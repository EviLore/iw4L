//! Reference export of first-person weapon clips, posed exactly as IW4L poses them, for animation study.
//!
//! cargo run --profile play -p asset_game --example dump_fpv_clips -- <out_dir> <hands model> <gun model> \
//!     <gun part bones, comma separated> <clip filter> <zone.ff>...
//!
//! Builds the DObj the game draws (hands, with the gun attached at tag_weapon), then for every clip whose name
//! contains the filter evaluates calc_anim + compose at every frame. Writes:
//! - rig.json: every bone (name, parent, rest-pose world matrix) and the hands and gun meshes in that rest pose,
//!   with per-vertex bone indices and weights (gun surfaces limited to the listed part bones, so no attachments).
//! - clips/<clip>.json: frame rate, frame count, notetracks and each frame's world matrix for every bone.
//! - hands.tsv: per clip and frame, each wrist and tag_weapon relative to j_gun and tag_view (inches, degrees).
//!
//! Matrices are column-major, inches, IW4 axes (X forward, Y left, Z up). Output stays under iw4l-artifacts/
//! (gitignored): it is game data and is never committed.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::fs;
use std::path::PathBuf;

use asset_anim::{AssetNamespace, XAnimBuild};
use asset_model::{ModelSkel, capture_xmodel_skel};
use asset_transport::{ZoneMemory, open_zone_shared};
use bevy::math::{EulerRot, Mat4, Vec3};
use fastfile_iw4::{
    AssetLinkSink, AssetSink, AssetType, Ptr, ScriptStrings, XAnimPartsGeometry, ZoneStream,
    load_asset_at_observed, load_zone,
};
use xmodel_runtime::{AnimInstance, Attach, DObj};

struct Sink {
    strings: ScriptStrings,
    wanted: Vec<String>,
    models: HashMap<String, ModelSkel>,
    xanims: XAnimBuild,
}

impl AssetSink for Sink {
    fn set_script_strings(&mut self, strings: ScriptStrings) {
        self.strings = strings;
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
        if ty != AssetType::XModel {
            return Ok(());
        }
        let Some(geometry) = s.xmodel() else { return Ok(()) };
        let Some(name) = geometry.name.and_then(|p| s.cstr(p).ok()) else { return Ok(()) };
        if self.wanted.iter().any(|w| w == name) && !self.models.contains_key(name) {
            if let Some(skel) = capture_xmodel_skel(s, &self.strings, geometry, None) {
                self.models.insert(name.to_owned(), skel);
            }
        }
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

fn mat(m: &Mat4) -> Vec<f32> {
    m.to_cols_array().iter().map(|v| (v * 1e5).round() / 1e5).collect()
}

/// A mesh posed into the composed rest pose, keeping only faces whose vertices all sit on `keep` bones.
fn mesh_json(skel: &ModelSkel, base: usize, rest: &[Mat4], dobj: &DObj, keep: Option<&[&str]>) -> serde_json::Value {
    let lod0 = skel.surfaces_for_lod(0);
    let primary = |v: usize| skel.vert_skin.get(v).map(|s| s.bones[0] as usize).unwrap_or(0);
    let allowed = |v: usize| {
        keep.is_none_or(|k| k.contains(&skel.bone_names.get(primary(v)).map(String::as_str).unwrap_or("")))
    };
    let mut remap = HashMap::new();
    let (mut verts, mut weights, mut faces) = (Vec::new(), Vec::new(), Vec::new());
    for (surface, &(start, count)) in skel.surface_index_ranges.iter().enumerate() {
        if !lod0.contains(&surface) {
            continue;
        }
        for tri in skel.indices[start..start + count].chunks_exact(3) {
            if !tri.iter().all(|&i| allowed(i as usize)) {
                continue;
            }
            let mut face = Vec::with_capacity(3);
            for &i in tri {
                let i = i as usize;
                let next = remap.len();
                let id = *remap.entry(i).or_insert_with(|| {
                    let p = Vec3::from_array(skel.positions[i]);
                    let skin = skel.vert_skin.get(i).copied();
                    let (bones, ws) = match skin {
                        Some(s) => (s.bones, s.weights),
                        None => ([0; 4], [1.0, 0.0, 0.0, 0.0]),
                    };
                    let mut posed = Vec3::ZERO;
                    let mut out_b = Vec::new();
                    let mut out_w = Vec::new();
                    for k in 0..4 {
                        if ws[k] <= 0.0 {
                            continue;
                        }
                        let g = base + bones[k] as usize;
                        posed += (rest[g] * dobj.bones[g].bind_world.inverse()).transform_point3(p) * ws[k];
                        out_b.push(g);
                        out_w.push((ws[k] * 1e4).round() / 1e4);
                    }
                    verts.push([posed.x, posed.y, posed.z]);
                    weights.push(serde_json::json!([out_b, out_w]));
                    next
                });
                face.push(id);
            }
            faces.push(face);
        }
    }
    serde_json::json!({ "verts": verts, "weights": weights, "faces": faces })
}

fn relative(world: &[Mat4], of: usize, to: usize) -> (Vec3, Vec3) {
    let m = world[to].inverse() * world[of];
    let (_, r, t) = m.to_scale_rotation_translation();
    let (x, y, z) = r.to_euler(EulerRot::ZYX);
    (t, Vec3::new(z.to_degrees(), y.to_degrees(), x.to_degrees()))
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [out_dir, hands, gun, parts, filter, zones @ ..] = args.as_slice() else {
        panic!("usage: <out_dir> <hands> <gun> <gun part bones> <clip filter> <zone.ff>...");
    };
    let out = PathBuf::from(out_dir);
    fs::create_dir_all(out.join("clips")).unwrap();
    let mut xanims = XAnimBuild::default();
    xanims.set_capture_ns(AssetNamespace::Iw4);
    let mut sink = Sink {
        strings: ScriptStrings::default(),
        wanted: vec![hands.clone(), gun.clone()],
        models: HashMap::new(),
        xanims,
    };
    for zone in zones {
        let image = open_zone_shared(zone).unwrap_or_else(|e| panic!("{zone}: {e}"));
        let header = image.header().expect("zone header");
        let mut memory = ZoneMemory::for_header(&header);
        let mut stream = memory.stream(&image.bytes).expect("zone stream");
        if let Err(e) = load_zone(&mut stream, &mut sink) {
            eprintln!("{zone}: stopped: {e:?}");
        }
    }
    let hands_skel = sink.models.get(hands).unwrap_or_else(|| panic!("no model {hands}"));
    let gun_skel = sink.models.get(gun).unwrap_or_else(|| panic!("no model {gun}"));
    let dobj = DObj::build(&[
        (hands_skel.pose.as_ref().expect("hands pose"), None),
        (
            gun_skel.pose.as_ref().expect("gun pose"),
            Some(Attach { parent_model: 0, tag: "tag_weapon".into() }),
        ),
    ])
    .expect("dobj");
    let gun_base = hands_skel.bone_names.len();
    let rest = dobj.compose(&dobj.bind_locals(), Mat4::IDENTITY);
    let part_bones: Vec<&str> = parts.split(',').collect();
    let rig = serde_json::json!({
        "hands": hands, "gun": gun, "gun_parts": part_bones,
        "bones": dobj.bones.iter().enumerate().map(|(i, b)| serde_json::json!({
            "name": b.name, "parent": b.parent, "model": b.model, "rest": mat(&rest[i]),
        })).collect::<Vec<_>>(),
        "meshes": {
            "hands": mesh_json(hands_skel, 0, &rest, &dobj, None),
            "gun": mesh_json(gun_skel, gun_base, &rest, &dobj, Some(&part_bones)),
        },
    });
    fs::write(out.join("rig.json"), serde_json::to_string(&rig).unwrap()).unwrap();

    let find = |n: &str| dobj.find(n).unwrap_or_else(|| panic!("no bone {n}"));
    let (j_gun, tag_view, tag_weapon) = (find("j_gun"), find("tag_view"), find("tag_weapon"));
    let (wrist_ri, wrist_le) = (find("j_wrist_ri"), find("j_wrist_le"));
    let mut table = String::from(
        "clip\tframe\ttime_s\tpart\trel_to\tx_in\ty_in\tz_in\tyaw_deg\tpitch_deg\troll_deg\n",
    );
    let all = dobj.all_parts();
    let mut names: Vec<String> = sink
        .xanims
        .names()
        .filter(|n| n.to_ascii_lowercase().contains(&filter.to_ascii_lowercase()))
        .map(str::to_owned)
        .collect();
    names.sort();
    // ADS up/down are additive single-track layers the game scrubs over the base pose by aim fraction; pose
    // them over the first frame of the weapon's idle so the export shows the hands as the player sees them.
    let idle_name = names.iter().find(|n| n.to_ascii_lowercase().ends_with("_idle")).cloned();
    let idle = idle_name.as_deref().and_then(|n| sink.xanims.decode(AssetNamespace::Iw4, n));
    let idle_tracks = idle.as_ref().map(|c| dobj.tracks_for(c));
    let mut additive_clips = Vec::new();
    for name in &names {
        let Some(clip) = sink.xanims.decode(AssetNamespace::Iw4, name) else { continue };
        let tracks = dobj.tracks_for(&clip);
        let additive = clip.tracks.len() <= 4 && idle.is_some();
        if additive {
            additive_clips.push(serde_json::json!([name, clip.tracks.iter().map(|t| &t.name).collect::<Vec<_>>()]));
        }
        let mut frames = Vec::new();
        for f in 0..=clip.numframes as usize {
            let time = if clip.framerate > 0.0 { f as f32 / clip.framerate } else { 0.0 };
            let mut locals = if additive {
                let base = AnimInstance {
                    clip: idle.as_ref().unwrap(),
                    tracks: idle_tracks.as_ref().unwrap(),
                    time: 0.0,
                    weight: 1.0,
                    parts: None,
                };
                let mut locals = dobj.calc_anim(&[base], &all);
                for (track, bone) in tracks.iter().enumerate() {
                    let (Some(bone), Some(sample)) = (*bone, clip.sample_track(track, time)) else { continue };
                    let l = &mut locals[bone];
                    let (r, t) = anim_iw4::apply_additive(
                        l.rotation,
                        l.translation,
                        sample.rotation.unwrap_or([0.0, 0.0, 0.0, 1.0]),
                        sample.translation.unwrap_or([0.0; 3]),
                        1.0,
                    );
                    l.rotation = r;
                    l.translation = t;
                }
                locals
            } else {
                let anim = AnimInstance { clip: &clip, tracks: &tracks, time, weight: 1.0, parts: None };
                dobj.calc_anim(&[anim], &all)
            };
            dobj.apply_duplicates(&mut locals);
            let world = dobj.compose(&locals, Mat4::IDENTITY);
            for (part, of, to) in [
                ("wrist_ri", wrist_ri, j_gun),
                ("wrist_le", wrist_le, j_gun),
                ("gun", tag_weapon, tag_view),
                ("wrist_ri", wrist_ri, tag_view),
                ("wrist_le", wrist_le, tag_view),
            ] {
                let (t, r) = relative(&world, of, to);
                let to_name = &dobj.bones[to].name;
                let _ = writeln!(
                    table,
                    "{name}\t{f}\t{time:.4}\t{part}\t{to_name}\t{:.3}\t{:.3}\t{:.3}\t{:.2}\t{:.2}\t{:.2}",
                    t.x, t.y, t.z, r.x, r.y, r.z
                );
            }
            frames.push(world.iter().map(mat).collect::<Vec<_>>());
        }
        let json = serde_json::json!({
            "name": name, "fps": clip.framerate, "numframes": clip.numframes, "looping": clip.looping,
            "duration": clip.duration(),
            "notetracks": clip.notifies.iter().map(|n| serde_json::json!([n.name, n.time])).collect::<Vec<_>>(),
            "frames": frames,
        });
        fs::write(out.join("clips").join(format!("{name}.json")), serde_json::to_string(&json).unwrap())
            .unwrap();
    }
    fs::write(out.join("hands.tsv"), table).unwrap();
    fs::write(out.join("additive.json"), serde_json::to_string(&additive_clips).unwrap()).unwrap();
    eprintln!("bones={} clips={}", dobj.bones.len(), names.len());
}
