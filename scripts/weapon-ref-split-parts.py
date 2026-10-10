"""Split an exported IW4 model OBJ into parts by each vertex's primary bone (dump_xmodel.py output).

python3 -I scripts/weapon-ref-split-parts.py <model.obj> <out_dir> <part=bone,bone,...>...
Writes <out_dir>/<model>__<part>.obj with only the faces whose three vertices all belong to that part's bones.
"""
import json
import sys
from pathlib import Path

obj_path, out_dir, *specs = sys.argv[1:]
obj_path, out = Path(obj_path), Path(out_dir)
out.mkdir(parents=True, exist_ok=True)
meta = json.loads(obj_path.with_suffix(".json").read_text())
names = [b["name"] for b in meta["bones"]]
primary = [names[b[0][0]] if b[0][0] < len(names) else "?" for b in meta["skin"]]

lines = obj_path.read_text().splitlines()
verts = [l for l in lines if l.startswith("v ")]
uvs = [l for l in lines if l.startswith("vt ")]
faces = [l for l in lines if l.startswith("f ")]

for spec in specs:
    part, bones = spec.split("=")
    keep = set(bones.split(","))
    used, kept = {}, []
    for f in faces:
        idx = [int(t.split("/")[0]) - 1 for t in f.split()[1:]]
        if all(primary[i] in keep for i in idx):
            kept.append(idx)
            for i in idx:
                used.setdefault(i, len(used) + 1)
    order = sorted(used, key=used.get)
    text = [f"# {meta['name']} part {part}: bones {sorted(keep)}"]
    text += [verts[i] for i in order]
    if len(uvs) == len(verts):
        text += [uvs[i] for i in order]
        text += ["f " + " ".join(f"{used[i]}/{used[i]}" for i in tri) for tri in kept]
    else:
        text += ["f " + " ".join(str(used[i]) for i in tri) for tri in kept]
    dest = out / f"{obj_path.stem}__{part}.obj"
    dest.write_text("\n".join(text) + "\n")
    print(f"{dest.name}: {len(order)} verts, {len(kept)} tris")
