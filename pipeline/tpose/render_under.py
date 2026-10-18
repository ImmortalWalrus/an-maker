"""Render an equipped look (its real 3D pieces, as shown: look pose, masks on) from the step-1 cameras, so the next
layer can be drawn ON TOP OF THE ACTUAL GEOMETRY beneath it (bulk, folds, hems) instead of an imagined slimmer one.

Run: blender -b --factory-startup -P pipeline/tpose/render_under.py -- <look_dir> <base> <out_dir> [--exclude key ...]
Writes <out_dir>/{front,left,back,right}.png (same camera, framing and lighting as 01_mannequin).
"""
import bpy, sys, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402
from s1_render_mannequin import VIEWS, setup_camera  # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:]
look, base, out = Path(args[0]).resolve(), args[1], Path(args[2]).resolve()
exclude = args[args.index('--exclude') + 1:] if '--exclude' in args else []
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(look / '06_fitted' / f'{look.name}__{base}.blend'))
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
F.apply_look_pose(arm, look)
for o in bpy.data.objects:
    if o.type == 'MESH' and any(o.name.endswith('__' + k) for k in exclude):
        o.hide_render = True
for o in bpy.data.objects:  # helper objects from earlier inspection runs
    if o.type == 'CAMERA' or (o.type == 'MESH' and o.name.startswith(('Sphere', 'Icosphere'))):
        o.hide_render = o.type == 'MESH' or o.hide_render
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.render.film_transparent = False
scene.view_settings.view_transform = 'Standard'
world = scene.world or bpy.data.worlds.new('under_world')
scene.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
world.node_tree.nodes['Background'].inputs[1].default_value = 1.0
sun = bpy.data.objects.new('key', bpy.data.lights.new('key', 'SUN'))
sun.data.energy = 2.5
sun.rotation_euler = (math.radians(50), 0, math.radians(25))
scene.collection.objects.link(sun)
for view in VIEWS:
    setup_camera(scene, view)
    scene.render.filepath = str(out / f'{view}.png')
    bpy.ops.render.render(write_still=True)
print('UNDER', out, flush=True)
