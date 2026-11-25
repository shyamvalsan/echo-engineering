"""Lab server: health, static files with Range and no-cache, inputs listing, upload -> job -> contract-valid run
folder, and the refusals (path traversal, dot-paths, oversize, undecodable, missing field)."""

import http.client
import io
import json
import os
import threading
import time
import uuid

import numpy as np
import pytest
import soundfile as sf

from contract_check import check_run_folder
from echo.lab import MAX_UPLOAD, ROOT, Lab, make_server
from echo.scene import FS

os.environ["ECHO_LAB_QUIET"] = "1"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    srv = make_server("127.0.0.1", 0, lab=Lab(runs_root=runs))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _req(srv, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r, data


def _multipart(fields):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for name, val in fields.items():
        out.write(f"--{b}\r\n".encode())
        if isinstance(val, bytes):
            out.write(f'Content-Disposition: form-data; name="{name}"; filename="../../evil name.wav"\r\n'
                      "Content-Type: audio/wav\r\n\r\n".encode())
            out.write(val)
        else:
            out.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}'.encode())
        out.write(b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


def _tone_wav(dur=0.06, f=1800.0, sr=FS):
    t = np.arange(int(dur * sr)) / sr
    b = io.BytesIO()
    sf.write(b, 0.5 * np.sin(2 * np.pi * f * t) * np.hanning(len(t)) ** 0.2, sr, format="WAV")
    return b.getvalue()


def test_health_and_inputs(server):
    r, d = _req(server, "GET", "/api/health")
    j = json.loads(d)
    assert r.status == 200 and j["ok"] is True and j["features"] == ["design", "source_echo"] and j["version"]
    r, d = _req(server, "GET", "/api/inputs")
    j = json.loads(d)
    assert {"name": "clap_0.wav", "url": "/inputs/sources/clap_0.wav"} in j["sources"]
    assert any(t["name"] == "rising_two_note.wav" for t in j["targets"])


def test_static_range_and_cache_headers(server):
    p = ROOT / "inputs" / "sources" / "chirp.wav"
    raw = p.read_bytes()
    r, d = _req(server, "GET", "/inputs/sources/chirp.wav", headers={"Range": "bytes=100-299"})
    assert r.status == 206 and d == raw[100:300]
    assert r.getheader("Content-Range") == f"bytes 100-299/{len(raw)}" and r.getheader("Accept-Ranges") == "bytes"
    r, d = _req(server, "GET", "/inputs/sources/chirp.wav", headers={"Range": "bytes=-10"})
    assert r.status == 206 and d == raw[-10:]
    r, d = _req(server, "GET", "/inputs/sources/chirp.wav", headers={"Range": f"bytes={len(raw) + 5}-"})
    assert r.status == 416
    r, d = _req(server, "GET", "/inputs/sources/chirp.wav")
    assert r.status == 200 and d == raw and r.getheader("Cache-Control") is None
    r, d = _req(server, "GET", "/runs/index.json")
    assert r.status == 200 and r.getheader("Cache-Control") == "no-cache"
    r, _ = _req(server, "GET", "/viewer/")
    assert r.status == 200 and r.getheader("Cache-Control") == "no-cache"


def test_traversal_and_dotpaths_refused(server):
    for path in ("/../../../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/.git/HEAD", "/.cache/tier1.lock",
                 "/viewer/../.git/config", "/api/jobs/..%2f..%2fetc"):
        r, d = _req(server, "GET", path)
        assert r.status == 404, (path, r.status)
        assert b"root:" not in d


def test_upload_refusals(server):
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
    c.putrequest("POST", "/api/design")
    c.putheader("Content-Type", "multipart/form-data; boundary=x")
    c.putheader("Content-Length", str(MAX_UPLOAD + 10 * 2 ** 20))
    c.endheaders()
    r = c.getresponse()
    assert r.status == 413 and "too large" in json.loads(r.read())["error"]
    c.close()
    body, ct = _multipart({"target": b"not audio" * 100})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct})
    assert r.status == 400 and "decodable" in json.loads(d)["error"]
    body, ct = _multipart({"name": "x"})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct})
    assert r.status == 400 and "target" in json.loads(d)["error"]
    body, ct = _multipart({"target": _tone_wav(0.01)})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct})
    assert r.status == 400 and "short" in json.loads(d)["error"]
    r, d = _req(server, "GET", "/api/jobs/doesnotexist")
    assert r.status == 404


def test_upload_design_job(server):
    body, ct = _multipart({"target": _tone_wav(), "name": "test tone", "max_duration_s": "1.0", "tier1": "0"})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct})
    assert r.status == 202
    jid = json.loads(d)["job_id"]
    t0 = time.time()
    while True:
        r, d = _req(server, "GET", f"/api/jobs/{jid}")
        j = json.loads(d)
        assert set(j) >= {"status", "stage", "progress", "message", "run", "warnings"}
        if j["status"] in ("done", "error"):
            break
        assert time.time() - t0 < 300
        time.sleep(0.5)
    assert j["status"] == "done", j
    assert j["run"]["stage"] == "custom" and j["run"]["path"] == f"custom/{j['run']['run_id']}"
    runs = server.lab.runs_root
    d = runs / j["run"]["path"]
    check_run_folder(d)
    assert (d / "ir_tier0.wav").exists()
    assert (runs / "custom" / "_jobs" / f"{jid}.json").exists()
    ups = list((runs / "custom" / "_uploads").iterdir())
    assert [u.name for u in ups] == [f"{jid}.audio"]  # stored under the job id, never the client's file name
    r, d = _req(server, "GET", "/api/jobs")
    assert any(x["job_id"] == jid for x in json.loads(d)["jobs"])
    idx = json.loads((runs / "index.json").read_text())
    assert idx["runs"][0]["path"] == j["run"]["path"]
