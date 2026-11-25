"""Local lab server: the repo's static files (viewer, explainer, runs, inputs) plus a small JSON API for custom designs.

    uv run python -m echo.lab [--port 8000] [--host 127.0.0.1]

Static: serves the repo root like `python -m http.server`, plus HTTP Range (206 / 416) for every file, and
`Cache-Control: no-cache` on .js/.css/.json/.html. Paths with a dot-segment (.git, .cache, ...) are not served.

API (same origin, JSON):
    GET  /api/health          {"ok": true, "version": "<git short sha>", "features": ["design", "source_echo"]}
    GET  /api/inputs          {"targets": [{"name", "url"}], "sources": [{"name", "url"}]}  (inputs/targets, inputs/sources)
    POST /api/design          multipart: target (audio file), name?, max_duration_s? (1.0), tier1? ("0"/"1")
                              -> 202 {"job_id"} | 400 {"error"} | 413 {"error"}
    GET  /api/jobs            {"jobs": [job, ...]} newest first (at most 50)
    GET  /api/jobs/<job_id>   {"job_id", "status": queued|running|done|error, "stage", "progress", "message",
                               "run": {"stage": "custom", "run_id", "path": "custom/<run_id>"} | null, "warnings": [...]}

Jobs run one at a time in a worker thread (stages.custom.design_custom); state is in memory and mirrored to
runs/custom/_jobs/<job_id>.json. Uploads are stored as runs/custom/_uploads/<job_id>.audio (the client's file name is
never used as a path), limited to 20 MB, and accepted only if soundfile/librosa decode them and the custom designer's
input checks pass. No shell is ever invoked with user input.
"""

from __future__ import annotations

import argparse
import email.parser
import email.policy
import json
import os
import queue
import re
import secrets
import threading
import traceback
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from echo import export

ROOT = export.ROOT
MAX_UPLOAD = 20 * 1024 * 1024
MAX_BODY = MAX_UPLOAD + 256 * 1024  # form fields and multipart framing
NO_CACHE_EXT = {".js", ".mjs", ".css", ".json", ".html", ".htm"}
AUDIO_EXT = {".wav", ".flac", ".ogg", ".mp3"}
JOB_ID_RE = re.compile(r"^[0-9a-z-]{6,40}$")
FEATURES = ["design", "source_echo"]
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class Lab:
    """Job queue + worker for custom designs (one at a time)."""

    def __init__(self, runs_root=None, inputs_dir=None, design_fn=None):
        self.runs_root = Path(runs_root or export.RUNS)
        self.custom_dir = self.runs_root / "custom"
        self.jobs_dir = self.custom_dir / "_jobs"
        self.uploads_dir = self.custom_dir / "_uploads"
        self.inputs_dir = Path(inputs_dir or ROOT / "inputs")
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.q: queue.Queue = queue.Queue()
        self._design = design_fn
        self.version = export.git_commit()
        self._load_mirrors()
        self.worker = threading.Thread(target=self._work, name="lab-worker", daemon=True)
        self.worker.start()

    # ---- jobs
    def _load_mirrors(self):
        """Jobs of earlier server sessions (from their mirrors); unfinished ones are marked as interrupted."""
        for p in sorted(self.jobs_dir.glob("*.json")) if self.jobs_dir.is_dir() else []:
            try:
                j = json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                continue
            if not JOB_ID_RE.match(str(j.get("job_id", ""))):
                continue
            if j.get("status") in ("queued", "running"):
                j.update(status="error", stage="error", message="interrupted: the lab server was restarted")
            self.jobs[j["job_id"]] = j

    def _mirror(self, job):
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.jobs_dir / f".{job['job_id']}.tmp"
        tmp.write_text(json.dumps(export.clean_json(job), indent=1))
        tmp.replace(self.jobs_dir / f"{job['job_id']}.json")

    def update(self, job_id, **kw):
        with self.lock:
            job = self.jobs[job_id]
            job.update(kw)
            job["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
            snap = dict(job)
        self._mirror(snap)
        return snap

    def submit(self, data: bytes, name: str, max_duration_s: float, tier1: bool) -> str:
        job_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        path = self.uploads_dir / f"{job_id}.audio"
        path.write_bytes(data)
        job = {"job_id": job_id, "status": "queued", "stage": "queued", "progress": 0.0, "message": "",
               "run": None, "warnings": [], "name": name, "max_duration_s": max_duration_s, "tier1": tier1,
               "created": datetime.now().astimezone().isoformat(timespec="seconds"), "timings": None}
        with self.lock:
            self.jobs[job_id] = job
        self._mirror(job)
        self.q.put((job_id, path))
        return job_id

    def get(self, job_id):
        with self.lock:
            j = self.jobs.get(job_id)
            return None if j is None else dict(j)

    def recent(self, n=50):
        with self.lock:
            js = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)[:n]
            return [dict(j) for j in js]

    def _work(self):
        while True:
            job_id, path = self.q.get()
            job = self.get(job_id)
            try:
                self.update(job_id, status="running", stage="starting", progress=0.01)
                design = self._design
                if design is None:
                    from stages.custom import design_custom as design
                r = design(path, name=job["name"], max_duration_s=job["max_duration_s"], tier1=job["tier1"],
                           progress=lambda s, f: self.update(job_id, stage=s, progress=round(float(f), 3)),
                           runs_root=self.runs_root,
                           command=f"POST /api/design (job {job_id}; upload stored as "
                                   f"{path.relative_to(self.runs_root.parent) if self.runs_root.parent in path.parents else path.name})")
                rd = Path(r["run_dir"])
                t1 = r.get("tier1") or {}
                msg = "fast-model design written"
                if t1.get("status") == "done":
                    msg = "fast-model design and full-wave run written (status final)"
                elif t1.get("status") in ("refused", "error"):
                    msg = f"fast-model design written; {t1.get('message')}"
                self.update(job_id, status="done", stage="done", progress=1.0, message=msg,
                            run={"stage": "custom", "run_id": rd.name, "path": f"custom/{rd.name}"},
                            warnings=list(r.get("warnings") or []), timings=r.get("timings"),
                            classification=r.get("classification"), tier1_result=t1)
            except Exception as exc:  # noqa: BLE001 - the job reports it
                from stages.custom import CustomInputError

                user = isinstance(exc, CustomInputError)
                self.update(job_id, status="error", stage="error", message=str(exc) if user else
                            f"{type(exc).__name__}: {exc}", traceback=None if user else traceback.format_exc()[-2000:])
            finally:
                self.q.task_done()

    # ---- inputs
    def inputs(self):
        out = {}
        for kind in ("targets", "sources"):
            d = self.inputs_dir / kind
            files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT) if d.is_dir() else []
            out[kind] = [{"name": p.name, "url": f"/inputs/{kind}/{p.name}"} for p in files]
        return out


def parse_multipart(content_type: str, body: bytes) -> dict:
    """{field name: bytes} from a multipart/form-data body (stdlib email parser)."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    if not msg.is_multipart():
        raise ValueError("expected multipart/form-data")
    out = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            out[str(name)] = part.get_payload(decode=True) or b""
    return out


class LabHandler(SimpleHTTPRequestHandler):
    server_version = "EchoLab/1"
    lab: Lab = None  # set by make_server
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript",
                      ".webm": "video/webm", ".wav": "audio/wav", ".json": "application/json",
                      ".wasm": "application/wasm", ".md": "text/markdown; charset=utf-8"}

    def log_message(self, fmt, *args):
        if os.environ.get("ECHO_LAB_QUIET") != "1":
            super().log_message(fmt, *args)

    # ---- helpers
    def _json(self, code, obj):
        body = json.dumps(export.clean_json(obj)).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def end_headers(self):
        if getattr(self, "_static_ext", None) in NO_CACHE_EXT:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    # ---- routing
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            return self._api_get(path)
        return self._static()

    def do_HEAD(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            return self._api_get(path)
        return self._static()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path != "/api/design":
            return self._json(404, {"error": "not found"})
        return self._api_design()

    def _api_get(self, path):
        lab = self.lab
        if path == "/api/health":
            return self._json(200, {"ok": True, "version": lab.version, "features": FEATURES})
        if path == "/api/inputs":
            return self._json(200, lab.inputs())
        if path in ("/api/jobs", "/api/jobs/"):
            return self._json(200, {"jobs": [_public(j) for j in lab.recent()]})
        if path.startswith("/api/jobs/"):
            jid = path[len("/api/jobs/"):]
            j = lab.get(jid) if JOB_ID_RE.match(jid) else None
            return self._json(200, _public(j)) if j else self._json(404, {"error": "unknown job"})
        return self._json(404, {"error": "not found"})

    def _api_design(self):
        from stages.custom import CustomInputError, load_audio, prepare_target

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            return self._json(411, {"error": "Content-Length required"})
        if length > MAX_BODY:
            self.close_connection = True  # the body is not read
            return self._json(413, {"error": f"upload too large ({length / 1e6:.1f} MB; limit {MAX_UPLOAD // 2**20} MB)"})
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self.close_connection = True
            return self._json(400, {"error": "expected multipart/form-data"})
        body = self.rfile.read(length)
        try:
            form = parse_multipart(ctype, body)
        except Exception as exc:  # noqa: BLE001
            return self._json(400, {"error": f"bad multipart body: {exc}"})
        data = form.get("target")
        if not data:
            return self._json(400, {"error": "missing file field 'target'"})
        if len(data) > MAX_UPLOAD:
            return self._json(413, {"error": f"upload too large (limit {MAX_UPLOAD // 2**20} MB)"})
        name = (form.get("name") or b"").decode("utf-8", "replace").strip()[:80] or "custom"
        name = re.sub(r"[\x00-\x1f\x7f]", " ", name)
        try:
            mdur = float((form.get("max_duration_s") or b"1.0").decode() or 1.0)
            if not (0 < mdur < 1e3):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "max_duration_s must be a positive number"})
        t1 = (form.get("tier1") or b"0").decode().strip()
        if t1 not in ("0", "1", "true", "false", ""):
            return self._json(400, {"error": "tier1 must be 0 or 1"})
        try:  # validate now so obvious rejections come back immediately
            x, sr = load_audio(data)
            prepare_target(x, sr, mdur)
        except CustomInputError as exc:
            return self._json(400, {"error": str(exc)})
        jid = self.lab.submit(data, name, mdur, t1 in ("1", "true"))
        return self._json(202, {"job_id": jid})

    # ---- static files with Range
    def _static(self):
        raw = unquote(urlsplit(self.path).path)
        if any(seg.startswith(".") for seg in raw.split("/") if seg):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        fpath = Path(self.translate_path(self.path))
        try:
            fpath.resolve().relative_to(Path(self.directory).resolve())
        except (ValueError, OSError):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        self._static_ext = fpath.suffix.lower() if not fpath.is_dir() else ".html"
        if fpath.is_dir() or not fpath.is_file():
            f = self.send_head()  # directory index / redirect / 404, as http.server
            if f:
                try:
                    if self.command != "HEAD":
                        self.copyfile(f, self.wfile)
                finally:
                    f.close()
            return
        size = fpath.stat().st_size
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial_ = False
        if rng:
            m = RANGE_RE.match(rng.strip())
            ok = m is not None and (m.group(1) or m.group(2))
            if ok:
                a, b = m.group(1), m.group(2)
                if a == "":  # suffix range: last b bytes
                    n = int(b)
                    start, end = max(0, size - n), size - 1
                    ok = n > 0
                else:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
                    ok = start < size and start <= end
            if not ok:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            partial_ = True
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial_ else HTTPStatus.OK)
        self.send_header("Content-Type", self.guess_type(str(fpath)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        if partial_:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Last-Modified", self.date_time_string(int(fpath.stat().st_mtime)))
        self.end_headers()
        if self.command == "HEAD" or size == 0:
            return
        with open(fpath, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)


def _public(job):
    if job is None:
        return None
    keys = ("job_id", "status", "stage", "progress", "message", "run", "warnings", "name", "created", "updated",
            "tier1", "timings", "classification", "tier1_result")
    return {k: job.get(k) for k in keys if k in job}


def make_server(host="127.0.0.1", port=8000, root=None, lab=None):
    """ThreadingHTTPServer bound to (host, port) serving `root` (default the repo root). Returns the server; its
    `lab` attribute is the job manager."""
    lab = lab or Lab()
    handler = type("BoundLabHandler", (LabHandler,), {"lab": lab})
    srv = ThreadingHTTPServer((host, port), partial(handler, directory=str(root or ROOT)))
    srv.daemon_threads = True
    srv.lab = lab
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description="Composed Echo lab server (static files + design API)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1: this machine only)")
    a = ap.parse_args(argv)
    srv = make_server(a.host, a.port)
    print(f"Composed Echo lab on http://{a.host}:{srv.server_address[1]}/viewer/  (version {srv.lab.version}; "
          f"API /api/health; Ctrl+C to stop)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
