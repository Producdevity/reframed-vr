#!/usr/bin/env python3
"""Inspect the pinned Neo3 speaker route; optionally test a bounded silent stream."""
import argparse
import ctypes as C
import ctypes.util
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import time
import xml.etree.ElementTree as ET

MIXER_SHA256 = '3eae1996a38943878160bc455851a1429212a289535df57fd7260132d061589d'
KERNEL_NOTES_SHA256 = '95fdc5f801b3c7330c42a3a59bb9d7d0d0ce2559ce403098defb9c69cdc47a91'
FRONTEND_MIXER = 'WSA_CDC_DMA_RX_0 Audio Mixer MultiMedia1'


def speaker_route(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MIXER_SHA256:
        raise ValueError('Requires the hash-pinned b1977 mixer_paths_pro.xml')
    root = ET.fromstring(raw)
    operations = [('WSA_RX0 Digital Mute', '1'), ('WSA_RX1 Digital Mute', '1')]
    for name, count in [('speaker', 18), ('deep-buffer-playback', 1)]:
        paths = [p for p in root.findall('path') if p.get('name') == name]
        if len(paths) != 1 or len(paths[0]) != count:
            raise ValueError('Stock route shape differs: ' + name)
        for ctl in paths[0]:
            if ctl.tag != 'ctl' or set(ctl.attrib) != {'name', 'value'}:
                raise ValueError('Expected direct stock mixer controls')
            operations.append((ctl.get('name'), ctl.get('value')))
    if len({name for name, _ in operations}) != len(operations):
        raise ValueError('Repeated route controls')
    return operations


def pcm_geometry(buffer_frames, period_frames):
    if not 1 <= period_frames <= 12000 or not period_frames <= buffer_frames <= 96000 or buffer_frames % period_frames:
        raise ValueError('Unexpected PCM buffer/period geometry')
    return ((48000 + period_frames - 1) // period_frames) * period_frames


def verify_drained(status, frames):
    fields = {}
    for line in status.splitlines():
        key, separator, value = line.partition(':')
        key = key.strip()
        if separator and key in ['state', 'delay', 'hw_ptr', 'appl_ptr']:
            if key in fields:
                raise ValueError('Repeated PCM completion field: ' + key)
            fields[key] = value.strip()
    if (fields.get('state') != 'SETUP' or fields.get('delay') != '0' or
            fields.get('hw_ptr') != str(frames) or fields.get('appl_ptr') != str(frames)):
        raise ValueError('PCM drain lacks matching completed hardware/application pointers')
    return fields


class Alsa:
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library('asound') or 'libasound.so.2')
        self.ctl = C.c_void_p()
        v, p, u, i, s = C.c_void_p, C.POINTER(C.c_void_p), C.c_uint, C.c_int, C.c_char_p
        declarations = {
            'snd_strerror': ([i], s), 'snd_ctl_open': ([p, s, i], i), 'snd_ctl_close': ([v], i),
            'snd_ctl_elem_info': ([v, v], i), 'snd_ctl_elem_read': ([v, v], i),
            'snd_ctl_elem_write': ([v, v], i),
            'snd_ctl_elem_info_set_name': ([v, s], None),
            'snd_ctl_elem_info_set_interface': ([v, i], None),
            'snd_ctl_elem_info_set_item': ([v, u], None),
            'snd_ctl_elem_info_get_item_name': ([v], s),
            'snd_pcm_open': ([p, s, i, i], i), 'snd_pcm_close': ([v], i),
            'snd_pcm_format_value': ([s], i),
            'snd_pcm_set_params': ([v, i, i, u, u, i, u], i),
            'snd_pcm_get_params': ([v, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong)], i),
            'snd_pcm_writei': ([v, v, C.c_ulong], C.c_long),
            'snd_pcm_wait': ([v, i], i), 'snd_pcm_drain': ([v], i), 'snd_pcm_drop': ([v], i),
            'snd_pcm_state': ([v], i),
        }
        for kind in ['info', 'value']:
            declarations['snd_ctl_elem_' + kind + '_malloc'] = ([p], i)
            declarations['snd_ctl_elem_' + kind + '_free'] = ([v], None)
        for name in ['type', 'count', 'numid', 'items']:
            declarations['snd_ctl_elem_info_get_' + name] = ([v], u)
        declarations['snd_ctl_elem_info_is_writable'] = ([v], i)
        for name in ['min', 'max', 'step']:
            declarations['snd_ctl_elem_info_get_' + name] = ([v], C.c_long)
        declarations['snd_ctl_elem_value_set_numid'] = ([v, u], None)
        for name, result in [('boolean', C.c_long), ('integer', C.c_long), ('enumerated', u)]:
            declarations['snd_ctl_elem_value_get_' + name] = ([v, u], result)
            declarations['snd_ctl_elem_value_set_' + name] = ([v, u, result], None)
        for name, (arguments, result) in declarations.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = arguments, result
        self.check(self.lib.snd_ctl_open(C.byref(self.ctl), b'hw:0', 1))

    def check(self, result):
        if result < 0:
            raise OSError(-result, self.lib.snd_strerror(result).decode())
        return result

    def close(self):
        if self.ctl:
            self.check(self.lib.snd_ctl_close(self.ctl))
            self.ctl = C.c_void_p()

    def resolve(self, name, text):
        info = C.c_void_p()
        self.check(self.lib.snd_ctl_elem_info_malloc(C.byref(info)))
        try:
            self.lib.snd_ctl_elem_info_set_interface(info, 2)
            self.lib.snd_ctl_elem_info_set_name(info, name.encode())
            self.check(self.lib.snd_ctl_elem_info(self.ctl, info))
            kind = self.lib.snd_ctl_elem_info_get_type(info)
            count = self.lib.snd_ctl_elem_info_get_count(info)
            # msm-pcm-routing-v2.c uses only value[0] of this SOC_DOUBLE_EXT control.
            frontend = name == FRONTEND_MIXER and kind == 1 and count == 2
            if kind not in [1, 2, 3] or (count != 1 and not frontend):
                raise ValueError('Unsupported mixer type/count: ' + name)
            if not self.lib.snd_ctl_elem_info_is_writable(info):
                raise ValueError('Mixer control is not writable: ' + name)
            control = {'name': name, 'numid': self.lib.snd_ctl_elem_info_get_numid(info),
                       'type': kind, 'count': count, 'value_index': 0}
            if kind == 3:
                items = self.lib.snd_ctl_elem_info_get_items(info)
                if not 1 <= items <= 256:
                    raise ValueError('Invalid enum size: ' + name)
                labels = []
                for item in range(items):
                    self.lib.snd_ctl_elem_info_set_item(info, item)
                    self.check(self.lib.snd_ctl_elem_info(self.ctl, info))
                    labels.append(self.lib.snd_ctl_elem_info_get_item_name(info).decode())
                if labels.count(text) != 1:
                    raise ValueError('Stock enum value absent or ambiguous: ' + name + '=' + text)
                control.update(items=labels, target=labels.index(text))
            else:
                minimum = 0 if kind == 1 else self.lib.snd_ctl_elem_info_get_min(info)
                maximum = 1 if kind == 1 else self.lib.snd_ctl_elem_info_get_max(info)
                step = 1 if kind == 1 else self.lib.snd_ctl_elem_info_get_step(info)
                value = int(text, 0)
                if not minimum <= value <= maximum or (step > 0 and (value - minimum) % step):
                    raise ValueError('Stock value outside native mixer range: ' + name)
                control.update(minimum=minimum, maximum=maximum, step=step, target=value)
            return control
        finally:
            self.lib.snd_ctl_elem_info_free(info)

    def value(self, control, new=None):
        value = C.c_void_p()
        self.check(self.lib.snd_ctl_elem_value_malloc(C.byref(value)))
        try:
            self.lib.snd_ctl_elem_value_set_numid(value, control['numid'])
            kind = {1: 'boolean', 2: 'integer', 3: 'enumerated'}[control['type']]
            if new is None:
                self.check(self.lib.snd_ctl_elem_read(self.ctl, value))
                return getattr(self.lib, 'snd_ctl_elem_value_get_' + kind)(value, 0)
            getattr(self.lib, 'snd_ctl_elem_value_set_' + kind)(value, 0, new)
            self.check(self.lib.snd_ctl_elem_write(self.ctl, value))
        finally:
            self.lib.snd_ctl_elem_value_free(value)

    def silence(self, report):
        pcm = C.c_void_p()
        self.check(self.lib.snd_pcm_open(C.byref(pcm), b'hw:0,0', 0, 1))
        try:
            sample_format = self.check(self.lib.snd_pcm_format_value(b'S16_LE'))
            self.check(self.lib.snd_pcm_set_params(pcm, sample_format, 3, 2, 48000, 0, 50000))
            buffer_size, period_size = C.c_ulong(), C.c_ulong()
            self.check(self.lib.snd_pcm_get_params(pcm, C.byref(buffer_size), C.byref(period_size)))
            target = pcm_geometry(buffer_size.value, period_size.value)
            zeros = C.create_string_buffer(period_size.value * 4)
            frames, deadline, statuses = 0, time.monotonic() + 5, []
            report['pcm'] = {'frames': 0, 'target_frames': target,
                             'buffer_frames': buffer_size.value, 'period_frames': period_size.value,
                             'rate': 48000, 'channels': 2, 'format': 'S16_LE',
                             'content': 'zeros', 'statuses': statuses, 'drain_waits': []}
            while frames < target:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Silent PCM write deadline')
                # The vendor copy callback consumes one DSP slot per call, even for short writes.
                count = self.lib.snd_pcm_writei(pcm, zeros, period_size.value)
                if count == -errno.EAGAIN:
                    self.check(self.lib.snd_pcm_wait(pcm, 20))
                    continue
                self.check(count)
                if count != period_size.value:
                    raise ValueError('Partial vendor PCM period write')
                frames += count
                report['pcm']['frames'] = frames
                if len(statuses) < 64:
                    statuses.append(Path('/proc/asound/card0/pcm0p/sub0/status').read_text())
            if self.lib.snd_pcm_state(pcm) != 3:
                raise ValueError('PCM must be RUNNING before drain')
            result = self.lib.snd_pcm_drain(pcm)
            if result != -errno.EAGAIN:
                self.check(result)
            while self.lib.snd_pcm_state(pcm) != 1:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Silent PCM drain deadline')
                wait_result = self.lib.snd_pcm_wait(pcm, 20)
                state = self.lib.snd_pcm_state(pcm)
                report['pcm']['drain_waits'].append({'wait_result': wait_result, 'state': state})
                if wait_result < 0 and not (wait_result == -errno.EIO and state == 1):
                    self.check(wait_result)
                if state not in [1, 5]:
                    raise ValueError('Unexpected PCM state during drain: ' + str(state))
            # This 4.19 kernel returns EAGAIN for every nonblocking drain, even in SETUP.
            status = Path('/proc/asound/card0/pcm0p/sub0/status').read_text()
            report['pcm']['final_status'] = status
            report['pcm']['completion'] = verify_drained(status, frames)
        finally:
            try:
                self.lib.snd_pcm_drop(pcm)
            finally:
                self.check(self.lib.snd_pcm_close(pcm))


def transaction(alsa, controls, play, report):
    originals = [(control, alsa.value(control)) for control in controls]
    report['originals'] = [{'numid': c['numid'], 'value': v} for c, v in originals]
    attempted, restored = [], []
    try:
        for control, old in originals:
            attempted.append((control, old))
            alsa.value(control, control['target'])
            actual = alsa.value(control)
            if actual != control['target']:
                raise ValueError(f"Mixer write readback differs: {control['name']} expected={control['target']} actual={actual}")
        play(report)
    finally:
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        try:
            for control, old in reversed(attempted):
                try:
                    alsa.value(control, old)
                    if alsa.value(control) != old:
                        raise ValueError('Restore readback differs')
                    restored.append({'numid': control['numid'], 'restored': True})
                except Exception as error:
                    restored.append({'numid': control['numid'], 'restored': False, 'error': str(error)})
            report['rollback'] = restored
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        if any(not item['restored'] for item in restored):
            raise RuntimeError('Audio mixer rollback incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--mixer-xml', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--test-silence', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64' or os.geteuid() != 0:
        parser.error('Requires native ARM64 Linux root')
    if not re.fullmatch('[a-f0-9-]{36}', args.boot_id) or not re.fullmatch('[A-Za-z0-9_.-]{1,64}', args.boot_serial):
        parser.error('Invalid boot identity')
    if (Path('/proc/sys/kernel/random/boot_id').read_text().strip() != args.boot_id or
            'androidboot.serialno=' + args.boot_serial not in Path('/proc/cmdline').read_text().split() or
            hashlib.sha256(Path('/sys/kernel/notes').read_bytes()).hexdigest() != KERNEL_NOTES_SHA256 or
            Path('/proc/asound/card0/id').read_text().strip() != 'konamtpsndcard' or
            Path('/sys/devices/platform/soc/soc:hw_version/version').read_text().strip() != 'B4'):
        parser.error('Native boot, kernel, sound card or hardware version differs')
    operations = speaker_route(args.mixer_xml)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {'status': 'started', 'boot_id': args.boot_id, 'mixer_sha256': MIXER_SHA256,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'test_silence': args.test_silence, 'audible_output_verified': False}
    def interrupted(number, frame):
        raise KeyboardInterrupt('Interrupted by signal ' + str(number))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    alsa = None
    lock = -1
    try:
        lock = os.open('/run/lock/reframed-pico-audio-route.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        st = os.fstat(lock)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_mode & 0o077:
            raise ValueError('Unsafe audio diagnostic lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        alsa = Alsa()
        controls = [alsa.resolve(name, value) for name, value in operations]
        report['controls'] = controls
        if args.test_silence:
            statuses = list(Path('/proc/asound/card0').glob('pcm*/sub*/status'))
            if not statuses or any(p.read_text().strip() != 'closed' for p in statuses):
                raise ValueError('Requires an idle sound card owned by this diagnostic session')
            transaction(alsa, controls, alsa.silence, report)
        report['status'] = 'silent-pcm-passed' if args.test_silence else 'preflight-passed'
    except BaseException as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        try:
            if alsa:
                try:
                    alsa.close()
                except Exception as error:
                    report.update(status='failed', close_error=str(error))
                    raise
        finally:
            try:
                (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            finally:
                if lock >= 0:
                    os.close(lock)


if __name__ == '__main__':
    main()
