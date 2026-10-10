//! Local reference dump (not part of IW4L): weapon timing/sway/kick fields and
//! viewmodel xanim timing, notetracks and key-bone curves from IW4 zones.
//!
//! cargo run --profile play -p asset_game --example dump_weapon_ref -- <out_dir> <zone.ff>...
//! python3 -I scripts/weapon-ref-summarize.py <out_dir>   # weapons.tsv + clips.tsv for base MP weapons
//!
//! Output stays under iw4l-artifacts/ (gitignored): it is game data and is never committed.

use std::fmt::Write as _;
use std::fs;
use std::path::PathBuf;

use asset_anim::{AssetNamespace, XAnimBuild};
use asset_transport::{ZoneMemory, open_zone_shared};
use fastfile_iw4::{
    AssetLinkSink, AssetSink, AssetType, Ptr, ScriptStrings, XAnimPartsGeometry, ZonePtr,
    ZoneStream, load_asset_at_observed, load_zone,
};

const SLOT_NAMES: [&str; 37] = [
    "root", "idle", "empty_idle", "fire", "hold_fire", "lastshot", "rechamber", "melee",
    "melee_charge", "reload", "reload_empty", "reload_start", "reload_end", "raise",
    "first_raise", "breach_raise", "drop", "alt_raise", "alt_drop", "quick_raise", "quick_drop",
    "empty_raise", "empty_drop", "sprint_in", "sprint_loop", "sprint_out", "stunned_start",
    "stunned_loop", "stunned_end", "detonate", "nightvision_wear", "nightvision_remove",
    "ads_fire", "ads_lastshot", "ads_rechamber", "ads_up", "ads_down",
];

struct Sink {
    xanims: XAnimBuild,
    weapons: Vec<(String, String)>,
}

fn name_at(s: &ZoneStream<'_>, p: Option<Ptr>) -> String {
    p.and_then(|p| s.cstr(p).ok()).unwrap_or("").to_owned()
}

impl AssetSink for Sink {
    fn set_script_strings(&mut self, strings: ScriptStrings) {
        self.xanims.set_strings(strings);
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
        if ty != AssetType::Weapon {
            return Ok(());
        }
        let Some(g) = s.weapon() else { return Ok(()) };
        let name = name_at(s, g.name);
        if name.is_empty() {
            return Ok(());
        }
        let mut out = String::new();
        let _ = writeln!(out, "weapon: {name}");
        let _ = writeln!(out, "gun_xmodel: {}", name_at(s, g.gun_xmodel_name));
        let _ = writeln!(out, "hand_xmodel: {}", name_at(s, g.hand_xmodel_name));
        let _ = writeln!(out, "world_model: {}", name_at(s, g.world_model_name));
        if let Some(arr) = g.sz_xanims {
            let _ = writeln!(out, "anims:");
            for (i, slot) in SLOT_NAMES.iter().enumerate() {
                let p = match s.ptr_at(arr, i * s.pointer_bytes()) {
                    Ok(ZonePtr::Offset(q)) => Some(s.resolve_alias(q)),
                    _ => None,
                };
                let anim = name_at(s, p);
                if !anim.is_empty() {
                    let _ = writeln!(out, "  {slot}: {anim}");
                }
            }
        }
        let _ = writeln!(out, "geometry:\n{g:#?}");
        self.weapons.push((name, out));
        Ok(())
    }

    fn alias(&mut self, _ty: AssetType, _slot: Ptr, _target: Ptr) -> fastfile_iw4::Result<()> {
        Ok(())
    }

    fn capture_xanim(
        &mut self,
        s: &ZoneStream<'_>,
        geometry: XAnimPartsGeometry,
    ) -> fastfile_iw4::Result<()> {
        AssetLinkSink::capture_xanim(&mut self.xanims, s, geometry)
    }
}

fn key_bone(name: &str) -> bool {
    matches!(
        name,
        "tag_view" | "tag_torso" | "tag_weapon" | "tag_weapon_right" | "tag_weapon_left"
            | "j_gun" | "j_wrist_le" | "j_wrist_ri" | "j_elbow_le" | "j_elbow_ri"
            | "j_shoulder_le" | "j_shoulder_ri" | "j_wristtwist_le" | "j_wristtwist_ri"
    ) || name.contains("clip")
        || name.contains("mag")
        || name.contains("bolt")
        || name.contains("slide")
        || name.contains("charging")
}

fn main() {
    let mut args = std::env::args().skip(1);
    let out_dir = PathBuf::from(args.next().expect("usage: <out_dir> <zone.ff>..."));
    let zones: Vec<PathBuf> = args.map(PathBuf::from).collect();
    fs::create_dir_all(out_dir.join("weapons")).unwrap();
    fs::create_dir_all(out_dir.join("curves")).unwrap();

    let mut xanims = XAnimBuild::default();
    xanims.set_capture_ns(AssetNamespace::Iw4);
    let mut sink = Sink { xanims, weapons: Vec::new() };
    for zone in &zones {
        let image = open_zone_shared(zone).unwrap_or_else(|e| panic!("{}: {e}", zone.display()));
        let header = image.header().expect("zone header");
        let mut memory = ZoneMemory::for_header(&header);
        let mut stream = memory.stream(&image.bytes).expect("zone stream");
        match load_zone(&mut stream, &mut sink) {
            Ok(_) => eprintln!("{}: ok", zone.display()),
            Err(e) => eprintln!("{}: stopped: {e:?}", zone.display()),
        }
    }

    for (name, text) in &sink.weapons {
        fs::write(out_dir.join("weapons").join(format!("{name}.txt")), text).unwrap();
    }

    let mut index = String::from("name\tframes\tfps\tduration_s\tlooping\ttracks\tnotetracks\n");
    let mut names: Vec<String> = sink.xanims.names().map(str::to_owned).collect();
    names.sort();
    for name in &names {
        let Some(clip) = sink.xanims.decode(AssetNamespace::Iw4, name) else {
            let _ = writeln!(index, "{name}\t\t\t\t\t\tDECODE_FAILED");
            continue;
        };
        let notes: Vec<String> = clip
            .notifies
            .iter()
            .map(|n| format!("{}@{:.3}", n.name, n.time))
            .collect();
        let _ = writeln!(
            index,
            "{name}\t{}\t{}\t{:.3}\t{}\t{}\t{}",
            clip.numframes,
            clip.framerate,
            clip.duration(),
            clip.looping,
            clip.tracks.len(),
            notes.join(" ")
        );
        if !name.starts_with("viewmodel_") {
            continue;
        }
        let mut csv = String::from("frame,time_s,bone,qx,qy,qz,qw,tx,ty,tz\n");
        let frames = clip.numframes.max(1) as usize;
        for f in 0..=frames {
            let t = if clip.framerate > 0.0 { f as f32 / clip.framerate } else { 0.0 };
            let t = t.min(clip.duration() - 1e-4).max(0.0);
            for (i, track) in clip.tracks.iter().enumerate() {
                if !key_bone(&track.name) {
                    continue;
                }
                let Some(sample) = clip.sample_track(i, t) else { continue };
                let q = sample.rotation.unwrap_or([0.0, 0.0, 0.0, 1.0]);
                let tr = sample.translation.map_or(String::from(",,"), |v| {
                    format!("{:.4},{:.4},{:.4}", v[0], v[1], v[2])
                });
                let _ = writeln!(
                    csv,
                    "{f},{t:.4},{},{:.5},{:.5},{:.5},{:.5},{tr}",
                    track.name, q[0], q[1], q[2], q[3]
                );
            }
        }
        fs::write(out_dir.join("curves").join(format!("{name}.csv")), csv).unwrap();
    }
    fs::write(out_dir.join("xanims.tsv"), index).unwrap();
    eprintln!("weapons={} xanims={}", sink.weapons.len(), names.len());
}
