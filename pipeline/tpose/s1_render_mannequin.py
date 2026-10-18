"""Step 1 - render the Genies base avatar in its T-pose rest from 4 fixed orthographic cameras (front, left, back,
right) plus flat silhouette masks, and save every camera so later steps convert pixels <-> metres exactly.

Run: blender -b --factory-startup -P pipeline/tpose/s1_render_mannequin.py -- <outfit_dir> <base>
Writes <outfit_dir>/01_mannequin/<view>.png, <view>_mask.png, camera.json
camera.json: for each view, `to_camera` (unit vector from the subject toward the camera) and `right` (world
direction of +u in the image). A pixel (u, v) at depth t along to_camera is
    world = center + right*(u - W/2)*mpp + up*(H/2 - v)*mpp + to_camera*t,   up = +Z
"""
import bpy, sys, json, math
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
CAMERA = {'res': [1024, 1536], 'ortho_scale': 2.25, 'center': [0.0, 0.0, 0.8]}
VIEWS = {  # view: direction from subject to camera (character faces -Y; its left is +X)
    'front': (0, -1, 0), 'left': (1, 0, 0), 'back': (0, 1, 0), 'right': (-1, 0, 0),
}


def setup_camera(scene, view):
    cam = bpy.data.objects.get('mannequin_cam') or bpy.data.objects.new('mannequin_cam', bpy.data.cameras.new('mannequin_cam'))
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = CAMERA['ortho_scale']
    cam.data.sensor_fit = 'AUTO'
    cam.data.clip_start, cam.data.clip_end = 0.01, 50
    d = Vector(VIEWS[view])
    cam.location = Vector(CAMERA['center']) + d * 10
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = CAMERA['res']
    scene.render.resolution_percentage = 100
    bpy.context.view_layer.update()
    right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
    return [round(c, 6) for c in d], [round(c, 6) for c in right]


def main():
    out_dir, base = Path(sys.argv[sys.argv.index('--') + 1]).resolve(), sys.argv[sys.argv.index('--') + 2]
    out = out_dir / '01_mannequin'
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'Bases' / f'{base}.blend'))
    scene = bpy.context.scene
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    for pb in arm.pose.bones:  # rest pose = T-pose
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()

    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 48
    scene.cycles.use_denoising = True
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    world = scene.world or bpy.data.worlds.new('mannequin_world')
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 1.0
    sun = bpy.data.objects.new('key', bpy.data.lights.new('key', 'SUN'))
    sun.data.energy = 2.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(25))
    scene.collection.objects.link(sun)
    views = {}
    for view in VIEWS:
        to_cam, right = setup_camera(scene, view)
        views[view] = {'to_camera': to_cam, 'right': right}
        scene.render.filepath = str(out / f'{view}.png')
        bpy.ops.render.render(write_still=True)

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'SINGLE'
    scene.display.shading.single_color = (1, 1, 1)
    scene.display.shading.background_type = 'VIEWPORT'
    scene.display.shading.background_color = (0, 0, 0)
    scene.display.shading.show_cavity = False
    scene.display.shading.show_shadows = False
    for view in VIEWS:
        setup_camera(scene, view)
        scene.render.filepath = str(out / f'{view}_mask.png')
        bpy.ops.render.render(write_still=True)

    W, H = CAMERA['res']
    cam = dict(CAMERA, base=base, metres_per_pixel=CAMERA['ortho_scale'] / max(W, H), up=[0, 0, 1], views=views)
    (out / 'camera.json').write_text(json.dumps(cam, indent=2), encoding='utf-8')
    print('MANNEQUIN', out, json.dumps(views), flush=True)


if __name__ == '__main__':
    main()
