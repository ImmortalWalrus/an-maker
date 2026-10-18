"""Reject trousers/shorts whose legs are fused below the knees.

A generated bottom whose two legs touch below the knee carries vertices weighted to both legs and faces joining
the legs. In the fit pose this is invisible; as soon as a clip spreads the legs it stretches into a web, and the
customizer cannot hide it (garments are never partially masked). Run on an exported piece GLB:

    python -I pipeline/anim/check_leg_bridge.py web/customizer/assets/piece_<key>.glb

Exit code 1 (and a report) when any face below the knees joins a left-leg vertex to a right-leg vertex, or when
more than a handful of below-knee vertices are weighted to both legs. Exit code 0 otherwise.
"""
import json
import struct
import sys

import numpy as np

MAX_MIXED = 8          # a few stray seam vertices are fine; the customizer reassigns them


def load(path):
    raw = open(path, 'rb').read()
    jl = struct.unpack('<I', raw[12:16])[0]
    g = json.loads(raw[20:20 + jl])
    blob = raw[20 + jl + 8:]

    def acc(i):
        a = g['accessors'][i]
        bv = g['bufferViews'][a['bufferView']]
        ct = {5121: 'u1', 5123: 'u2', 5125: 'u4', 5126: 'f4'}[a['componentType']]
        n = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
        off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
        out = np.frombuffer(blob, dtype='<' + ct, count=a['count'] * n, offset=off).reshape(a['count'], n)
        if a.get('normalized') and ct != 'f4':
            out = out / float(np.iinfo(out.dtype).max)
        return out
    return g, acc


def main(path):
    g, acc = load(path)
    skin = g['skins'][0]
    names = [g['nodes'][j]['name'] for j in skin['joints']]
    inv = acc(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)   # column-major -> row-major
    knee_y = min(np.linalg.inv(inv[names.index(n)])[1, 3] for n in ('LeftLeg', 'RightLeg'))
    side = np.array([1 if n.startswith('Left') and any(k in n for k in ('Leg', 'Foot', 'Toe')) else
                     -1 if n.startswith('Right') and any(k in n for k in ('Leg', 'Foot', 'Toe')) else 0 for n in names])
    bad = False
    for mesh in g['meshes']:
        for prim in mesh['primitives']:
            a = prim['attributes']
            if 'JOINTS_0' not in a:
                continue
            P, J, W = acc(a['POSITION']), acc(a['JOINTS_0']).astype(int), acc(a['WEIGHTS_0']).astype(float)
            idx = acc(prim['indices']).reshape(-1, 3)
            s = side[J]
            wl, wr = (W * (s == 1)).sum(1), (W * (s == -1)).sum(1)
            low = P[:, 1] < knee_y        # piece meshes are exported in the avatar's metre space
            mixed = low & (wl > 0.02) & (wr > 0.02)
            dom = np.where(wl > wr + 1e-6, 1, np.where(wr > wl + 1e-6, -1, 0))
            td = dom[idx]
            bridge = low[idx].all(1) & (td.max(1) == 1) & (td.min(1) == -1)
            print(f"{mesh.get('name', '?')}: knee at y={knee_y:.3f} m, below-knee vertices weighted to both legs: "
                  f"{int(mixed.sum())}, faces joining the legs below the knees: {int(bridge.sum())}")
            if bridge.any():
                c = P[idx[bridge]].mean(1)
                print(f"  joining faces span y {c[:, 1].min():.3f}..{c[:, 1].max():.3f} m, x {c[:, 0].min():.3f}..{c[:, 0].max():.3f} m")
            if bridge.any() or mixed.sum() > MAX_MIXED:
                bad = True
    print('REJECT: legs are fused below the knees; regenerate with a clear gap between the legs.' if bad else 'OK')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
