"""Cross-sections of every limb opening: garment outline vs skin outline, sliced perpendicular to the limb at several
heights around the opening. Ground truth for the opening numbers in inspect_look.py - a picture you can read in one
glance (hand resting on the rim, cuff off-centre, skin outside a cuff).

Analysis only: the meshes are sliced as copies in memory (bmesh), nothing in the scene changes.
Run: blender -b --factory-startup -P pipeline/tpose/sections.py -- <look_or_outfit_dir> <base>   (slices -> sections.json)
     python pipeline/tpose/sections.py <look_or_outfit_dir>                                        (draws the PNGs)
Writes <dir>/08_inspect/section_<piece>_<bone>.png
"""
import sys, json, math
from pathlib import Path
import numpy as np
try:
    import bpy, bmesh
    from mathutils import Vector, Matrix
    IN_BLENDER = True
except ImportError:
    IN_BLENDER = False

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
if IN_BLENDER:
    import fit_outfit as F  # noqa: E402
    import metrics as M  # noqa: E402

PX = 4000  # pixels per metre (0.25 mm / px)
TILE = 360


def section(obj, origin, normal):
    """Line segments where obj's evaluated mesh crosses the plane (world space)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(dg).to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    obj.evaluated_get(dg).to_mesh_clear()
    bm.transform(obj.matrix_world)
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    res = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=origin, plane_no=normal)
    cut = [e for e in res['geom_cut'] if isinstance(e, bmesh.types.BMEdge)]
    segs = [[list(e.verts[0].co), list(e.verts[1].co)] for e in cut]
    bm.free()
    return segs


def draw_tile(title, centre, axis, garment_segs, skin_segs, hand_segs):
    from PIL import Image, ImageDraw
    centre = np.array(centre)
    garment_segs, skin_segs = np.array(garment_segs).reshape(-1, 2, 3), np.array(skin_segs).reshape(-1, 2, 3)
    ax = np.array(axis) / np.linalg.norm(axis)
    up = np.array([0, 0, 1.0]) - ax * ax[2]
    if np.linalg.norm(up) < 1e-3:
        up = np.array([0, 1.0, 0]) - ax * ax[1]
    up /= np.linalg.norm(up)
    right = np.cross(up, ax)
    im = Image.new('RGB', (TILE, TILE + 22), 'white')
    dr = ImageDraw.Draw(im)

    def P(p):
        r = p - centre
        return (TILE / 2 + (r @ right) * PX / 2, TILE / 2 - (r @ up) * PX / 2)
    for segs, col, w in ((hand_segs, (190, 150, 120), 1), (skin_segs, (120, 60, 30), 2), (garment_segs, (20, 90, 220), 2)):
        for a, b in segs:
            dr.line([P(a), P(b)], fill=col, width=w)
    dr.line([TILE / 2 - 5, TILE / 2, TILE / 2 + 5, TILE / 2], fill='red')
    dr.line([TILE / 2, TILE / 2 - 5, TILE / 2, TILE / 2 + 5], fill='red')
    dr.text((4, TILE + 4), title, fill='black')
    dr.text((4, 4), 'up', fill='gray')
    dr.text((4, TILE - 14), '5 cm', fill='gray')
    dr.line([40, TILE - 8, 40 + 0.05 * PX / 2, TILE - 8], fill='gray', width=2)
    return im


def main():
    d = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    base = sys.argv[sys.argv.index('--') + 2]
    out = d / '08_inspect'
    out.mkdir(exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(d / '06_fitted' / f'{d.name}__{base}.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    F.apply_look_pose(arm, d)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    for o in meshes:
        for m in o.modifiers:
            if m.type == 'MASK':
                m.show_viewport = False  # whole meshes: the true shapes
    bpy.context.view_layer.update()
    pieces = [o for o in meshes if o.name.startswith(d.name + '__')]
    body = max((o for o in meshes if o not in pieces), key=lambda o: len(o.data.vertices))
    names, W = F.body_weights(body)
    bco, _ = F.world_verts(body, evaluated=True)
    bb = M.chain_bone_of(names, W)
    report = {}
    for o in pieces:
        slot = o.name.split('__')[1]
        key = o.name.split('__')[-1]
        bvh = F.bvh_of(*F.world_verts(o, evaluated=True))
        for limb in M.SLOT_LIMBS.get(slot, []):
            ops = M.limb_openings(bvh, bco, bb, lambda b: M.joint(arm, b), limb)
            for bone, rr in ops.items():
                if 'opening' not in rr:
                    continue
                child = dict(M.LIMB_CHAINS[limb])[bone]
                a, b = np.array(M.joint(arm, bone)), np.array(M.joint(arm, child))
                L = np.linalg.norm(b - a)
                axis = (b - a) / L
                t_lo, t_hi = rr['opening']['rim_t_range']
                tiles = []
                ts_ = []
                for t in (t_lo - 0.12, t_lo - 0.05, t_lo, (t_lo + t_hi) / 2, t_hi, t_hi + 0.04):
                    c = M.skin_centre(M.limb_skin(bco, bb, bone, child), a, b, t)
                    if c is None:
                        c = a + t * (b - a)
                    g = section(o, Vector(c), Vector(axis))
                    s = section(body, Vector(c), Vector(axis))
                    ts_.append({'title': f'{key[:18]} {bone} t={t:.2f}', 'centre': list(map(float, c)),
                                'axis': list(map(float, axis)), 'garment': g, 'skin': s})
                report[f'{key}:{bone}'] = {'rim_t': [round(t_lo, 2), round(t_hi, 2)],
                                           'offset_cm': round(rr['opening']['offset'] * 100, 2), 'tiles': ts_}
                print(f'[sections] {key} {bone} rim t {t_lo:.2f}-{t_hi:.2f}', flush=True)
    (out / 'sections.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def draw(d):
    from PIL import Image
    out = Path(d).resolve() / '08_inspect'
    rep = json.loads((out / 'sections.json').read_text(encoding='utf-8'))
    for f in out.glob('section_*.png'):
        f.unlink()
    for name, r in rep.items():
        tiles = [draw_tile(t['title'], t['centre'], t['axis'], t['garment'], t['skin'], []) for t in r['tiles']]
        sheet = Image.new('RGB', (TILE * 3, (TILE + 22) * 2), 'white')
        for i, im in enumerate(tiles):
            sheet.paste(im, ((i % 3) * TILE, (i // 3) * (TILE + 22)))
        sheet.save(out / f"section_{name.replace(':', '_')}.png")
        print('[sections] drew', name, flush=True)


if __name__ == '__main__':
    if IN_BLENDER:
        main()
    else:
        draw(sys.argv[1])
