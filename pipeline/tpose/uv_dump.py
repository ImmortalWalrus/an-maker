"""Dump a generated mesh's triangles with their UVs and positions (Blender world space, as imported) for texture work
done outside Blender (decal_bake.py). The mesh is only read.

Run: blender -b --factory-startup -P pipeline/tpose/uv_dump.py -- <mesh.glb> <out.npz>
"""
import bpy, sys
import numpy as np

glb, out = sys.argv[sys.argv.index('--') + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
o = next(x for x in bpy.data.objects if x.type == 'MESH')
me = o.data
me.calc_loop_triangles()
mw = o.matrix_world
co = np.array([mw @ v.co for v in me.vertices], dtype=np.float32)
uv = np.array([d.uv for d in me.uv_layers.active.data], dtype=np.float32)
lt = np.array([t.loops[:] for t in me.loop_triangles], dtype=np.int64)
vt = np.array([t.vertices[:] for t in me.loop_triangles], dtype=np.int64)
np.savez(out, tri_p=co[vt], tri_uv=uv[lt])
print(f'[uv] {len(vt)} triangles -> {out}', flush=True)
