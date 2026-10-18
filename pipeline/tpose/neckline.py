"""Neckline check: how far a top's collar sits off the neck, front and back (crew / round necks).

The collar = the piece's vertices in its top 2 cm (in the look pose, i.e. as shown); each one's distance to the
nearest skin surface. A crew neck sits a few mm off the neck all round: median <= NECK_MEDIAN_MM and 90th percentile
<= NECK_P90_MM, front and back separately.

Run (report only): blender -b --factory-startup -P pipeline/tpose/neckline.py -- <look_dir> [<look_dir> ...]
"""
import sys
from pathlib import Path
import numpy as np

NECK_MEDIAN_MM, NECK_P90_MM = 8.0, 15.0
SLOTS = ('top', 'outerwear', 'fullbody')


def collar_gaps(gco, body_bvh, band=0.02):
    """{'front': stats, 'back': stats} of collar-to-skin distances (mm). gco: the piece's vertices (world, as shown)."""
    from mathutils import Vector
    top = gco[:, 2].max()
    col = gco[gco[:, 2] > top - band]
    if len(col) < 20:
        return None
    d = np.array([(body_bvh.find_nearest(Vector(p))[3] or 0.0) for p in col]) * 1000
    cy = np.median(col[:, 1])
    out = {}
    for side, m in (('front', col[:, 1] < cy), ('back', col[:, 1] >= cy)):
        if m.sum() >= 10:
            out[side] = {'n': int(m.sum()), 'median_mm': round(float(np.median(d[m])), 1),
                         'p90_mm': round(float(np.percentile(d[m], 90)), 1), 'max_mm': round(float(d[m].max()), 1)}
    return out


def check(gaps):
    fails = []
    for side, st in (gaps or {}).items():
        if st['median_mm'] > NECK_MEDIAN_MM or st['p90_mm'] > NECK_P90_MM:
            fails.append(f"collar floats off the neck at the {side} (median {st['median_mm']:.0f} mm, 90% within "
                         f"{st['p90_mm']:.0f} mm; a crew neck sits <= {NECK_MEDIAN_MM:.0f} / {NECK_P90_MM:.0f} mm off it)")
    return fails


if __name__ == '__main__' and '--' in sys.argv:
    import bpy, json
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / 'pipeline'))
    sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
    import fit_outfit as F  # noqa: E402
    for look in sys.argv[sys.argv.index('--') + 1:]:
        look = Path(look).resolve()
        bpy.ops.wm.open_mainfile(filepath=str(look / '06_fitted' / f'{look.name}__Xander.blend'))
        F.apply_look_pose(next(o for o in bpy.data.objects if o.type == 'ARMATURE'), look)
        for o in bpy.data.objects:
            for m in getattr(o, 'modifiers', []):
                if m.type == 'MASK':
                    m.show_viewport = False
        bpy.context.view_layer.update()
        bb = F.bvh_of(*F.world_verts(bpy.data.objects['Submesh_0'], evaluated=True))
        for o in bpy.data.objects:
            if o.type == 'MESH' and '__' in o.name and o.name.split('__')[1] in SLOTS:
                g = collar_gaps(F.world_verts(o, evaluated=True)[0], bb)
                print('NECK', look.name, o.name.split('__')[-1], json.dumps(g), '|', '; '.join(check(g)) or 'OK', flush=True)
