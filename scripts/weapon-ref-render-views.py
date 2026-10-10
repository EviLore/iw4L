"""Blender: render orthographic and three-quarter reference views of an OBJ (IW4 inches, X forward, Z up).

blender -b --factory-startup --python scripts/weapon-ref-render-views.py -- <model.obj> <out_dir>
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

obj_path, out_dir = sys.argv[sys.argv.index("--") + 1:][:2]
out = Path(out_dir)
out.mkdir(parents=True, exist_ok=True)
stem = Path(obj_path).stem

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=obj_path, forward_axis="Y", up_axis="Z")
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in objs:
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre, size = (lo + hi) / 2, hi - lo
print(f"BOUNDS {stem} min={tuple(round(v, 3) for v in lo)} max={tuple(round(v, 3) for v in hi)} "
      f"size_in={tuple(round(v, 3) for v in size)} size_cm={tuple(round(v * 2.54, 1) for v in size)}")

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light = "STUDIO"
shading.color_type = "SINGLE"
shading.single_color = (0.62, 0.63, 0.66)
shading.show_cavity = True
shading.cavity_type = "BOTH"
shading.show_object_outline = True
scene.display.render_aa = "8"
scene.render.film_transparent = False
world = bpy.data.worlds.new("w")
scene.world = world
world.color = (0.93, 0.93, 0.93)
scene.render.resolution_x, scene.render.resolution_y = 1600, 900

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
span = max(size) * 1.15
dist = max(size) * 4

views = {
    "right": Vector((0, -1, 0)), "left": Vector((0, 1, 0)), "front": Vector((1, 0, 0)),
    "back": Vector((-1, 0, 0)), "top": Vector((0, 0, 1)), "bottom": Vector((0, 0, -1)),
    "three_quarter_front": Vector((1, -1.2, 0.6)), "three_quarter_back": Vector((-1, -1.2, 0.6)),
    "three_quarter_left": Vector((0.8, 1.2, 0.5)),
}
for name, d in views.items():
    d = d.normalized()
    cam.location = centre + d * dist
    up = Vector((1, 0, 0)) if abs(d.z) > 0.99 else Vector((0, 0, 1))
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y" if up.z else "X").to_euler()
    if name.startswith("three_quarter"):
        cam_data.type = "PERSP"
        cam_data.lens = 85
        cam.location = centre + d * max(size) * 3.2
    else:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = span
    cam_data.clip_end = dist * 4
    scene.render.filepath = str(out / f"{stem}_{name}.png")
    bpy.ops.render.render(write_still=True)
