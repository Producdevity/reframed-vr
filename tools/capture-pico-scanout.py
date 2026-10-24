#!/usr/bin/env python3
"""Capture a native Pico's linear dual-DMA framebuffer without changing scanout."""
import argparse
import base64
import ctypes as C
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import time
import uuid
import zlib


FORMATS = {name: int.from_bytes(name.encode(), 'little') for name in
           ('XR24', 'AR24', 'XB24', 'AB24', 'XR30', 'AR30', 'XB30', 'AB30')}
MAX_BYTES = 64 * 1024 * 1024


def pixel_rgb(word, fourcc):
    if fourcc not in FORMATS:
        raise ValueError('Unsupported framebuffer format: ' + fourcc)
    if fourcc.endswith('24'):
        low, green, high = word & 255, (word >> 8) & 255, (word >> 16) & 255
    else:
        low, green, high = ((word >> shift) & 1023 for shift in (0, 10, 20))
        low, green, high = ((value * 255 + 511) // 1023 for value in (low, green, high))
    return (high, green, low) if fourcc[1] == 'R' else (low, green, high)


def decode_rgb(native, width, height, pitch, fourcc):
    if not (0 < width <= 8192 and 0 < height <= 8192 and
            width * 4 <= pitch and len(native) == pitch * height <= MAX_BYTES):
        raise ValueError('Invalid native raster extent')
    pixel_rgb(0, fourcc)
    rgb = bytearray(width * height * 3)
    at = 0
    for y in range(height):
        for (word,) in struct.iter_unpack('<I', native[y * pitch:y * pitch + width * 4]):
            rgb[at:at + 3] = bytes(pixel_rgb(word, fourcc))
            at += 3
    return bytes(rgb)


def plane_layout(state, active):
    if len(state) > 2 * 1024 * 1024 or len(active) != 2:
        raise ValueError('Unexpected atomic state extent')
    blocks = {}
    pattern = r'^plane\[(\d+)\]:[^\n]*\n(.*?)(?=^(?:plane|crtc|connector)\[|\Z)'
    for match in re.finditer(pattern, state, re.M | re.S):
        key = int(match[1])
        if key in blocks:
            raise ValueError('Duplicate atomic plane')
        blocks[key] = match[2]
    layouts, rectangles = [], []
    for plane in active:
        block = blocks.get(plane['id'], '')

        def field(pattern):
            matches = re.findall(pattern, block, re.M)
            if len(matches) != 1:
                raise ValueError('Missing or ambiguous atomic framebuffer field')
            return matches[0]

        if int(field(r'^\s*fb=(\d+)$')) != plane['fb']:
            raise ValueError('Framebuffer changed during state query')
        name, code = field(r'^\s*format=(\w+) little-endian \((0x[0-9a-f]+)\)$')
        if name not in FORMATS or int(code, 16) != FORMATS[name]:
            raise ValueError('Unsupported or inconsistent framebuffer fourcc')
        layout = {'fourcc': name, 'fourcc_value': int(code, 16),
                  'modifier': int(field(r'^\s*modifier=(0x[0-9a-f]+)$'), 16),
                  'size': list(map(int, field(r'^\s*size=(\d+)x(\d+)$'))),
                  'pitch': int(field(r'^\s*pitch\[0\]=(\d+)$')),
                  'offset': int(field(r'^\s*offset\[0\]=(\d+)$'))}
        if (layout['modifier'] != 0 or layout['offset'] != 0 or
                layout['size'] != [1920, 3664] or
                not 7680 <= layout['pitch'] <= MAX_BYTES // 3664):
            raise ValueError('Only bounded, linear, single-plane Pico rasters are supported')
        rectangle = tuple(map(int, field(r'^\s*crtc-pos=(\d+)x(\d+)\+(\d+)\+(\d+)$')))
        source = tuple(map(float, field(r'^\s*src-pos=([0-9.]+)x([0-9.]+)\+([0-9.]+)\+([0-9.]+)$')))
        if source != (960., 3664., float(rectangle[2]), 0.) or re.search(r'(?:pitch|offset)\[[1-9]', block):
            raise ValueError('Unexpected source rectangle or extra framebuffer layer')
        if field(r'^\s*rotation=(\d+)$') != '1':
            raise ValueError('Unexpected DMA rotation')
        rectangles.append(rectangle)
        layouts.append(layout)
    if layouts[0] != layouts[1] or set(rectangles) != {(960, 3664, 0, 0), (960, 3664, 960, 0)}:
        raise ValueError('DMA halves do not share the expected framebuffer layout')
    return layouts[0]


class Planes(C.Structure):
    _fields_ = [('count', C.c_uint32), ('planes', C.POINTER(C.c_uint32))]


class Plane(C.Structure):
    _fields_ = [('count_formats', C.c_uint32), ('formats', C.POINTER(C.c_uint32)),
                *[(name, C.c_uint32) for name in
                  ('id', 'crtc', 'fb', 'crtc_x', 'crtc_y', 'x', 'y', 'possible', 'gamma_size')]]


class FB(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ('id', 'width', 'height', 'pitch', 'bpp', 'depth', 'handle')]


def drm_library():
    lib = C.CDLL('libdrm.so.2', use_errno=True)
    for name, args, result in [
        ('drmModeGetPlaneResources', [C.c_int], C.POINTER(Planes)),
        ('drmModeGetPlane', [C.c_int, C.c_uint32], C.POINTER(Plane)),
        ('drmModeGetFB', [C.c_int, C.c_uint32], C.POINTER(FB)),
        ('drmModeFreePlaneResources', [C.POINTER(Planes)], None),
        ('drmModeFreePlane', [C.POINTER(Plane)], None),
        ('drmModeFreeFB', [C.POINTER(FB)], None),
        ('drmPrimeHandleToFD', [C.c_int, C.c_uint32, C.c_uint32, C.POINTER(C.c_int)], C.c_int),
        ('drmSetClientCap', [C.c_int, C.c_uint64, C.c_uint64], C.c_int),
    ]:
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
    return lib


def active_planes(lib, fd):
    resources = lib.drmModeGetPlaneResources(fd)
    if not resources:
        raise OSError(C.get_errno(), 'drmModeGetPlaneResources')
    active = []
    try:
        if not 8 <= resources.contents.count <= 64:
            raise ValueError('Unexpected plane inventory')
        expected = {resources.contents.planes[i] for i in (6, 7)}
        for index in range(resources.contents.count):
            plane = lib.drmModeGetPlane(fd, resources.contents.planes[index])
            if not plane:
                raise OSError(C.get_errno(), 'drmModeGetPlane')
            try:
                value = plane.contents
                if value.fb and value.crtc:
                    active.append({'id': value.id, 'fb': value.fb, 'crtc': value.crtc})
            finally:
                lib.drmModeFreePlane(plane)
    finally:
        lib.drmModeFreePlaneResources(resources)
    if (len(active) != 2 or {p['id'] for p in active} != expected or
            len({p['fb'] for p in active}) != 1 or len({p['crtc'] for p in active}) != 1):
        raise ValueError('Expected exactly two active DMA halves sharing one framebuffer')
    return active


def capture():
    lib = drm_library()
    fd = os.open('/dev/dri/card0', os.O_RDWR | os.O_CLOEXEC)
    prime, fb, pixels, synced = C.c_int(-1), None, None, False
    try:
        if lib.drmSetClientCap(fd, 2, 1):
            raise OSError(C.get_errno(), 'DRM_CLIENT_CAP_UNIVERSAL_PLANES')
        for attempt in range(8):
            active = active_planes(lib, fd)
            state = Path('/sys/kernel/debug/dri/0/state').read_text()
            try:
                layout = plane_layout(state, active)
                break
            except ValueError:
                if attempt == 7:
                    raise
                time.sleep(.001)
        fb = lib.drmModeGetFB(fd, active[0]['fb'])
        if not fb:
            raise OSError(C.get_errno(), 'drmModeGetFB')
        value = fb.contents
        if (value.id != active[0]['fb'] or [value.width, value.height] != layout['size'] or
                value.pitch != layout['pitch'] or value.bpp != 32 or not value.handle):
            raise ValueError('Legacy framebuffer query disagrees with atomic state')
        if lib.drmPrimeHandleToFD(fd, value.handle, os.O_CLOEXEC, C.byref(prime)) or prime.value < 0:
            raise OSError(C.get_errno(), 'drmPrimeHandleToFD')
        fcntl.ioctl(prime.value, 0x40086200, struct.pack('<Q', 1))
        synced = True
        pixels = mmap.mmap(prime.value, value.pitch * value.height,
                           flags=mmap.MAP_SHARED, prot=mmap.PROT_READ)
        started = time.monotonic()
        native = pixels[:]
        ended = time.monotonic()
        layout.update(active=active, fb=value.id, bpp=value.bpp, depth=value.depth,
                      copy_started=started, copy_ended=ended)
    finally:
        if pixels is not None:
            pixels.close()
        try:
            if synced:
                fcntl.ioctl(prime.value, 0x40086200, struct.pack('<Q', 5))
        finally:
            if prime.value >= 0:
                os.close(prime.value)
            if fb:
                lib.drmModeFreeFB(fb)
            os.close(fd)
    layout.update(native_bytes=len(native), native_sha256=hashlib.sha256(native).hexdigest(),
                  dma_buf_read_sync=True, coherent_single_frame_verified=False,
                  optical_verified=False, colorimetry_verified=False)
    return native, state, layout


def capture_paused(unit):
    if not re.fullmatch(r'pico-steamvr-compositor-[a-z0-9-]+(?:\.service)?', unit):
        raise ValueError('Expected an explicitly selected Pico compositor unit')

    def command(arguments, check=True):
        return subprocess.run(arguments, capture_output=True, text=True, check=check, timeout=5)

    def identity():
        result = command(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID'])
        values = dict(line.split('=', 1) for line in result.stdout.splitlines())
        if values.get('ActiveState') != 'active' or int(values.get('MainPID', '0')) <= 1:
            raise ValueError('Selected compositor is not active')
        return int(values['MainPID'])

    pid = identity()
    watchdog = 'pico-scanout-resume-' + uuid.uuid4().hex
    resume = ['systemctl', 'kill', '--kill-whom=all', '--signal=CONT', unit]
    command(['systemd-run', '--quiet', '--unit='+watchdog, '--on-active=3s',
             '--timer-property=AccuracySec=10ms', '/usr/bin/systemctl',
             'kill', '--kill-whom=all', '--signal=CONT', unit])

    def require_waiting_watchdog():
        # An elapsed timer can remain active after its service has run.
        result = command(['systemctl', 'show', watchdog+'.timer', '-p', 'ActiveState',
                          '-p', 'SubState', '-p', 'LastTriggerUSecMonotonic'])
        values = dict(line.split('=', 1) for line in result.stdout.splitlines())
        if (values.get('ActiveState') != 'active' or values.get('SubState') != 'waiting' or
                values.get('LastTriggerUSecMonotonic') != '0'):
            raise ValueError('Capture resume watchdog is not waiting or has already fired')

    try:
        require_waiting_watchdog()
        command(['systemctl', 'kill', '--kill-whom=all', '--signal=STOP', unit])
        paused = time.monotonic()
        time.sleep(.1)
        native, state, metadata = capture()
        repeated, _, second = capture()
        if native != repeated or metadata['active'] != second['active']:
            raise ValueError('Framebuffer changed while the compositor was paused')
        if identity() != pid:
            raise ValueError('Compositor identity changed during capture')
        require_waiting_watchdog()
        metadata.update(stable_readback_verified=True, compositor_pause={
            'unit': unit, 'main_pid': pid, 'resume_watchdog_seconds': 3,
            'paused_at': paused, 'comparison_copy_started': second['copy_started'],
            'comparison_copy_ended': second['copy_ended'],
            'matching_readbacks': 2, 'sha256': hashlib.sha256(repeated).hexdigest()})
        return native, state, metadata
    finally:
        continued = command(resume, check=False)
        if continued.returncode == 0:
            command(['systemctl', 'stop', watchdog+'.timer', watchdog+'.service'], check=False)
        else:
            raise RuntimeError('Compositor resume failed; independent resume watchdog remains armed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-serial', required=True)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--pause-compositor-unit', help='Briefly pause this Pico compositor and require two identical readbacks')
    args = parser.parse_args()
    if (os.getuid() != 0 or os.uname().sysname != 'Linux' or os.uname().machine != 'aarch64' or
            Path('/proc/1/comm').read_text().strip() != 'systemd' or
            'androidboot.serialno=' + args.boot_serial not in Path('/proc/cmdline').read_text().split() or
            b'qcom,kona-iot' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')):
        raise ValueError('Expected an explicitly selected native Pico Linux session')
    if (str(uuid.UUID(args.boot_id)) != args.boot_id or
            Path('/proc/sys/kernel/random/boot_id').read_text().strip() != args.boot_id):
        raise ValueError('Native boot identity changed')
    if args.output.parent != Path('/run') or args.output.exists() or args.output.is_symlink():
        raise ValueError('Output must be a new private directory directly under /run')
    signal.alarm(20)
    native, state, metadata = (capture_paused(args.pause_compositor_unit)
                               if args.pause_compositor_unit is not None else capture())
    metadata.update(boot_id=args.boot_id, boot_serial=args.boot_serial)
    width, height = metadata['size']
    preview = bytearray()
    for y in range(184):
        for x in range(96):
            at = y * (height - 1) // 183 * metadata['pitch'] + x * (width - 1) // 95 * 4
            preview.extend(pixel_rgb(struct.unpack_from('<I', native, at)[0], metadata['fourcc']))
    metadata['preview'] = {'width': 96, 'height': 184, 'channels': 'RGB8_stored_components',
                           'sha256': hashlib.sha256(preview).hexdigest(),
                           'zlib_base64': base64.b64encode(zlib.compress(preview)).decode()}
    args.output.mkdir(mode=0o700)
    for name, data in [('native.bin', native), ('display-state.txt', state.encode()),
                       ('metadata.json', (json.dumps(metadata, indent=2) + '\n').encode())]:
        with (args.output / name).open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
    print('PICO_SCANOUT_CAPTURE ' + json.dumps(metadata), flush=True)


if __name__ == '__main__':
    main()
