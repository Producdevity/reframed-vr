"""Own one controller worker process within an already verified native sensor session."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import time
import uuid

# Worker status carries Linux errno values, including when inspected on macOS.
MOTION_RECEIVE_TIMEOUT = -110


class ControllerSession:
    def __init__(self, build, directory, boot_id, *, seconds, environment,
                 companion_accel=False, motion=None):
        if str(uuid.UUID(boot_id)) != boot_id or type(seconds) is not int or not 1 <= seconds <= 3600:
            raise ValueError('Invalid boot identity or duration')
        self.build = Path(build).resolve()
        directory = Path(directory)
        if not directory.is_absolute():
            raise ValueError('Session directory must be absolute and new')
        self.directory = directory.parent.resolve() / directory.name
        self.channel = self.directory / 'input.channel'
        self.instance = f'{secrets.randbits(64) or 1:016x}'
        self.boot_id, self.seconds = boot_id, seconds
        self.environment = dict(environment)
        self.companion_accel = bool(companion_accel)
        self.motion = None
        if motion is not None:
            if (not isinstance(motion, dict) or set(motion) - {'generation', 'left', 'right'} or
                    not isinstance(motion.get('generation'), str) or
                    not re.fullmatch('[0-9a-f]{16}', motion.get('generation', '')) or
                    not int(motion['generation'], 16) or not (set(motion) & {'left', 'right'})):
                raise ValueError('Motion requires an explicit generation and connected-hand settings')
            self.motion = {'generation': motion['generation']}
            fields = {'connected', 'revision_byte', 'double_scale_byte', 'axis_reversal_bypass_byte'}
            for hand in ('left', 'right'):
                if hand not in motion:
                    continue
                settings = motion[hand]
                if (not isinstance(settings, dict) or set(settings) != fields or
                        settings['connected'] is not True or any(
                            type(settings[key]) is not int or not 0 <= settings[key] <= 255
                            for key in fields - {'connected'})):
                    raise ValueError('Each motion hand requires verified connected stock byte settings')
                self.motion[hand] = dict(settings)
        self.motion_channel = self.directory / 'motion.channel'
        self.motion_base = self.motion_channel
        self.motion_ready = self.motion_stop_result = None
        self.motion_channel_identity = None
        self.motion_restart = None
        self.motion_history = []
        self.motion_resumed = self.motion_resume_error = None
        self.motion_recovery_pending = False
        self.process = None
        self.reader = None
        self.pending = b''
        self.ready = None
        self.stop_result = None
        self.waiting = self.released = False
        self.channel_identity = None

    def start(self):
        if self.process is not None:
            raise RuntimeError('A worker session cannot be restarted')
        manifest = json.loads((self.build / 'build.json').read_text())
        binary = self.build / 'pico-controller-input'
        if (manifest.get('status') != 'compiled' or binary.is_symlink() or
                hashlib.sha256(binary.read_bytes()).hexdigest() != manifest.get('binary_sha256')):
            raise ValueError('Worker differs from its verified build manifest')
        self.directory.mkdir(mode=0o755)
        self.directory.chmod(0o755)
        command = [str(binary), '--boot-id', self.boot_id, '--channel', str(self.channel),
                   '--instance', self.instance, '--seconds', str(self.seconds)]
        if self.companion_accel:
            command.append('--companion-accel')
        if self.motion:
            command += ['--motion-channel', str(self.motion_channel),
                        '--motion-generation', self.motion['generation']]
            for hand in ('left', 'right'):
                if hand in self.motion:
                    settings = self.motion[hand]
                    value = ':'.join(f'{settings[key]:02x}' for key in
                                     ('revision_byte', 'double_scale_byte', 'axis_reversal_bypass_byte'))
                    command += ['--' + hand + '-motion-config', value]
        outputs = []
        try:
            for name in ('stdout.log', 'stderr.log'):
                fd = os.open(self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                outputs.append(os.fdopen(fd, 'wb'))
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE if self.motion else subprocess.DEVNULL,
                                            stdout=outputs[0], stderr=outputs[1],
                                            env=self.environment, close_fds=True)
        finally:
            for stream in outputs:
                stream.close()
        self.reader = (self.directory / 'stdout.log').open('rb', buffering=0)
        record = {'pid': self.process.pid, 'boot_id': self.boot_id, 'instance': self.instance,
                  'command': command, 'binary_sha256': manifest['binary_sha256'], 'motion': self.motion}
        fd = os.open(self.directory / 'session.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')

    def _read_status(self):
        if self.reader is None:
            return
        while data := self.reader.read(65536):
            self._parse_status(data)

    def _parse_status(self, data):
        self.pending += data
        lines = self.pending.split(b'\n')
        self.pending = lines.pop()
        if len(self.pending) > 8192:
            raise RuntimeError('Oversized worker status line')
        for raw in lines:
            line = raw.decode(errors='replace')
            if line.startswith('PICO_CONTROLLER_READY '):
                match = re.fullmatch(r'PICO_CONTROLLER_READY instance=([0-9a-f]{16}) '
                                     r'companion_accel=([01]) rc=(-?\d+)', line)
                if (not match or self.ready is not None or match[1] != self.instance or
                        int(match[2]) != self.companion_accel):
                    raise RuntimeError('Worker readiness identity differs')
                self.ready = int(match[3])
            elif line.startswith('PICO_CONTROLLER_STOP '):
                match = re.fullmatch(r'PICO_CONTROLLER_STOP rc=(-?\d+) controller_rc=(-?\d+) '
                                     r'accel_rc=(-?\d+) left=(\d+) right=(\d+)', line)
                if not match or self.stop_result is not None:
                    raise RuntimeError('Invalid worker stop result')
                self.stop_result = dict(zip(('rc', 'controller_rc', 'accel_rc', 'left', 'right'),
                                            map(int, match.groups())))
            elif line.startswith('PICO_CONTROLLER_MOTION_READY '):
                match = re.fullmatch(r'PICO_CONTROLLER_MOTION_READY instance=([0-9a-f]{16}) '
                                     r'generation=([0-9a-f]{16}) mask=([1-3]) rc=(-?\d+)', line)
                mask = sum(1 << i for i, hand in enumerate(('left', 'right'))
                           if self.motion and hand in self.motion)
                if (not match or not self.motion or self.motion_ready is not None or
                        match[1] != self.instance or match[2] != self.motion['generation'] or
                        int(match[3]) != mask):
                    raise RuntimeError('Motion readiness identity differs')
                self.motion_ready = int(match[4])
            elif line.startswith('PICO_CONTROLLER_MOTION_STOP '):
                match = re.fullmatch(r'PICO_CONTROLLER_MOTION_STOP rc=(-?\d+) samples=(\d+)', line)
                if not match or not self.motion or self.motion_stop_result is not None:
                    raise RuntimeError('Invalid motion stop result')
                self.motion_stop_result = {'rc': int(match[1]), 'samples': int(match[2])}
                self.motion_history.append({'generation': self.motion['generation'],
                                            **self.motion_stop_result})
                self.motion_resumed = None
            elif line.startswith('PICO_CONTROLLER_MOTION_RESUMED '):
                match = re.fullmatch(r'PICO_CONTROLLER_MOTION_RESUMED instance=([0-9a-f]{16}) '
                                     r'generation=([0-9a-f]{16}) received_ns=(\d+) deadline_ns=(\d+)', line)
                if (not match or not self.motion or match[1] != self.instance or
                        match[2] != self.motion['generation'] or self.waiting or
                        self.motion_stop_result is None or
                        self.motion_stop_result['rc'] != MOTION_RECEIVE_TIMEOUT):
                    raise RuntimeError('Unexpected motion resumption identity or state')
                received, deadline = int(match[3]), int(match[4])
                if (received <= 0 or not received <= deadline <= received + 100000000 or
                        (self.motion_resumed is not None and received <= self.motion_resumed['received_ns'])):
                    raise RuntimeError('Invalid motion resumption time')
                self.motion_resumed = {'received_ns': received, 'deadline_ns': deadline}
            elif line.startswith('PICO_CONTROLLER_MOTION_RESUME_FAILED '):
                match = re.fullmatch(r'PICO_CONTROLLER_MOTION_RESUME_FAILED generation=([0-9a-f]{16}) '
                                     r'rc=(-\d+)', line)
                if (not match or not self.motion or match[1] != self.motion['generation'] or
                        self.motion_resume_error is not None or self.motion_stop_result is None):
                    raise RuntimeError('Unexpected motion resumption failure')
                self.motion_resume_error = int(match[2])
            elif line.startswith('PICO_CONTROLLER_MOTION_RESTART '):
                match = re.fullmatch(r'PICO_CONTROLLER_MOTION_RESTART previous=([0-9a-f]{16}) '
                                     r'generation=([0-9a-f]{16}) rc=(-?\d+)', line)
                restart = self.motion_restart
                if (not match or restart is None or restart['rc'] is not None or
                        (match[1], match[2]) != (restart['previous'], restart['generation'])):
                    raise RuntimeError('Unexpected motion restart acknowledgment')
                restart['rc'] = int(match[3])
                if not restart['rc']:
                    if self.motion_stop_result is None:
                        raise RuntimeError('Motion restarted without stopping the old generation')
                    self.motion['generation'] = restart['generation']
                    self.motion_channel = Path(restart['path'])
                    self.motion_ready = self.motion_stop_result = self.motion_channel_identity = None
                    self.motion_resumed = self.motion_resume_error = None
            elif line == 'PICO_CONTROLLER_WAIT_DSP_OFFLINE':
                if self.stop_result is None or self.waiting:
                    raise RuntimeError('Worker shutdown order differs')
                self.waiting = True
            elif line == 'PICO_CONTROLLER_RELEASED_DSP_OFFLINE':
                if not self.waiting or self.released:
                    raise RuntimeError('Worker released before shutdown acknowledgment')
                self.released = True

    def _wait(self, predicate, timeout):
        if self.process is None or timeout < 0:
            raise ValueError('Requires a started worker and nonnegative timeout')
        deadline = time.monotonic() + timeout
        while True:
            self._read_status()
            if predicate():
                return
            if self.process.poll() is not None:
                self._read_status()
                if predicate():
                    return
                self.reader.close()
                self.reader = None
                raise RuntimeError(f'Worker exited without expected acknowledgment: {self.process.returncode}')
            if time.monotonic() >= deadline:
                # A timeout must not kill a process that can still own DSP DMA.
                raise TimeoutError('Worker still owned; stop other sensor clients and SLPI before release')
            time.sleep(0.01)

    def _verify_channel(self):
        fd = os.open(self.channel, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            header = os.read(fd, 16)
            identity = (info.st_dev, info.st_ino)
            if (not stat.S_ISREG(info.st_mode) or info.st_size != 128 or
                    info.st_uid != os.geteuid() or info.st_mode & 0o022 or
                    len(header) != 16 or struct.unpack('<QQ', header) !=
                    (0x5256504943430001, int(self.instance, 16)) or
                    self.channel_identity not in (None, identity)):
                raise RuntimeError('Worker channel identity or permissions differ')
            self.channel_identity = identity
        finally:
            os.close(fd)

    def wait_ready(self, timeout):
        self._wait(lambda: self.ready is not None, timeout)
        if self.ready or self.waiting or self.process.poll() is not None:
            raise RuntimeError(f'Worker did not become usable: rc={self.ready}')
        self._verify_channel()

    def steamvr_environment(self):
        self._read_status()
        if self.ready != 0 or self.waiting or self.process is None or self.process.poll() is not None:
            raise RuntimeError('Worker is not ready for SteamVR')
        self._verify_channel()
        return {'PICO_STEAMVR_CONTROLLER_CHANNEL': str(self.channel),
                'PICO_STEAMVR_CONTROLLER_INSTANCE': self.instance}

    def _motion_header(self):
        fd = os.open(self.motion_channel, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            data = os.read(fd, 64)
            identity = (info.st_dev, info.st_ino)
            if (not stat.S_ISREG(info.st_mode) or info.st_size != 32832 or
                    info.st_uid != os.geteuid() or info.st_mode & 0o022 or len(data) != 64 or
                    self.motion_channel_identity not in (None, identity)):
                raise RuntimeError('Motion channel identity or permissions differ')
            magic, instance, generation, sequence, active, left, right, received = struct.unpack('<8Q', data)
            if ((magic, instance, generation) !=
                    (0x525650434d430001, int(self.instance, 16), int(self.motion['generation'], 16)) or
                    active not in (0, 1) or sequence == (1 << 64) - 1):
                raise RuntimeError('Motion channel binding or active state differs')
            self.motion_channel_identity = identity
            return sequence, active, left, right, received
        finally:
            os.close(fd)

    def _motion_available(self):
        if not self.motion:
            raise RuntimeError('Motion was not enabled for this worker')
        if self.motion_restart is not None and self.motion_restart['rc'] is None:
            return False
        if (self.ready not in (None, 0) or self.motion_ready not in (None, 0) or
                self.motion_stop_result is not None or self.waiting):
            raise RuntimeError('Motion worker is stopped or failed')
        if self.ready is None or self.motion_ready is None:
            return False
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError('Motion worker is stopped or failed')
        sequence, active, left, right, received = self._motion_header()
        if active != 1:
            raise RuntimeError('Motion channel is stopped')
        if not sequence or any(not stamp for hand, stamp in [('left', left), ('right', right)]
                                   if hand in self.motion):
            return False
        now = time.monotonic_ns()
        if not received or received > now or any(not 0 <= now - stamp <= 100000000
                for hand, stamp in [('left', left), ('right', right)] if hand in self.motion):
            raise RuntimeError('Motion channel has no fresh capture times')
        return True

    def wait_motion_ready(self, timeout):
        self._wait(self._motion_available, timeout)

    def motion_endpoint(self):
        if not self.motion:
            raise RuntimeError('Motion was not enabled for this worker')
        if self.motion_restart is not None and self.motion_restart['rc'] is None:
            raise RuntimeError('Motion restart is awaiting acknowledgment')
        return {'path': str(self.motion_channel), 'instance': self.instance,
                'generation': self.motion['generation']}

    def motion_binding(self):
        self._read_status()
        if not self._motion_available():
            raise RuntimeError('Motion has no samples yet')
        return self.motion_endpoint()

    def restart_motion(self, generation, timeout):
        """Start a new motion epoch; the consumer must reset its estimator before attaching.

        This does not restart RPC or release shared DSP buffers. Retire the old
        consumer on its stopped channel, then reset before attaching anew.
        A timeout leaves the request pending; finish it with
        wait_motion_restart rather than issuing another request or killing RPC.
        """
        self._read_status()
        if (not isinstance(generation, str) or not re.fullmatch('[0-9a-f]{16}', generation) or
                not self.motion or int(generation, 16) <= int(self.motion['generation'], 16) or timeout < 0):
            raise ValueError('Motion restart requires an increasing nonzero generation and timeout')
        if (self.ready != 0 or self.waiting or self.process is None or self.process.poll() is not None or
                self.motion_ready != 0 or
                (self.motion_restart is not None and self.motion_restart['rc'] is None)):
            raise RuntimeError('Worker cannot accept a motion restart')
        self.motion_restart = {'previous': self.motion['generation'], 'generation': generation,
                               'path': str(self.motion_base) + '.' + generation, 'rc': None}
        command = f'restart {self.motion["generation"]} {generation}\n'.encode('ascii')
        self.process.stdin.write(command)
        self.process.stdin.flush()
        self.wait_motion_restart(timeout)

    def wait_motion_restart(self, timeout):
        if self.motion_restart is None:
            raise RuntimeError('No motion restart was requested')
        self._wait(lambda: self.motion_restart['rc'] is not None, timeout)
        if self.motion_restart['rc']:
            raise RuntimeError(f'Motion restart failed: rc={self.motion_restart["rc"]}')
        self._wait(lambda: self.motion_ready is not None, timeout)
        if self.motion_ready:
            raise RuntimeError('Restarted motion generation did not initialize')

    def recover_motion(self, timeout):
        """Poll for fresh post-timeout IMU data and return a new, ready endpoint.

        The caller atomically publishes it to a consumer that resets its
        estimator before rebinding, retaining the head/world generation.
        None means no eligible data. A timeout leaves the operation pending;
        another call completes it without resending or releasing DSP ownership.
        """
        if timeout < 0 or not self.motion:
            raise ValueError('Motion recovery requires enabled motion and a nonnegative timeout')
        self._read_status()
        if not self.motion_recovery_pending:
            if (self.ready != 0 or self.waiting or self.process is None or self.process.poll() is not None or
                    self.motion_stop_result is None or self.motion_stop_result['rc'] != MOTION_RECEIVE_TIMEOUT or
                    self.motion_resumed is None or self.motion_resume_error is not None or
                    (self.motion_restart is not None and self.motion_restart['rc'] not in (None, 0))):
                return None
            now = time.monotonic_ns()
            if now < self.motion_resumed['received_ns']:
                raise RuntimeError('Motion resumption clock is in the future')
            if now > self.motion_resumed['deadline_ns']:
                return None
            if self._motion_header()[1] != 0:
                raise RuntimeError('Timed-out motion channel is not stopped')
            if self.motion_restart is not None and self.motion_restart['rc'] is None:
                raise RuntimeError('Another motion restart is pending')
            generation = max(int(self.motion['generation'], 16),
                             int(self.motion_restart['generation'], 16) if self.motion_restart else 0) + 1
            if generation >= 1 << 64:
                raise RuntimeError('Motion generation exhausted')
            self.motion_recovery_pending = True
            try:
                self.restart_motion(f'{generation:016x}', timeout)
            except TimeoutError:
                raise
            except Exception:
                self.motion_recovery_pending = False
                raise
        try:
            self.wait_motion_restart(timeout)
            self.wait_motion_ready(timeout)
            endpoint = self.motion_binding()
        except TimeoutError:
            raise
        except Exception:
            self.motion_recovery_pending = False
            raise
        self.motion_recovery_pending = False
        return endpoint

    def request_stop(self):
        if self.process is None:
            raise RuntimeError('Worker was not started')
        if self.process.poll() is None:
            self.process.terminate()

    def wait_rpc_stopped(self, timeout):
        self._wait(lambda: self.waiting, timeout)
        return dict(self.stop_result)

    def finish(self, timeout):
        if not self.waiting:
            raise RuntimeError('Wait for RPC shutdown before stopping the shared DSP and finishing')
        self._wait(lambda: self.released, timeout)
        result = self.process.wait(timeout=timeout)
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.reader.close()
        self.reader = None
        return result
