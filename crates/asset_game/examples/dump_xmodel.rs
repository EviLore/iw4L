//! Reference export of IW4 XModels for study: OBJ geometry plus a JSON skeleton and skin.
//!
//! cargo run --profile play -p asset_game --example dump_xmodel -- <out_dir> <name filter> <zone.ff>...
//!
//! Every XModel whose name contains the filter is written as <name>.obj (one group per surface, model
//! space, inches) and <name>.json (bones with parent and model-space bind pose, per-vertex skin).
//! Output stays under iw4l-artifacts/ (gitignored): it is game data and is never committed.

use std::fmt::Write as _;
use std::fs;
use std::path::PathBuf;

use asset_model::capture_xmodel_skel;
use asset_transport::{ZoneMemory, open_zone_shared};
use fastfile_iw4::{
    AssetLinkSink, AssetSink, AssetType, Ptr, ScriptStrings, ZoneStream, load_asset_at_observed,
    load_zone,
};

struct Sink {
    strings: ScriptStrings,
    filter: String,
    out_dir: PathBuf,
    matched: Vec<String>,
}

impl AssetSink for Sink {
    fn set_script_strings(&mut self, strings: ScriptStrings) {
        self.strings = strings;
    }

    fn load_asset(
        &mut self,
        s: &mut ZoneStream<'_>,
        _index: usize,
        ty: AssetType,
        slot: Ptr,
    ) -> fastfile_iw4::Result<()> {
        load_asset_at_observed(s, ty, slot, self)?;
        Ok(())
    }
}

impl AssetLinkSink for Sink {
    fn loaded(
        &mut self,
        s: &ZoneStream<'_>,
        ty: AssetType,
        _slot: Ptr,
        _insert_slot: Option<Ptr>,
    ) -> fastfile_iw4::Result<()> {
        if ty != AssetType::XModel {
            return Ok(());
        }
        let Some(geometry) = s.xmodel() else { return Ok(()) };
        let Some(name) = geometry.name.and_then(|p| s.cstr(p).ok()) else { return Ok(()) };
        if !name.to_ascii_lowercase().contains(&self.filter) {
            return Ok(());
        }
        let Some(skel) = capture_xmodel_skel(s, &self.strings, geometry, None) else {
            eprintln!("{name}: capture failed");
            return Ok(());
        };
        let file = name.replace(['/', '\\'], "_");
        let mut obj = format!("# {name} (IW4 reference, inches, model space)\n");
        for p in &skel.positions {
            let _ = writeln!(obj, "v {} {} {}", p[0], p[1], p[2]);
        }
        for n in &skel.normals {
            let _ = writeln!(obj, "vn {} {} {}", n[0], n[1], n[2]);
        }
        for uv in &skel.uvs {
            let _ = writeln!(obj, "vt {} {}", uv[0], 1.0 - uv[1]);
        }
        let has_n = skel.normals.len() == skel.positions.len();
        let has_uv = skel.uvs.len() == skel.positions.len();
        let lod0 = skel.surfaces_for_lod(0);
        for (surface, &(start, count)) in skel.surface_index_ranges.iter().enumerate() {
            if !lod0.contains(&surface) {
                continue;
            }
            let _ = writeln!(obj, "g surface_{surface}");
            for tri in skel.indices[start..start + count].chunks_exact(3) {
                let v: Vec<String> = tri
                    .iter()
                    .map(|&i| {
                        let i = i + 1;
                        match (has_uv, has_n) {
                            (true, true) => format!("{i}/{i}/{i}"),
                            (false, true) => format!("{i}//{i}"),
                            (true, false) => format!("{i}/{i}"),
                            (false, false) => format!("{i}"),
                        }
                    })
                    .collect();
                let _ = writeln!(obj, "f {}", v.join(" "));
            }
        }
        fs::write(self.out_dir.join(format!("{file}.obj")), obj).unwrap();

        let bones: Vec<serde_json::Value> = skel
            .bones
            .iter()
            .enumerate()
            .map(|(i, b)| {
                serde_json::json!({
                    "name": skel.bone_names.get(i).cloned().unwrap_or_default(),
                    "parent": skel.parent_of(i),
                    "quat": b.quat,
                    "trans": b.trans,
                })
            })
            .collect();
        let skin: Vec<serde_json::Value> = skel
            .vert_skin
            .iter()
            .map(|v| serde_json::json!([v.bones, v.weights]))
            .collect();
        let json = serde_json::json!({
            "name": name,
            "bounds": skel.bounds,
            "vertices": skel.positions.len(),
            "triangles": skel.indices.len() / 3,
            "lod0_surfaces": [lod0.start, lod0.end],
            "surface_index_ranges": skel.surface_index_ranges,
            "surface_vertex_ranges": skel.surface_vertex_ranges,
            "bones": bones,
            "skin": skin,
        });
        fs::write(
            self.out_dir.join(format!("{file}.json")),
            serde_json::to_string(&json).unwrap(),
        )
        .unwrap();
        self.matched.push(format!(
            "{name}\tverts={}\ttris={}\tbones={}\tbounds={:?}",
            skel.positions.len(),
            skel.indices.len() / 3,
            skel.bones.len(),
            skel.bounds
        ));
        Ok(())
    }

    fn alias(&mut self, _ty: AssetType, _slot: Ptr, _target: Ptr) -> fastfile_iw4::Result<()> {
        Ok(())
    }
}

fn main() {
    let mut args = std::env::args().skip(1);
    let out_dir = PathBuf::from(args.next().expect("usage: <out_dir> <filter> <zone.ff>..."));
    let filter = args.next().expect("usage: <out_dir> <filter> <zone.ff>...").to_ascii_lowercase();
    let zones: Vec<PathBuf> = args.map(PathBuf::from).collect();
    fs::create_dir_all(&out_dir).unwrap();
    let mut sink = Sink { strings: ScriptStrings::default(), filter, out_dir, matched: Vec::new() };
    for zone in &zones {
        let image = open_zone_shared(zone).unwrap_or_else(|e| panic!("{}: {e}", zone.display()));
        let header = image.header().expect("zone header");
        let mut memory = ZoneMemory::for_header(&header);
        let mut stream = memory.stream(&image.bytes).expect("zone stream");
        if let Err(e) = load_zone(&mut stream, &mut sink) {
            eprintln!("{}: stopped: {e:?}", zone.display());
        }
    }
    for line in &sink.matched {
        println!("{line}");
    }
}
