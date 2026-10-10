"""Key-pose breakdown of dump_fpv_clips output: where the gun, hands, magazine and charging handle are, and when.

python3 -I scripts/weapon-ref-fpv-keys.py <fpv_dir> <clip> [clip ...] > keys.txt

For each clip it prints, every frame, the gun (tag_weapon) relative to the eye (tag_view), each wrist and the
magazine (tag_clip) and charging handle (j_reload) relative to the gun (j_gun), in inches and degrees (yaw,
pitch, roll), plus each hand's finger curl (sum of finger joint bend, degrees). Rows where a hand stops or
starts moving relative to the gun are flagged, which is where the key poses are.
"""
import json
import math
import sys
from pathlib import Path


def mat(c):
    return [[c[0], c[4], c[8], c[12]], [c[1], c[5], c[9], c[13]], [c[2], c[6], c[10], c[14]], [0, 0, 0, 1]]


def inv(m):
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def euler(m):
    """yaw (Z), pitch (Y, nose down positive as in IW4), roll (X) in degrees."""
    yaw = math.degrees(math.atan2(m[1][0], m[0][0]))
    pitch = math.degrees(math.asin(max(-1, min(1, -m[2][0]))))
    roll = math.degrees(math.atan2(m[2][1], m[2][2]))
    return yaw, pitch, roll


def angle(m):
    tr = max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2))
    return math.degrees(math.acos(tr))


fpv = Path(sys.argv[1])
rig = json.loads((fpv / "rig.json").read_text())
names = [b["name"] for b in rig["bones"]]
parent = [b["parent"] for b in rig["bones"]]
idx = {n: i for i, n in reversed(list(enumerate(names)))}
FINGERS = {side: [i for i, n in enumerate(names) if (n.endswith(f"_{side}_1") or n.endswith(f"_{side}_2"))
                  and not n.startswith("j_thumb")] for side in ("ri", "le")}

for clip_name in sys.argv[2:]:
    clip = json.loads((fpv / "clips" / f"{clip_name}.json").read_text())
    frames = [[mat(m) for m in f] for f in clip["frames"]]
    fps = clip["fps"]
    notes = ", ".join(f"{n}@{t * clip['duration']:.2f}s" for n, t in clip["notetracks"] if n != "end")
    print(f"\n== {clip_name}: {clip['numframes']} frames at {fps:g} fps = {clip['duration']:.3f} s; notetracks: {notes or 'none'}")
    print("frame time  | gun vs eye x y z (in) yaw pitch roll | wrist_ri vs gun x y z | wrist_le vs gun x y z  | mag vs gun x y z     | ch.handle x | curl ri le | flags")
    prev = None
    moving_prev = {"le": None, "ri": None}
    for f, w in enumerate(frames):
        g = w[idx["j_gun"]]
        gi = inv(g)
        rel = lambda b: mul(gi, w[idx[b]])
        eye = mul(inv(w[idx["tag_view"]]), w[idx["tag_weapon"]])
        ri, le, mag, ch = rel("j_wrist_ri"), rel("j_wrist_le"), rel("tag_clip"), rel("j_reload")
        y, p, r = euler(eye)
        curls = {s: sum(angle(mul(inv(w[parent[b]]), w[b])) for b in FINGERS[s]) for s in ("ri", "le")}
        pos = {"ri": [ri[i][3] for i in range(3)], "le": [le[i][3] for i in range(3)]}
        flags = []
        if prev:
            for s in ("ri", "le"):
                speed = math.dist(pos[s], prev[s]) * fps
                moving = speed > 3.0  # inches per second relative to the gun
                if moving_prev[s] is not None and moving != moving_prev[s]:
                    flags.append(f"{s} {'starts' if moving else 'stops'} ({speed:.0f} in/s)")
                moving_prev[s] = moving
        prev = pos
        print(f"{f:5d} {f / fps:5.2f} | {eye[0][3]:6.2f} {eye[1][3]:6.2f} {eye[2][3]:6.2f} {y:6.1f} {p:6.1f} {r:6.1f} "
              f"| {ri[0][3]:6.2f} {ri[1][3]:6.2f} {ri[2][3]:6.2f} | {le[0][3]:6.2f} {le[1][3]:6.2f} {le[2][3]:6.2f} "
              f"| {mag[0][3]:6.2f} {mag[1][3]:6.2f} {mag[2][3]:6.2f} | {ch[0][3]:6.2f} | {curls['ri']:4.0f} {curls['le']:4.0f} | {'; '.join(flags)}")
