#!/usr/bin/env python3
"""Inspect bounded saved controller images; report geometry hypotheses, never poses."""
import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    'controller_acquisition', Path(__file__).with_name('analyze-pico-controller-acquisition.py'))
acquisition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquisition)
MAX_FEATURES = 7
MAX_BRIGHT_PIXELS = 4096
MAX_REPORTED_HYPOTHESES = 32
TRANSFORMS = ('none', 'flip-x', 'flip-y', 'rotate-180')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path, maximum):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,
            'Expected a bounded regular file: ' + str(path))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def camera(path):
    regular(path, 65536)
    text = path.read_text()

    def field(key):
        values = re.findall(r'^\s*' + re.escape(key) + r':\s*([^\n#]+)', text, re.M)
        require(len(values) == 1, 'Missing or duplicate camera field: ' + key)
        return values[0].strip()

    def vector(key, count):
        values = re.findall(r'^\s*' + re.escape(key) + r':\s*\[([^]]+)\]', text, re.M)
        require(len(values) == 1, 'Missing or duplicate camera vector: ' + key)
        result = np.array([float(x) for x in values[0].split(',')])
        require(result.shape == (count,) and np.all(np.isfinite(result)),
                'Invalid camera vector: ' + key)
        return result

    require(field('sensor_type') == 'camera' and field('camera_model') == 'omni' and
            field('distortion_model') == 'radtan', 'Requires an omni/radtan camera')
    require(np.array_equal(vector('resolution', 2), [640, 480]), 'Unsupported camera resolution')
    require(len(re.findall(r'^T_BS:\s*$', text, re.M)) == 1 and
            field('rows') == field('cols') == '4', 'Requires factory T_BS')
    transform = vector('data', 16).reshape(4, 4)
    rotation = transform[:3, :3]
    require(np.allclose(transform[3], [0, 0, 0, 1], atol=1e-9, rtol=0) and
            np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0) and
            abs(np.linalg.det(rotation) - 1) < 1e-6,
            'T_BS must be a proper rigid camera-to-body transform')
    intrinsics = vector('intrinsics', 5)
    require(0 <= intrinsics[0] <= 10 and np.all(intrinsics[1:3] > 0), 'Invalid omni intrinsics')
    return transform, intrinsics, vector('distortion_coefficients', 4)


def led_bounds(path):
    regular(path, 340)
    raw = path.read_bytes()
    require(len(raw) == 340, 'Requires the complete 85-float Neo3 tracker vector')
    values = np.array(struct.unpack('<85f', raw))
    require(np.all(np.isfinite(values)) and values[25] == 1, 'Invalid calibrated LED section')
    points = values[26:74].reshape(16, 3)
    diameter = float(np.max(np.linalg.norm(points[:, None] - points[None, :], axis=2)))
    radius = float(np.max(np.linalg.norm(points, axis=1)))
    require(0 < diameter < 1 and radius < 1, 'Unsupported metre-scale controller model')
    return diameter, radius


def distort(xy, coefficients):
    x, y = np.asarray(xy).T
    k1, k2, p1, p2 = coefficients
    radius = x*x + y*y
    radial = 1 + k1*radius + k2*radius*radius
    return np.column_stack((x*radial + 2*p1*x*y + p2*(radius + 2*x*x),
                            y*radial + p1*(radius + 2*y*y) + 2*p2*x*y))


def project(calibration, points):
    transform, k, coefficients = calibration
    xi, fx, fy, cx, cy = k
    local = (points - transform[:3, 3]) @ transform[:3, :3]
    denominator = local[:, 2] + xi * np.linalg.norm(local, axis=1)
    require(np.all(denominator > 1e-12), 'Points outside the camera projection domain')
    xy = local[:, :2] / denominator[:, None]
    return distort(xy, coefficients) * [fx, fy] + [cx, cy]


def rays(calibration, pixels):
    transform, k, coefficients = calibration
    xi, fx, fy, cx, cy = k
    target = (pixels - [cx, cy]) / [fx, fy]
    xy = target.copy()
    for _ in range(20):
        error = distort(xy, coefficients) - target
        if np.max(abs(error)) < 1e-13:
            break
        for i in range(len(xy)):
            jacobian = np.column_stack([
                ((distort(xy[i:i+1] + np.eye(2)[j]*1e-7, coefficients) -
                  distort(xy[i:i+1] - np.eye(2)[j]*1e-7, coefficients)) / 2e-7)[0]
                for j in range(2)])
            xy[i] -= np.linalg.solve(jacobian, error[i])
    require(np.max(abs(distort(xy, coefficients) - target)) < 1e-10,
            'Distortion inversion did not converge')
    radius = np.sum(xy*xy, axis=1)
    radicand = 1 + (1-xi*xi)*radius
    require(np.all(radicand >= 0), 'Features outside the omni inverse domain')
    scale = (xi + np.sqrt(radicand)) / (1 + radius)
    result = np.column_stack((xy*scale[:, None], scale-xi)) @ transform[:3, :3].T
    roundtrip = project(calibration, transform[:3, 3] + result)
    require(np.max(abs(roundtrip-pixels)) < 1e-6, 'Projection round trip failed')
    return result


def components(pixels, threshold, masked_rows):
    active = np.flatnonzero(pixels > threshold)
    active = active[active >= masked_rows * 640]
    if len(active) > MAX_BRIGHT_PIXELS:
        return {'status': 'bright_pixel_limit', 'bright_pixels': len(active), 'features': []}
    pending = set(map(int, active))
    features = []
    while pending:
        stack = [pending.pop()]
        group = []
        while stack:
            index = stack.pop()
            group.append(index)
            y, x = divmod(index, 640)
            for dy, dx in itertools.product((-1, 0, 1), repeat=2):
                nx, ny = x+dx, y+dy
                neighbor = ny*640+nx
                if 0 <= nx < 640 and 0 <= ny < 480 and neighbor in pending:
                    pending.remove(neighbor)
                    stack.append(neighbor)
        if 2 <= len(group) <= 30:
            ys, xs = np.divmod(group, 640)
            features.append({'xy': [float(np.mean(xs)), float(np.mean(ys))], 'area': len(group),
                             'peak': int(np.max(pixels[np.array(group)]))})
    features.sort(key=lambda row: (row['xy'][1], row['xy'][0]))
    status = 'feature_limit' if len(features) > MAX_FEATURES else 'observed'
    return {'status': status, 'bright_pixels': len(active), 'feature_count': len(features),
            'features': features[:MAX_FEATURES]}


def pixel_transform(points, transform):
    result = points.copy()
    if transform in ('flip-x', 'rotate-180'):
        result[:, 0] = 639-result[:, 0]
    if transform in ('flip-y', 'rotate-180'):
        result[:, 1] = 479-result[:, 1]
    return result


def hypotheses(calibrations, points, diameter, pixel_limit):
    if min(map(len, points)) < 5:
        return {'status': 'insufficient_features', 'hypotheses': [], 'total_hypotheses': 0}
    require(max(map(len, points)) <= MAX_FEATURES, 'Feature search exceeds its bound')
    directions = [rays(c, p) for c, p in zip(calibrations, points)]
    origins = [c[0][:3, 3] for c in calibrations]
    cloud, errors = {}, {}
    for i, j in itertools.product(range(len(points[0])), range(len(points[1]))):
        first, second = directions[0][i], directions[1][j]
        matrix = np.column_stack((first, -second))
        depths, _, rank, singular = np.linalg.lstsq(matrix, origins[1]-origins[0], rcond=None)
        if rank != 2 or singular[-1] < 1e-6 or min(depths) <= 0:
            continue
        xyz = (origins[0]+first*depths[0] + origins[1]+second*depths[1])/2
        error = max(float(np.linalg.norm(project(c, xyz[None])[0]-p[index]))
                    for c, p, index in zip(calibrations, points, (i, j)))
        if error <= pixel_limit:
            cloud[i, j], errors[i, j] = xyz, error
    count, results = 0, []
    for left in itertools.combinations(range(len(points[0])), 5):
        for right in itertools.permutations(range(len(points[1])), 5):
            keys = list(zip(left, right))
            if any(key not in cloud for key in keys):
                continue
            xyz = np.array([cloud[key] for key in keys])
            span = float(np.max(np.linalg.norm(xyz[:, None]-xyz[None, :], axis=2)))
            if span > diameter:
                continue
            count += 1
            center = xyz.mean(0)
            result = {'feature_indices': [list(left), list(right)], 'points_body_m': xyz.tolist(),
                      'feature_centroid_body_m': center.tolist(), 'diameter_m': span,
                      'centroid_radial_distance_m': float(np.linalg.norm(center)),
                      'maximum_reprojection_pixels': max(errors[key] for key in keys)}
            results.append(result)
            results.sort(key=lambda row: row['maximum_reprojection_pixels'])
            del results[MAX_REPORTED_HYPOTHESES:]
    return {'status': 'hypotheses' if count else 'no_hypothesis', 'hypotheses': results,
            'total_hypotheses': count, 'reported_hypotheses_truncated': count > len(results)}


def analyze(images, camera_paths, tracker, frames, image_cameras, transforms,
            thresholds=(64, 80, 96), pixel_limit=.5, diameter_margin=.01, masked_rows=4):
    require(1 <= len(frames) <= 4 and len(set(frames)) == len(frames) and
            all(1 <= f <= 150 for f in frames), 'Select one to four distinct one-based image sets')
    require(len(camera_paths) == len(image_cameras) == len(transforms) == 2 and
            len(set(image_cameras)) == 2 and all(c in range(4) for c in image_cameras) and
            all(t in TRANSFORMS for t in transforms), 'Select two explicit camera mappings')
    require(1 <= len(thresholds) <= 3 and len(set(thresholds)) == len(thresholds) and
            all(1 <= t <= 254 for t in thresholds), 'Select one to three distinct byte thresholds')
    require(math.isfinite(pixel_limit) and 0 < pixel_limit <= 2 and
            math.isfinite(diameter_margin) and 0 <= diameter_margin <= .05 and
            0 <= masked_rows <= 16, 'Unsupported diagnostic bounds')
    regular(images, 32+150*acquisition.IMAGE_SIZE)
    paths = [images, tracker, *camera_paths]
    for path in paths[1:]:
        regular(path, 65536)
    hashes = {str(path): digest(path) for path in paths}
    calibrations = [camera(path) for path in camera_paths]
    baseline = float(np.linalg.norm(calibrations[0][0][:3, 3]-calibrations[1][0][:3, 3]))
    require(1e-4 < baseline < 2, 'Invalid stereo baseline')
    diameter, radius = led_bounds(tracker)
    records = acquisition.records(images, 'images')
    require(len({r['generation'] for r in records}) == 1, 'Mixed estimator generations')
    require(max(frames) <= len(records), 'Selected image set is absent')
    observations = []
    with images.open('rb') as stream:
        for number in frames:
            event = records[number-1]
            stream.seek(event['offset'])
            raw = stream.read(acquisition.IMAGE_SIZE)
            require(len(raw) == acquisition.IMAGE_SIZE, 'Image carrier changed while reading')
            planes, metadata = [], []
            for index in image_cameras:
                offset = 760+index*(64+acquisition.PIXELS)
                fields = acquisition.FRAME.unpack_from(raw, offset)
                metadata.append({'image_camera': fields[0], 'exposure': fields[5], 'gain': fields[6],
                                 'sof_ns': fields[8], 'center_ns': fields[9], 'frame_number': fields[10]})
                planes.append(np.frombuffer(raw, dtype=np.uint8, count=acquisition.PIXELS, offset=offset+64))
            for threshold in thresholds:
                detections = [components(p, threshold, masked_rows) for p in planes]
                if any(row['status'] != 'observed' for row in detections):
                    geometry = {'status': 'detection_limit', 'hypotheses': [], 'total_hypotheses': 0}
                else:
                    points = [pixel_transform(np.array([f['xy'] for f in row['features']]).reshape(-1, 2), t)
                              for row, t in zip(detections, transforms)]
                    try:
                        geometry = hypotheses(calibrations, points, diameter+diameter_margin, pixel_limit)
                    except (ValueError, np.linalg.LinAlgError) as error:
                        geometry = {'status': 'projection_refused', 'reason': str(error),
                                    'hypotheses': [], 'total_hypotheses': 0}
                observations.append({'image_set': number, 'timestamp_ns': event['timestamp_ns'],
                                     'dispatch_order': event['dispatch_order'], 'cameras': metadata,
                                     'threshold': threshold, 'detections': detections, **geometry})
    require(all(digest(path) == hashes[str(path)] for path in paths), 'Input changed during analysis')
    return {'schema': 1, 'scope': 'Offline feature geometry hypotheses; no SDK execution or pose output',
            'analyzer_sha256': digest(Path(__file__)), 'numpy_version': np.__version__,
            'input_sha256': hashes, 'image_sets_in_carrier': len(records),
            'camera_mapping_assumptions': [
                {'image_camera': i, 'factory_yaml': str(p), 'pixel_transform': t}
                for i, p, t in zip(image_cameras, camera_paths, transforms)],
            'coordinate_frame': 'Factory body B, with supplied T_BS mapping camera S into B; metres',
            'baseline_m': baseline, 'model_diameter_m': diameter, 'model_max_origin_radius_m': radius,
            'settings': {'thresholds': list(thresholds), 'component_area_pixels': [2, 30],
                         'masked_top_rows': masked_rows, 'max_features_per_view': MAX_FEATURES,
                         'max_bright_pixels': MAX_BRIGHT_PIXELS, 'matched_features': 5,
                         'pixel_residual_limit': pixel_limit, 'diameter_margin_m': diameter_margin},
            'observations': observations, 'optical_tracking_verified': False,
            'sdk_gate_comparison_performed': False,
            'unverified': ['physical camera mapping, pixel orientation and calibration accuracy',
                           'whether matched components are controller LEDs',
                           'LED identities and controller origin/orientation',
                           'physical placement and body axes relative to the room',
                           'SDK acceptance, loss and reacquisition'],
            'limits': ['Component thresholds do not emulate or modify SDK detection.',
                       'Feature centroid is not a controller origin; radial range is not body Z.',
                       'Closest-ray residual limits are not calibration or position confidence intervals.',
                       'A near-position capture with measured placement is needed to test mapping/scale.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--camera-yamls', type=Path, nargs=2, required=True)
    parser.add_argument('--tracker-calibration', type=Path, required=True)
    parser.add_argument('--image-cameras', type=int, nargs=2, required=True)
    parser.add_argument('--pixel-transforms', choices=TRANSFORMS, nargs=2, default=('none', 'none'))
    parser.add_argument('--frames', type=int, nargs='+', required=True, help='One-based recorded image sets; maximum four')
    parser.add_argument('--thresholds', type=int, nargs='+', default=(64, 80, 96))
    parser.add_argument('--pixel-limit', type=float, default=.5)
    parser.add_argument('--diameter-margin', type=float, default=.01)
    parser.add_argument('--masked-top-rows', type=int, default=4)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.images, args.camera_yamls, args.tracker_calibration, args.frames,
                     args.image_cameras, args.pixel_transforms, args.thresholds, args.pixel_limit,
                     args.diameter_margin, args.masked_top_rows)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print('Saved offline geometry hypotheses: ' + str(args.output))


if __name__ == '__main__':
    main()
