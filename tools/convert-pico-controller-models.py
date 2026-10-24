#!/usr/bin/env python3
"""Convert pinned WebXR Neo3 GLBs into static, metre-scale SteamVR render models."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import struct


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def transform(node):
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])
    if 'matrix' in node or node.get('scale', [1, 1, 1]) != [1, 1, 1] or abs(x*x+y*y+z*z+w*w-1) > 1e-5:
        raise ValueError('Unsupported node transform')
    t = node.get('translation', [0, 0, 0])
    return [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), t[0]],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), t[1]],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y), t[2]], [0, 0, 0, 1]]


def convert(source, destination, name):
    from PIL import Image

    raw = source.read_bytes()
    if struct.unpack_from('<III', raw) != (0x46546c67, 2, len(raw)):
        raise ValueError('Invalid GLB header')
    length, kind = struct.unpack_from('<II', raw, 12)
    if kind != 0x4e4f534a:
        raise ValueError('Missing GLB JSON')
    data = json.loads(raw[20:20+length])
    offset = 20 + length
    size, kind = struct.unpack_from('<II', raw, offset)
    if kind != 0x004e4942 or offset + 8 + size != len(raw):
        raise ValueError('Invalid GLB buffer')
    buffer = raw[offset+8:]
    if data.get('extensionsRequired') or len(data['buffers']) != 1 or data['buffers'][0].get('uri'):
        raise ValueError('Unsupported external or compressed geometry')

    def accessor(index, expected):
        a = data['accessors'][index]
        formats = {5123: 'H', 5125: 'I', 5126: 'f'}
        lengths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}
        if a['type'] != expected or a.get('sparse') or a.get('normalized'):
            raise ValueError('Unsupported accessor')
        fmt = '<' + formats[a['componentType']] * lengths[expected]
        view = data['bufferViews'][a['bufferView']]
        count, step = a['count'], view.get('byteStride', struct.calcsize(fmt))
        start = view.get('byteOffset', 0) + a.get('byteOffset', 0)
        end = start + max(0, count-1) * step + struct.calcsize(fmt)
        if view['buffer'] or step < struct.calcsize(fmt) or end > view.get('byteOffset', 0) + view['byteLength'] or end > len(buffer):
            raise ValueError('Accessor exceeds buffer')
        return [struct.unpack_from(fmt, buffer, start + i * step) for i in range(count)]

    lines = ['# Converted from MIT-licensed WebXR Input Profiles; see ../LICENSE and provenance.json.',
             'mtllib ' + name + '.mtl', 'o ' + name, 'usemtl controller']
    vertices, faces, visited = [], 0, set()

    def visit(index, parent):
        nonlocal faces
        if index in visited:
            raise ValueError('Repeated or cyclic scene node')
        visited.add(index)
        node = data['nodes'][index]
        matrix = multiply(parent, transform(node))
        if 'mesh' in node:
            for primitive in data['meshes'][node['mesh']]['primitives']:
                if primitive.get('mode', 4) != 4:
                    raise ValueError('Expected triangles')
                attrs = primitive['attributes']
                positions = accessor(attrs['POSITION'], 'VEC3')
                normals = accessor(attrs['NORMAL'], 'VEC3')
                uv = accessor(attrs['TEXCOORD_0'], 'VEC2')
                indices = [x[0] for x in accessor(primitive['indices'], 'SCALAR')]
                if len(positions) != len(normals) or len(uv) != len(positions) or len(indices) % 3:
                    raise ValueError('Inconsistent geometry')
                base = len(vertices) + 1
                for p, n, tex in zip(positions, normals, uv):
                    pos = [sum(matrix[i][k] * (*p, 1)[k] for k in range(4)) for i in range(3)]
                    normal = [sum(matrix[i][k] * n[k] for k in range(3)) for i in range(3)]
                    norm = math.sqrt(sum(x*x for x in normal))
                    if norm < .99 or not all(math.isfinite(x) for x in (*pos, *normal, *tex)):
                        raise ValueError('Invalid vertex')
                    vertices.append(pos)
                    lines.extend(['v ' + ' '.join(format(x, '.9g') for x in pos),
                                  'vt %.9g %.9g' % (tex[0], 1-tex[1]),
                                  'vn ' + ' '.join(format(x/norm, '.9g') for x in normal)])
                for i in range(0, len(indices), 3):
                    triangle = indices[i:i+3]
                    if min(triangle) < 0 or max(triangle) >= len(positions):
                        raise ValueError('Invalid triangle index')
                    lines.append('f ' + ' '.join(f'{base+x}/{base+x}/{base+x}' for x in triangle))
                    faces += 1
        for child in node.get('children', []):
            visit(child, matrix)

    identity = [[int(i == j) for j in range(4)] for i in range(4)]
    for node in data['scenes'][data.get('scene', 0)]['nodes']:
        visit(node, identity)
    bounds = [[min(v[i] for v in vertices), max(v[i] for v in vertices)] for i in range(3)]
    if len(vertices) >= 65000 or not .05 < max(b-a for a, b in bounds) < .35:
        raise ValueError('Model exceeds SteamVR geometry or metre-scale bounds')
    if len(data['images']) != 1 or len(data['materials']) != 1:
        raise ValueError('Expected one controller material and texture')
    view = data['bufferViews'][data['images'][0]['bufferView']]
    start = view.get('byteOffset', 0)
    texture = Image.open(io.BytesIO(buffer[start:start+view['byteLength']])).convert('RGB')
    destination.mkdir()
    (destination / (name + '.obj')).write_text('\n'.join(lines) + '\n')
    texture.save(destination / 'texture.png')
    (destination / (name + '.mtl')).write_text('newmtl controller\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nd 1\nmap_Kd texture.png\n')
    (destination / (name + '.json')).write_text(json.dumps({'components': {
        'body': {'filename': name + '.obj'}, 'tip': {}, 'grip': {}, 'handgrip': {}}}, indent=2) + '\n')
    return {'vertices': len(vertices), 'triangle_faces': faces, 'bounds_metres': bounds,
            'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    profile = json.loads((root / 'profiles/pico-controller-models.json').read_text())
    for hand in ('left', 'right'):
        source = args.source / (hand + '.glb')
        if hashlib.sha256(source.read_bytes()).hexdigest() != profile['sha256'][source.name]:
            raise ValueError('Unrecognized model: ' + str(source))
    args.output.mkdir(parents=True, exist_ok=True)
    record = {'upstream': profile, 'coordinates': 'glTF/OpenVR right-handed, +Y up, metres; original grip origin',
              'modifications': 'Flattened default node transforms; static triangulated OBJ; UV V flipped for OBJ; JPEG decoded to PNG; identity pose components are not calibrated aim offsets',
              'models': {}}
    for hand in ('left', 'right'):
        name = 'neo3_' + hand
        record['models'][hand] = convert(args.source / (hand + '.glb'), args.output / name, name)
    (args.output / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n')
    print('PICO_CONTROLLER_MODELS_CONVERTED ' + json.dumps(record['models']))


if __name__ == '__main__':
    main()
