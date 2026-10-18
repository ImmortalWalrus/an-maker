"""Helper for step 5 (run inside Blender): for every 04_meshes/<key>.glb, import it exactly as generated and dump
world-space vertices, triangles and per-vertex base colour (sampled from its texture) to 05_place/<key>_mesh.npz.
No mesh processing of any kind.
Run: blender -b --factory-startup -P pipeline/tpose/s5_dump_meshes.py -- <outfit_dir>
"""
import bpy, sys
import numpy as np
from pathlib import Path

d = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
(d / '05_place').mkdir(exist_ok=True)


def base_color_image(obj):
    for m in obj.data.materials:
        if m and m.use_nodes:
            bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf and bsdf.inputs['Base Color'].is_linked:
                node = bsdf.inputs['Base Color'].links[0].from_node
                if node.type == 'TEX_IMAGE' and node.image:
                    return node.image
    return None


# The mannequin itself (rest/T-pose) as an occluder: in the images the body hides what is behind it.
body_npz = d / '05_place' / '_body_mesh.npz'
if not body_npz.exists():
    import json
    base = json.loads((d / '01_mannequin' / 'camera.json').read_text())['base']
    root = Path(__file__).resolve().parents[2]
    bpy.ops.wm.open_mainfile(filepath=str(root / 'Bases' / f'{base}.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()
    verts, tris, off = [], [], 0
    for o in [o for o in bpy.data.objects if o.type == 'MESH']:
        ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        me.calc_loop_triangles()
        verts.append(np.array([(o.matrix_world @ v.co)[:] for v in me.vertices]))
        tris.append(np.array([t.vertices[:] for t in me.loop_triangles]) + off)
        off += len(me.vertices)
        ev.to_mesh_clear()
    np.savez(body_npz, verts=np.concatenate(verts), tris=np.concatenate(tris))
    print('DUMPED body occluder', off, flush=True)

for glb in sorted((d / '04_meshes').glob('*.glb')):
    key = glb.stem
    if (d / '05_place' / f'{key}_mesh.npz').exists():
        continue
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'{key}: expected one mesh, got {len(meshes)}')
    obj = meshes[0]
    me = obj.data
    me.calc_loop_triangles()
    co = np.array([(obj.matrix_world @ v.co)[:] for v in me.vertices])
    tri = np.array([t.vertices[:] for t in me.loop_triangles])
    col = np.full((len(co), 3), 0.5)
    img = base_color_image(obj)
    if img is not None and me.uv_layers.active:
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)
        uv = np.zeros((len(co), 2))
        for loop in me.loops:
            uv[loop.vertex_index] = me.uv_layers.active.data[loop.index].uv
        col = px[np.clip((uv[:, 1] % 1) * (h - 1), 0, h - 1).astype(int), np.clip((uv[:, 0] % 1) * (w - 1), 0, w - 1).astype(int), :3]
    np.savez(d / '05_place' / f'{key}_mesh.npz', verts=co, tris=tri, colors=col)
    print('DUMPED', key, 'verts', len(co), 'tris', len(tri), flush=True)
