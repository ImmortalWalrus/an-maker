"""Export a wardrobe for the three.js customizer (run inside Blender). The browser applies the SAME rules as equip.py:

  body       Bases/<base> body + face meshes, T-pose rest, every Genies blend shape (face presets, expressions,
             eyes, teeth/tongue, brows, lashes) as glTF morph targets, plus one vertex attribute per piece
             (_hide_<i>) = the skin that piece hides (equip's safe_hide on that piece alone, read from the
             Outfits/_looks/web-<key> look). The browser hides the union for what is worn.
  pieces     each piece EXACTLY as generated: its skinned mesh with the rig's rest set to the piece's own fit pose,
             so with the avatar posed to it the piece shows undeformed. The browser poses each limb to the
             outermost worn piece fitted along it (equip.look_pose).
  manifest   slots, layers, which limbs each piece is fitted along, which pieces are hidden ENTIRELY under which
             (equip's occlusion rule on the shared cage), and the blend-shape groups for the face UI.

Run: blender -b --factory-startup -P pipeline/web/export_web.py -- --base Xander --out web/customizer/assets
         --pieces hoodie-boy:navy_teal_tousled_hair ...
"""
import bpy, sys, json, argparse, re
from pathlib import Path
import numpy as np
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402
import equip as E  # noqa: E402
sys.path.insert(0, str(ROOT / 'pipeline' / 'web'))
import slim_glb  # noqa: E402

TEX = 1024  # piece textures are downscaled to this for the web


LABELS = {'sidequest_tee': 'SideQuest Tee', 'an_secret_tee': 'AN Secret Tee', 'lululemur_align_leggings': 'lululemur Leggings',
          'like_pro_shorts': 'LIKE PRO Shorts', 'monchill_puffer_jacket': 'MONCHILL Puffer', 'champignon_sweatpants': 'CHAMPIGNON Sweats'}  # brand spellings .title() would break


def labels(key):
    try:
        import catalog                                    # a piece's own catalog entry names it
        named = catalog.labels().get(key)
    except Exception:
        named = None
    return LABELS.get(key) or named or key.replace('_with_', ' + ').replace('_', ' ').title()


def loft_of(spec):
    """The padding a piece declares in its outfit.json ("loft_mm"), or 0."""
    outfit, key = spec.split(':')
    f = ROOT / 'Outfits' / outfit / 'outfit.json'
    if not f.exists():
        return 0
    return next((float(p.get('loft_mm') or 0) for p in json.loads(f.read_text(encoding='utf-8')).get('pieces', [])
                 if p.get('key') == key), 0)


def body_hides(base, keys):
    out = {}
    for k in keys:
        blend = ROOT / 'Outfits' / '_looks' / f'web-{k}' / '06_fitted' / f'web-{k}__{base}.blend'
        bpy.ops.wm.open_mainfile(filepath=str(blend))
        body = max((o for o in bpy.data.objects if o.type == 'MESH' and not o.name.startswith('web-')),
                   key=lambda o: len(o.data.vertices))
        g = body.vertex_groups.get('hide_covered_by_look')
        out[k] = sorted(v.index for v in body.data.vertices if g and any(e.group == g.index for e in v.groups))
        print(f'[web] {k}: hides {len(out[k])} skin vertices', flush=True)
    return out


def shrink_images(objs):
    for o in objs:
        # body-made tops (shell_garment.py, marked by _hem_band) carry a designed print on a true-scale pattern
        # layout: they keep up to 2048 px, and every texture keeps its own aspect
        cap = 2048 if any(at.name.lower() in ('_hem_band', '_shell') for at in o.data.attributes) else TEX
        for m in o.data.materials:
            if not (m and m.use_nodes):
                continue
            for n in m.node_tree.nodes:
                # a generated piece's reworked colour map (decal_bake.py: a logo redrawn sharply) keeps 2048, or the
                # new logo is blurred back down on the piece's coarse UV layout
                lim = 2048 if n.type == 'TEX_IMAGE' and n.image and n.image.name.startswith('Color_reworked') else cap
                if n.type == 'TEX_IMAGE' and n.image and max(n.image.size) > lim:
                    w, h = n.image.size
                    k = lim / max(w, h)
                    n.image.scale(max(1, round(w * k)), max(1, round(h * k)))


def export(path, objs, morph=False, attrs=False, fmt='JPEG'):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True, export_skins=True,
                              export_morph=morph, export_attributes=attrs, export_animations=False,
                              export_image_format=fmt, export_jpeg_quality=85)
    # same render, smaller download: morph targets stored sparse (the body's dense blend-shape normals were 8.8 of its
    # 10.7 MB, ~90% float noise) and byte-identical images stored once (slim_glb.py)
    slim_glb.slim_file(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--pieces', nargs='+', required=True)
    a = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    keys = [s.split(':')[1] for s in a.pieces]
    hides = body_hides(a.base, keys)

    arm, body, base_meshes = F.load_base(a.base)
    for o in [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('Icosphere')]:
        bpy.data.objects.remove(o, do_unlink=True)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    base_meshes = [o for o in bpy.data.objects if o.type == 'MESH']

    # ---- pieces (in rest space as fitted), coverage on the shared T-pose cage for the occlusion rule
    co, n, edges = E.cage_template(a.base, body)
    limit = E.free_space(co, n, body)
    pieces, cov, covE = [], {}, {}
    for i, spec in enumerate(a.pieces):
        key, info, obj = E.load_piece(spec)
        slot = info['slot']
        A, _ = E.heights(obj, co, n, limit=limit)
        cov[key] = ~np.isnan(A)
        covE[key] = E.erode(cov[key], edges, E.ERODE)
        fp = (info.get('fit', {}) or {}).get('fit_pose') or {}
        # show the piece exactly as generated: skin it into its fit pose, then make that pose the rig's rest
        names_k, W_k = E.piece_weights(obj, arm)
        rest = np.array([v.co[:] for v in obj.data.vertices])
        posed = E.lbs(rest, W_k, E.pose_mats(arm, names_k, fp))
        for v, q in zip(obj.data.vertices, posed):
            v.co = q
        obj.data.update()
        rig = arm.copy()
        rig.data = arm.data.copy()
        bpy.context.scene.collection.objects.link(rig)
        for pb in rig.pose.bones:
            pb.matrix_basis = Matrix(fp[pb.name]) if pb.name in fp else Matrix.Identity(4)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.armature_apply(selected=False)
        bpy.ops.object.mode_set(mode='OBJECT')
        F.attach(obj, rig)
        shrink_images([obj])
        fname = f'piece_{key}.glb'
        # body-made tops carry designed prints with thin stitch lines and hard colour edges: lossless PNG (JPEG breaks
        # thin lines into 8x8 blocks and halves colour resolution, which showed as dashed stitches and colour fringes)
        shell = any(at.name.lower() in ('_hem_band', '_shell') for at in obj.data.attributes)  # body-made (tops, leggings)
        export(out / fname, [rig, obj], attrs=True, fmt='AUTO' if shell else 'JPEG')  # custom attributes, e.g. _HEM_BAND
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.objects.remove(rig, do_unlink=True)
        E.pose_mats(arm, [], {})
        pieces.append({'key': key, 'label': labels(key), 'slot': slot, 'layer': E.SLOTS[slot]['layer'],
                       'file': fname, 'hide': i, 'limbBones': sorted(fp.keys()),
                       'bundleOf': info.get('fit', {}).get('bundle_of')})
        loft = loft_of(spec)
        if loft:  # padded pieces (a down puffer): the customizer keeps the arms straighter inside their sleeves
            pieces[-1]['loftMm'] = loft
        print(f'[web] {key}: exported ({len(fp)} fitted limb bones)', flush=True)

    # occlusion rule: a garment mostly under a higher one is hidden entirely while both are worn
    garments = [p for p in pieces if p['slot'] not in E.NEVER_HIDE]
    for p in garments:
        p['hiddenUnder'] = [q['key'] for q in garments if q['layer'] > p['layer'] and cov[p['key']].any()
                            and covE[q['key']][cov[p['key']]].mean() >= E.OCCLUDED]

    # ---- body: hide attributes + all blend shapes
    for i, k in enumerate(keys):
        at = body.data.attributes.new(f'_hide_{i}', 'FLOAT', 'POINT')
        vals = np.zeros(len(body.data.vertices), np.float32)
        vals[hides[k]] = 1.0
        at.data.foreach_set('value', vals)
    export(out / 'body.glb', [arm] + base_meshes, morph=True, attrs=True)

    morphs = {o.name: [kb.name for kb in o.data.shape_keys.key_blocks[1:]] for o in base_meshes if o.data.shape_keys}
    manifest = {'base': a.base, 'body': 'body.glb', 'pieces': pieces,
                'slots': [{'slot': s, 'label': s.title(), 'layer': E.SLOTS[s]['layer']}
                          for s in sorted({p['slot'] for p in pieces}, key=lambda s: (E.SLOTS[s]['layer'], s != 'hair', s))],
                'morphs': morphs}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print('[web] DONE', out, flush=True)


if __name__ == '__main__':
    main()
