"""Summarize dump_weapon_ref output into weapons.tsv + clips.tsv for base MP weapons."""
import csv
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
FIELDS = [
    "clip_size", "fire_time_ms", "damage", "raise_time_ms", "drop_time_ms", "first_raise_time_ms",
    "quick_raise_time_ms", "quick_drop_time_ms", "reload_time_ms", "reload_empty_time_ms",
    "reload_add_time_ms", "sprint_raise_time_ms", "sprint_loop_time_ms", "sprint_drop_time_ms",
    "ads_in_rate", "ads_out_rate", "ads_reload_trans_time_ms", "ads_zoom_fov", "ads_zoom_in_frac",
    "ads_zoom_out_frac", "ads_bob_factor", "ads_view_bob_mult", "move_speed_scale",
    "ads_move_speed_scale", "hip_idle_amount", "hip_idle_speed", "ads_idle_amount",
    "ads_idle_speed", "pos_move_rate", "pos_rot_rate", "sway_max_angle", "sway_lerp_speed",
    "sway_pitch_scale", "sway_yaw_scale", "sway_horiz_scale", "sway_vert_scale",
    "ads_sway_max_angle", "ads_sway_lerp_speed", "ads_sway_horiz_scale", "ads_sway_vert_scale",
    "gun_max_pitch", "gun_max_yaw", "hip_gun_kick_pitch_min", "hip_gun_kick_pitch_max",
    "hip_gun_kick_yaw_min", "hip_gun_kick_yaw_max", "hip_gun_kick_accel",
    "hip_gun_kick_speed_decay", "hip_gun_kick_static_decay", "ads_gun_kick_pitch_min",
    "ads_gun_kick_pitch_max", "ads_gun_kick_yaw_min", "ads_gun_kick_yaw_max",
    "ads_gun_kick_accel", "ads_gun_kick_speed_decay", "ads_gun_kick_static_decay",
    "ads_view_kick_pitch_min", "ads_view_kick_pitch_max", "hip_view_kick_pitch_min",
    "hip_view_kick_pitch_max", "f_ads_view_kick_center_speed", "f_hip_view_kick_center_speed",
    "hip_spread_stand_min", "hip_spread_stand_max", "player_anim_type", "weap_class",
]
SLOTS = ["reload", "reload_empty", "raise", "first_raise", "drop", "quick_raise", "quick_drop",
         "sprint_in", "sprint_loop", "sprint_out", "ads_up", "ads_down", "fire", "ads_fire", "idle"]
scalar = re.compile(r"^\s+([a-z_0-9]+): (-?[0-9.]+(?:e-?[0-9]+)?|true|false),$")
slot_re = re.compile(r"^  ([a-z_]+): (\S+)$")

clips = {}
with open(root / "xanims.tsv") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        clips[row["name"].lower()] = row

base = sorted(p for p in (root / "weapons").glob("*.txt") if re.fullmatch(r"[a-z0-9]+_mp", p.stem))
rows, clip_rows = [], []
for path in base:
    vals, slots = {}, {}
    in_geom = False
    for line in path.read_text().splitlines():
        if line == "geometry:":
            in_geom = True
            continue
        m = (scalar if in_geom else slot_re).match(line)
        if m and in_geom:
            vals.setdefault(m.group(1), m.group(2))
        elif m:
            slots[m.group(1)] = m.group(2)
    if "reload" not in slots:
        continue
    row = {"weapon": path.stem, **{k: vals.get(k, "") for k in FIELDS}}
    for s in SLOTS:
        c = clips.get(slots.get(s, "").lower(), {})
        row[f"{s}_clip_s"] = c.get("duration_s", "")
    rows.append(row)
    for s in SLOTS:
        name = slots.get(s)
        if name and name.lower() in clips:
            c = clips[name.lower()]
            clip_rows.append({"weapon": path.stem, "slot": s, "clip": name,
                              "frames": c["frames"], "fps": c["fps"], "duration_s": c["duration_s"],
                              "notetracks": c["notetracks"]})

with open(root / "weapons.tsv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
    w.writeheader()
    w.writerows(rows)
with open(root / "clips.tsv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(clip_rows[0].keys()), delimiter="\t")
    w.writeheader()
    w.writerows(clip_rows)
print(f"{len(rows)} base weapons, {len(clip_rows)} slot clips")
