"""Inspect a folder of part GLBs: stats JSON plus a contact-sheet render of each part (front view).
Run: blender -b --factory-startup -P pipeline/inspect_parts.py -- <parts_dir>
"""
import bpy, sys, json, math
from pathlib import Path
from mathutils import Vector

parts_dir = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
out_dir = parts_dir / '_inspect'
out_dir.mkdir(exist_ok=True)
stats = {}
for glb in sorted(parts_dir.glob('*.glb')):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector([min(c[i] for c in corners) for i in range(3)])
    hi = Vector([max(c[i] for c in corners) for i in range(3)])
    stats[glb.stem] = {
        'objects': len(meshes),
        'verts': sum(len(o.data.vertices) for o in meshes),
        'tris': sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes),
        'size': [round(v, 3) for v in (hi - lo)],
        'center': [round(v, 3) for v in (hi + lo) / 2],
        'materials': sorted({m.name for o in meshes for m in o.data.materials if m}),
    }
    center, size = (hi + lo) / 2, max(hi - lo)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    bpy.context.collection.objects.link(cam)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = size * 1.15
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'TEXTURE'
    scene.display.shading.background_type = 'WORLD'
    scene.world = bpy.data.worlds.new('w')
    scene.world.color = (0.85, 0.85, 0.85)
    scene.render.resolution_x = scene.render.resolution_y = 512
    # Two views: looking along +Y and along -X, so either front convention shows a front.
    for tag, offset, rot in (('y', Vector((0, -size * 3, 0)), (90, 0, 0)), ('x', Vector((size * 3, 0, 0)), (90, 0, 90))):
        cam.location = center + offset
        cam.rotation_euler = tuple(math.radians(a) for a in rot)
        scene.render.filepath = str(out_dir / f'{glb.stem}.{tag}.png')
        bpy.ops.render.render(write_still=True)
(out_dir / 'stats.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
print('INSPECTED', len(stats), flush=True)
