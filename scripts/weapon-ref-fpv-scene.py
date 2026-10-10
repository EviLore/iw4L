"""Blender: rebuild dump_fpv_clips output as a skinned rig with one action per clip, render study frames, save a .blend.

blender -b --factory-startup --python scripts/weapon-ref-fpv-scene.py -- <fpv_dir> <out_dir> [clip ...] [--every N]

The armature rests in the composed bind pose from rig.json; each clip's world matrices become pose keys per frame
(basis = rest_local^-1 * pose_local), so the scene plays exactly what IW4L poses. Units are inches (IW4 axes, X
forward, Z up). For every clip it renders the eye view (camera on tag_camera, 80.7 deg horizontal, MW2's 65 at 4:3
widened to 16:9), a right-side orthographic view, and right and left orthographic views fixed in j_gun space (hand
placement on the gun) every N frames (default 1), then saves <out_dir>/study.blend.
Output stays under iw4l-artifacts/ (gitignored).
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
every = 1
if "--every" in argv:
    i = argv.index("--every")
    every = int(argv[i + 1])
    argv = argv[:i] + argv[i + 2:]
fpv, out = Path(argv[0]), Path(argv[1])
wanted = argv[2:]
out.mkdir(parents=True, exist_ok=True)


def m4(cols):
    return Matrix([cols[0:4], cols[4:8], cols[8:12], cols[12:16]]).transposed()


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
rig = json.loads((fpv / "rig.json").read_text())
bones = rig["bones"]
rest = [m4(b["rest"]) for b in bones]

arm_data = bpy.data.armatures.new("fpv")
arm = bpy.data.objects.new("fpv", arm_data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
names = []
for i, b in enumerate(bones):
    name = b["name"] if b["name"] not in names else f'{b["name"]}.{i}'
    names.append(name)
    eb = arm_data.edit_bones.new(name)
    eb.head = (0, 0, 0)
    eb.tail = (0, 0.6, 0)
    eb.matrix = rest[i]
for i, b in enumerate(bones):
    if b["parent"] is not None:
        arm_data.edit_bones[names[i]].parent = arm_data.edit_bones[names[b["parent"]]]
bpy.ops.object.mode_set(mode="OBJECT")
arm.data.display_type = "STICK"


def mesh(label, data, colour):
    me = bpy.data.meshes.new(label)
    me.from_pydata([tuple(v) for v in data["verts"]], [], [tuple(f) for f in data["faces"]])
    me.update()
    ob = bpy.data.objects.new(label, me)
    scene.collection.objects.link(ob)
    groups = {}
    for v, (bs, ws) in enumerate(data["weights"]):
        for b, w in zip(bs, ws):
            g = groups.get(b) or ob.vertex_groups.new(name=names[b])
            groups[b] = g
            g.add([v], w, "ADD")
    ob.modifiers.new("arm", "ARMATURE").object = arm
    ob.parent = arm
    mat = bpy.data.materials.new(label)
    mat.diffuse_color = colour
    me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    return ob


mesh("hands", rig["meshes"]["hands"], (0.78, 0.6, 0.5, 1))
mesh("gun", rig["meshes"]["gun"], (0.32, 0.34, 0.37, 1))

# Eye camera on tag_camera: IW4 looks down +X with Z up; a Blender camera looks down -Z with Y up.
cam = bpy.data.objects.new("eye", bpy.data.cameras.new("eye"))
scene.collection.objects.link(cam)
cam.parent = arm
cam.parent_type = "BONE"
eye_bone = "tag_camera" if "tag_camera" in names else "tag_view"
cam.parent_bone = eye_bone
cam.matrix_parent_inverse = Matrix.Identity(4)
axes = Matrix(((0, 0, -1, 0), (-1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
cam.matrix_basis = Matrix.Translation((0, -0.6, 0)) @ axes  # parent_type BONE sits at the bone tail; step back to the head
cam.data.sensor_fit = "HORIZONTAL"
cam.data.angle = math.radians(80.7)
cam.data.clip_start = 0.5
side = bpy.data.objects.new("side", bpy.data.cameras.new("side"))
scene.collection.objects.link(side)
side.data.type = "ORTHO"
side.data.ortho_scale = 46
side.location = (12, -60, -4)
side.rotation_euler = (math.radians(90), 0, 0)


def gun_camera(label, columns, at):
    """Orthographic camera fixed in j_gun space, so hand placement on the gun reads the same through any motion."""
    c = bpy.data.objects.new(label, bpy.data.cameras.new(label))
    scene.collection.objects.link(c)
    c.parent, c.parent_type, c.parent_bone = arm, "BONE", "j_gun"
    c.matrix_parent_inverse = Matrix.Identity(4)
    x, y, z = columns
    rot = Matrix(((x[0], y[0], z[0], 0), (x[1], y[1], z[1], 0), (x[2], y[2], z[2], 0), (0, 0, 0, 1)))
    c.matrix_basis = Matrix.Translation((0, -0.6, 0)) @ Matrix.Translation(at) @ rot
    c.data.type, c.data.ortho_scale, c.data.clip_end = "ORTHO", 30, 200
    return c


gun_right = gun_camera("gun_right", ((1, 0, 0), (0, 0, 1), (0, -1, 0)), (7, -50, -1))
gun_left = gun_camera("gun_left", ((-1, 0, 0), (0, 0, 1), (0, 1, 0)), (7, 50, -1))

scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_cavity = True
scene.display.render_aa = "8"
scene.world = bpy.data.worlds.new("w")
scene.world.color = (0.82, 0.84, 0.86)
scene.render.resolution_x, scene.render.resolution_y = 960, 540
scene.render.fps = 30

parent_of = [b["parent"] for b in bones]
rest_local = [rest[i] if p is None else rest[p].inverted() @ rest[i] for i, p in enumerate(parent_of)]
clip_files = sorted((fpv / "clips").glob("*.json"))
if wanted:
    clip_files = [f for f in clip_files if f.stem in wanted]
arm.animation_data_create()
for f in clip_files:
    clip = json.loads(f.read_text())
    action = bpy.data.actions.new(clip["name"])
    action.use_fake_user = True
    arm.animation_data.action = action
    for frame, world in enumerate(clip["frames"]):
        world = [m4(w) for w in world]
        for i, pb_name in enumerate(names):
            p = parent_of[i]
            local = world[i] if p is None else world[p].inverted() @ world[i]
            basis = rest_local[i].inverted() @ local
            pb = arm.pose.bones[pb_name]
            pb.rotation_mode = "QUATERNION"
            loc, rot, _ = basis.decompose()
            pb.location, pb.rotation_quaternion = loc, rot
            pb.keyframe_insert("location", frame=frame)
            pb.keyframe_insert("rotation_quaternion", frame=frame)
    scene.frame_start, scene.frame_end = 0, len(clip["frames"]) - 1
    for frame in range(0, len(clip["frames"]), every):
        scene.frame_set(frame)
        for view, camera in (("eye", cam), ("side", side), ("gun_right", gun_right), ("gun_left", gun_left)):
            scene.camera = camera
            scene.render.filepath = str(out / clip["name"] / f"{view}_{frame:03d}.png")
            bpy.ops.render.render(write_still=True)
    print("CLIP", clip["name"], len(clip["frames"]), "frames")
bpy.ops.wm.save_as_mainfile(filepath=str(out / "study.blend"))
