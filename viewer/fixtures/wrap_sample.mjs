// Wrap the real Tier 1 field sample (runs/_samples/: field.webm, field.json, scene.json) as a minimal
// run folder in the fixture set, so the viewer loads it through the normal run code path.
//   node viewer/fixtures/wrap_sample.mjs      (from the repo root, after make_fixtures.mjs)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "..", "runs", "_samples");
const REL = "sample_field/real-tier1-sample";
const DIR = path.join(HERE, "runs", REL);

const field = JSON.parse(fs.readFileSync(path.join(SRC, "field.json")));
const scene = JSON.parse(fs.readFileSync(path.join(SRC, "scene.json")));
fs.rmSync(DIR, { recursive: true, force: true }); fs.mkdirSync(DIR, { recursive: true });
fs.copyFileSync(path.join(SRC, "field.webm"), path.join(DIR, "field.webm"));
fs.writeFileSync(path.join(DIR, "scene.json"), JSON.stringify(scene));
const tEnd = field.t0_s + field.n_frames * field.sim_seconds_per_frame;
const created = fs.statSync(path.join(SRC, "field.json")).mtime.toISOString();
fs.writeFileSync(path.join(DIR, "manifest.json"), JSON.stringify({
  run_id: "real-tier1-sample", stage: "sample_field", title: "Real Tier 1 field sample (viewer wrapper)", created,
  seed: null, git_commit: null, status: "tier0_only", verified: false, fs: 16000, c: scene.c ?? 343,
  duration_s: Math.round(tEnd * 1e6) / 1e6, t_direct_s: 0.3 / (scene.c ?? 343), command: "node viewer/fixtures/wrap_sample.mjs",
  solver: { tier1: "none", device: null, dx: null, dt: null, grid: null, f_lo: null, f_max: null, ppw: null, wall_s: null },
  field, audio: { echo_gain_db: { tier0: null, tier1: null }, as_heard_echo_level_db: null },
  notes: "Wraps runs/_samples (real full-wave field video and its scene) for viewer checks. No audio, profile or metrics.",
}));
const idxPath = path.join(HERE, "runs", "index.json"), idx = JSON.parse(fs.readFileSync(idxPath));
idx.runs = idx.runs.filter((r) => r.path !== REL);
idx.runs.push({ stage: "sample_field", run_id: "real-tier1-sample", path: REL, title: "Real Tier 1 field sample (viewer wrapper)", created, status: "tier0_only", passed: false, verified: false });
fs.writeFileSync(idxPath, JSON.stringify(idx));
console.log(`wrapped ${SRC} -> ${DIR}`);
