#!/usr/bin/env python3
"""Measure how far SteamVR's bilinear distortion mesh strays from the driver's lens model."""
import argparse
import json
import math
from pathlib import Path


def lens_model(view):
    """Mirror PicoSteamvrDisplay::ComputeDistortion for one view: (u, v) -> [(u, v)] * RGB."""
    model, rotation = view['analytic_distortion'], view['rotation']
    radial = list(reversed(model['radial_coefficients']))
    chroma = model['chromatic_coefficients']
    left, right, up, down = (math.tan(a) for a in view['fov'])

    def evaluate(u, v):
        px, py = 2 * u - 1, 1 - 2 * v
        logical_u = (rotation[0] * px + rotation[1] * py + 1) * .5
        logical_v = (1 - rotation[2] * px - rotation[3] * py) * .5
        x = model['tangent_scale'][0] * logical_u + model['tangent_offset'][0]
        y = model['tangent_scale'][1] * logical_v + model['tangent_offset'][1]
        rsq = x * x + y * y
        radius, scale = math.sqrt(rsq), 0.0
        for coefficient in radial:
            scale = scale * rsq + coefficient
        factors = (1 + chroma[0] + rsq * chroma[1] + radius * chroma[4], 1.0,
                   1 + chroma[2] + rsq * chroma[3] + radius * chroma[5])
        return [((x * scale * f - left) / (right - left), (up - y * scale * f) / (up - down)) for f in factors]
    return evaluate


def mesh_errors(profile, resolution, render_size):
    """Per-axis errors in render pixels at nine points per cell, where the exact sample is visible."""
    errors, points = [], (1 / 6, .5, 5 / 6)
    for view in profile['views']:
        evaluate, step = lens_model(view), resolution - 1
        grid = [[evaluate(i / step, j / step) for j in range(resolution)] for i in range(resolution)]
        for i in range(step):
            for j in range(step):
                corners = grid[i][j], grid[i + 1][j], grid[i][j + 1], grid[i + 1][j + 1]
                for a in points:
                    for b in points:
                        weights = (1 - a) * (1 - b), a * (1 - b), (1 - a) * b, a * b
                        exact = evaluate((i + a) / step, (j + b) / step)
                        for channel, (eu, ev) in enumerate(exact):
                            if not (0 <= eu <= 1 and 0 <= ev <= 1):
                                continue
                            for axis, size in enumerate(render_size):
                                mesh = sum(w * c[channel][axis] for w, c in zip(weights, corners))
                                errors.append(abs(mesh - exact[channel][axis]) * size)
    return sorted(errors)


def summary(errors):
    count = len(errors)
    if not count:
        raise ValueError('No visible samples')
    return {'samples': count, 'max_px': errors[-1], 'p99_px': errors[int(.99 * count)],
            'median_px': errors[count // 2], 'over_half_pixel': sum(e > .5 for e in errors) / count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path, help='analytic Neo3 optics profile (schema 2)')
    parser.add_argument('--render-size', type=int, nargs=2, default=(1832, 1920), metavar=('WIDTH', 'HEIGHT'))
    parser.add_argument('--resolution', type=int, nargs='+', default=[49, 97, 129, 193, 255])
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    for resolution in args.resolution:
        if not 2 <= resolution <= 255:
            parser.error('SteamVR meshes are 2 to 255 vertices per side')
        print(json.dumps({'resolution': resolution, **summary(mesh_errors(profile, resolution, args.render_size))}))


if __name__ == '__main__':
    main()
