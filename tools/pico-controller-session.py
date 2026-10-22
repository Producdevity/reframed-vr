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


class ControllerSession:
    def __init__(self, build, directory, boot_id, *, seconds, environment, companion_accel=False):
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
        outputs = []
        try:
            for name in ('stdout.log', 'stderr.log'):
                fd = os.open(self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                outputs.append(os.fdopen(fd, 'wb'))
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                            stdout=outputs[0], stderr=outputs[1],
                                            env=self.environment, close_fds=True)
        finally:
            for stream in outputs:
                stream.close()
        self.reader = (self.directory / 'stdout.log').open('rb', buffering=0)
        record = {'pid': self.process.pid, 'boot_id': self.boot_id, 'instance': self.instance,
                  'command': command, 'binary_sha256': manifest['binary_sha256']}
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
        self.reader.close()
        self.reader = None
        return result
