#!/usr/bin/env python3
"""Make a host-side lens-corrected preview from a retained Pico scanout."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def coordinates(view, u, v, channel):
    r = view['rotation']
    model = view['analytic_distortion']
    logical_u = (r[0] * (2*u-1) + r[1] * (1-2*v) + 1) / 2
    logical_v = (1 - r[2] * (2*u-1) - r[3] * (1-2*v)) / 2
    x = model['tangent_scale'][0]*logical_u + model['tangent_offset'][0]
    y = model['tangent_scale'][1]*logical_v + model['tangent_offset'][1]
    rsq = x*x + y*y
    scale = np.zeros_like(rsq)
    for coefficient in reversed(model['radial_coefficients']):
        scale = scale*rsq + coefficient
    chromatic = model['chromatic_coefficients']
    if channel != 1:
        at = 0 if channel == 0 else 2
        scale *= 1 + chromatic[at] + rsq*chromatic[at+1] + np.sqrt(rsq)*chromatic[4+channel//2]
    left, right, up, down = map(math.tan, view['fov'])
    return (x*scale-left)/(right-left), (up-y*scale)/(up-down)


def inverse_coordinates(view, target_u, target_v, channel):
    u = np.full_like(target_u, .5)
    v = np.full_like(target_v, .5)
    epsilon = 1e-5
    for _ in range(24):
        a, b = coordinates(view, u, v, channel)
        ex, ey = a-target_u, b-target_v
        if np.max(np.maximum(np.abs(ex), np.abs(ey))) < 1e-8:
            break
        ax, bx = coordinates(view, u+epsilon, v, channel)
        ay, by = coordinates(view, u, v+epsilon, channel)
        j00, j10 = (ax-a)/epsilon, (bx-b)/epsilon
        j01, j11 = (ay-a)/epsilon, (by-b)/epsilon
        determinant = j00*j11-j01*j10
        safe = np.where(np.abs(determinant) > 1e-12, determinant, np.nan)
        du = np.nan_to_num((j11*ex-j01*ey)/safe, nan=0, posinf=0, neginf=0)
        dv = np.nan_to_num((-j10*ex+j00*ey)/safe, nan=0, posinf=0, neginf=0)
        u = np.clip(u-np.clip(du, -.2, .2), -.25, 1.25)
        v = np.clip(v-np.clip(dv, -.2, .2), -.25, 1.25)
    a, b = coordinates(view, u, v, channel)
    residual = np.maximum(np.abs(a-target_u), np.abs(b-target_v))
    valid = np.isfinite(residual) & (residual < 1e-6) & (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    return u, v, valid, residual


def sample(pixels, u, v):
    height, width = pixels.shape
    x = np.clip(u*width-.5, 0, width-1)
    y = np.clip(v*height-.5, 0, height-1)
    ix, iy = x.astype(np.int32), y.astype(np.int32)
    nx, ny = np.minimum(ix+1, width-1), np.minimum(iy+1, height-1)
    fx, fy = x-ix, y-iy
    return ((1-fy)*((1-fx)*pixels[iy, ix]+fx*pixels[iy, nx]) +
            fy*((1-fx)*pixels[ny, ix]+fx*pixels[ny, nx]))


def render_eye(pixels, view, width, height):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    coverage = np.zeros((height, width), dtype=bool)
    maximum_residual = 0.
    vx, vy, vw, vh = view['viewport']
    plane = pixels[vy:vy+vh, vx:vx+vw]
    for first in range(0, height, 64):
        last = min(height, first+64)
        tu, tv = np.meshgrid((np.arange(width)+.5)/width, (np.arange(first, last)+.5)/height)
        valid = np.ones(tu.shape, dtype=bool)
        channels = []
        for channel in range(3):
            u, v, inside, residual = inverse_coordinates(view, tu, tv, channel)
            valid &= inside
            if np.any(inside):
                maximum_residual = max(maximum_residual, float(np.max(residual[inside])))
            channels.append(sample(plane[:, :, channel], u, v))
        result = np.stack(channels, axis=-1)
        result[~valid] = 0
        image[first:last] = np.clip(np.rint(result), 0, 255).astype(np.uint8)
        coverage[first:last] = valid
    return image, coverage, maximum_residual


def eye_size(view, width):
    display = view.get('display')
    if (not isinstance(display, list) or len(display) != 2 or
            any(type(x) is not int or not 1 <= x <= 16384 for x in display)):
        raise ValueError('Invalid per-eye display dimensions')
    height = round(width*display[1]/display[0])
    if not 1 <= height <= 3664:
        raise ValueError('Unsupported per-eye output aspect')
    return width, height


def load_capture(directory, optics):
    metadata_path, raw_path = directory/'metadata.json', directory/'native.bin'
    if metadata_path.stat().st_size > 65536 or optics.stat().st_size > 262144:
        raise ValueError('Metadata or optical profile exceeds its size limit')
    metadata = json.loads(metadata_path.read_text())
    profile = json.loads(optics.read_text())
    if (profile.get('schema_version') not in (2, 3) or profile.get('device') != 'PICOA7H10' or
            profile.get('serial') != metadata.get('boot_serial') or
            metadata.get('size') != [1920, 3664] or metadata.get('modifier') != 0 or
            metadata.get('offset') != 0 or metadata.get('fourcc') not in
            ('XR24', 'AR24', 'XB24', 'AB24', 'XR30', 'AR30', 'XB30', 'AB30')):
        raise ValueError('Expected a matching Neo3 profile and linear scanout')
    pitch = metadata['pitch']
    if type(pitch) is not int or not 7680 <= pitch <= 16384 or pitch % 4:
        raise ValueError('Unsupported raster pitch')
    size = pitch*3664
    if raw_path.stat().st_size != size or metadata.get('native_bytes') != size:
        raise ValueError('Scanout size mismatch')
    raw = raw_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata['native_sha256']:
        raise ValueError('Scanout hash mismatch')
    if (profile['screen']['width'], profile['screen']['height']) != (1920, 3664):
        raise ValueError('Profile screen geometry mismatch')
    views = profile['views']
    if len(views) != 2 or [v['viewport'] for v in views] != [[0, 0, 1920, 1832], [0, 1832, 1920, 1832]]:
        raise ValueError('Unsupported eye viewports')
    for view in views:
        eye_size(view, 916)
        model = view['analytic_distortion']
        if model['type'] != 'pico-radial-2' or view['rotation'] not in (
                [1, 0, 0, 1], [0, 1, -1, 0], [-1, 0, 0, -1], [0, -1, 1, 0]):
            raise ValueError('Unsupported distortion or panel rotation')
        for name, length in [('tangent_scale', 2), ('tangent_offset', 2),
                             ('radial_coefficients', 11), ('chromatic_coefficients', 6)]:
            values = model[name]
            if len(values) != length or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e6 for x in values):
                raise ValueError('Invalid optical coefficients')
        if (len(view['fov']) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in view['fov']) or
                not (-1.57 < view['fov'][0] < -1e-6 and 1e-6 < view['fov'][1] < 1.57 and
                     -1.57 < view['fov'][3] < -1e-6 and 1e-6 < view['fov'][2] < 1.57)):
            raise ValueError('Invalid render frustum')
    words = np.frombuffer(raw, dtype='<u4').reshape(3664, pitch//4)[:, :1920]
    bits = 10 if metadata['fourcc'].endswith('30') else 8
    maximum = (1 << bits)-1
    order = [2, 1, 0] if metadata['fourcc'][1] == 'R' else [0, 1, 2]
    pixels = np.empty((3664, 1920, 3), dtype=np.uint8)
    for channel, component in enumerate(order):
        values = (words >> (bits*component)) & maximum
        pixels[:, :, channel] = (values*255+maximum//2)//maximum
    return pixels, profile, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--optics', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--eye-width', type=int, default=916)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink() or not 64 <= args.eye_width <= 1832:
        parser.error('Use a new output directory and an eye width from 64 to 1832')
    pixels, profile, metadata = load_capture(args.capture, args.optics)
    sizes = [eye_size(view, args.eye_width) for view in profile['views']]
    if sizes[0] != sizes[1]:
        raise ValueError('Stereo preview requires matching per-eye dimensions')
    width, height = sizes[0]
    eyes, reports = [], []
    for view in profile['views']:
        eye, coverage, residual = render_eye(pixels, view, width, height)
        eyes.append(eye)
        reports.append({'covered_pixels': int(np.count_nonzero(coverage)), 'pixels': int(coverage.size),
                        'maximum_inverse_uv_residual': residual})
    args.output.mkdir(mode=0o700)
    Image.fromarray(np.concatenate(eyes, axis=1)).save(args.output/'undistorted-stereo.png')
    Image.fromarray(pixels).transpose(Image.Transpose.ROTATE_270).save(args.output/'panel-stereo.png')
    report = {'scope': 'Host-side inverse of the configured lens pre-correction; resampled diagnostic, not optical or sharpness acceptance',
              'raw_sha256': metadata['native_sha256'], 'optics_sha256': hashlib.sha256(args.optics.read_bytes()).hexdigest(),
              'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'coherent_single_frame_verified': metadata.get('coherent_single_frame_verified', False),
              'stable_readback_verified': metadata.get('stable_readback_verified', False),
              'device_actions': [], 'eye_size': [args.eye_width, height], 'eyes': reports}
    for path in args.output.glob('*.png'):
        report[path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (args.output/'preview.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PICO_SCANOUT_PREVIEW '+str(args.output))


if __name__ == '__main__':
    main()
