"""Hand hold shapes from dump_fpv_clips output, measured into another gun's frame, for authoring our own clips.

python3 -I scripts/weapon-ref-holds.py <fpv_dir> <out.json>

Each hold is one frame of one clip: where the wrist and every finger joint (MCP, PIP, DIP and the distal bone's
direction) sit relative to the gun (j_gun), the magazine (tag_clip) or the eye (tag_view). Output is in the receiving
gun's authoring frame: metres, +X right, +Y forward (muzzle), +Z up, MW2's M4 scaled 0.969 to the published length and
its gun origin placed 44.3 mm ahead of the upper receiver's rear, 56.1 mm under the bore (the M4 study's mapping).
"""
import json
import sys
from pathlib import Path

IN = .0254 * .969
ORIGIN = (0.0, .0443, -.0561)
HOLDS = {
    # name: (clip, frame, hand, relative to)
    'grip_r': ('viewmodel_m4_idle', 0, 'ri', 'j_gun'),          # firing grip, index along the receiver
    'release_r': ('viewmodel_m4_reload', 11, 'ri', 'j_gun'),     # index on the magazine release
    'support_l': ('viewmodel_m4_idle', 0, 'le', 'j_gun'),       # support grip under the handguard
    'open_l': ('viewmodel_m4_pullout', 0, 'le', 'j_gun'),       # open hand riding the handguard
    'vest_l': ('viewmodel_m4_reload', 16, 'le', 'tag_view'),    # at the pouch, closing on a magazine
    'mag_l': ('viewmodel_m4_reload', 27, 'le', 'tag_clip'),     # holding the fresh magazine
    'catch_l': ('viewmodel_m4_reload_empty', 52, 'le', 'j_gun'),  # thumb on the bolt catch
}
FINGERS = {'thumb': 'j_thumb_{s}_{k}', 'index': 'j_index_{s}_{k}', 'middle': 'j_mid_{s}_{k}', 'ring': 'j_ring_{s}_{k}',
           'pinky': 'j_pinky_{s}_{k}'}


def mat(c): return [[c[0], c[4], c[8], c[12]], [c[1], c[5], c[9], c[13]], [c[2], c[6], c[10], c[14]], [0, 0, 0, 1]]


def inv(m):
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0, 0, 0, 1]]


def mul(a, b): return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def point(m, frame):
    """A position into the receiving frame: IW4 inches (X fwd, Y left, Z up) to metres (X right, Y fwd, Z up)."""
    x, y, z = m[0][3], m[1][3], m[2][3]
    p = [-y * IN, x * IN, z * IN]
    return [round(p[i] + (ORIGIN[i] if frame == 'j_gun' else 0), 5) for i in range(3)]


def axis(m):
    """A bone's own +X (IW4 bones point down +X) as a direction in the receiving frame."""
    return [round(-m[1][0], 5), round(m[0][0], 5), round(m[2][0], 5)]


def rotation(m):
    """A bone's rotation into the receiving frame's axes (rows of a 3x3): C R C^T with C taking IW4 to ours."""
    C = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    R = [[m[i][j] for j in range(3)] for i in range(3)]
    CR = [[sum(C[i][k] * R[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return [[round(sum(CR[i][k] * C[j][k] for k in range(3)), 5) for j in range(3)] for i in range(3)]


MAG_KEYS = {'viewmodel_m4_reload': range(0, 44, 2)}   # the magazine relative to the gun through the change


def main():
    fpv, out = Path(sys.argv[1]), Path(sys.argv[2])
    rig = json.loads((fpv / 'rig.json').read_text())
    idx = {}
    for i, b in enumerate(rig['bones']): idx.setdefault(b['name'], i)
    holds = {}
    for name, (clip, frame, s, rel) in HOLDS.items():
        w = [mat(c) for c in json.loads((fpv / 'clips' / f'{clip}.json').read_text())['frames'][frame]]
        base = inv(w[idx[rel]])
        local = lambda b: mul(base, w[idx[b]])  # noqa: E731
        hold = {'clip': clip, 'frame': frame, 'relative': {'j_gun': 'gun', 'tag_clip': 'magazine', 'tag_view': 'eye'}[rel],
                'wrist': point(local(f'j_wrist_{s}'), rel), 'fingers': {}}
        for finger, pattern in FINGERS.items():
            joints = [local(pattern.format(s=s, k=k)) for k in range(3)]
            hold['fingers'][finger] = {'joints': [point(j, rel) for j in joints], 'tip': axis(joints[2])}
        holds[name] = hold
    mag = {}
    for clip, frames in MAG_KEYS.items():
        data = json.loads((fpv / 'clips' / f'{clip}.json').read_text())
        rows = []
        for f in frames:
            w = [mat(c) for c in data['frames'][f]]
            m = mul(inv(w[idx['j_gun']]), w[idx['tag_clip']])
            rest = [4.29, -.01, 1.29]   # the seated magazine's top on MW2's gun, inches
            rows.append({'frame': f, 'seconds': round(f / data['fps'], 4), 'offset': [round(-(m[1][3] - rest[1]) * IN, 5), round((m[0][3] - rest[0]) * IN, 5),
                         round((m[2][3] - rest[2]) * IN, 5)], 'rotation': rotation(m)})
        mag[clip] = rows
    out.write_text(json.dumps({'source': 'MW2 M4 study (#513), measured with dump_fpv_clips', 'holds': holds, 'magazine': mag}, indent=1) + '\n')
    print(f'{len(holds)} holds -> {out}')


main()
