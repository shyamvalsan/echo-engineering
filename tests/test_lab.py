"""Lab server: health, static files with Range and no-cache, inputs listing, upload -> job -> contract-valid run
folder, and the refusals (path traversal, dot-paths, oversize, undecodable, missing field), plus the hardening:
custom header and Origin on POST, Host check (DNS rebinding), negative Content-Length, decompression bomb, queue cap,
hidden _uploads/_jobs, multi-range -> 200."""

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
LAB = {"X-Echo-Lab": "1"}  # required on POST


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
    c.putheader("X-Echo-Lab", "1")
    c.putheader("Content-Length", str(MAX_UPLOAD + 10 * 2 ** 20))
    c.endheaders()
    r = c.getresponse()
    assert r.status == 413 and "too large" in json.loads(r.read())["error"]
    c.close()
    body, ct = _multipart({"target": b"not audio" * 100})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, **LAB})
    assert r.status == 400 and "decodable" in json.loads(d)["error"]
    body, ct = _multipart({"name": "x"})
    same = {"Origin": f"http://127.0.0.1:{server.server_address[1]}"}  # the viewer's own origin passes
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, **LAB, **same})
    assert r.status == 400 and "target" in json.loads(d)["error"]
    body, ct = _multipart({"target": _tone_wav(0.01)})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, **LAB})
    assert r.status == 400 and "short" in json.loads(d)["error"]
    r, d = _req(server, "GET", "/api/jobs/doesnotexist")
    assert r.status == 404


def test_upload_design_job(server):
    body, ct = _multipart({"target": _tone_wav(), "name": "test tone", "max_duration_s": "1.0", "tier1": "0"})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, **LAB})
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


# ---------------------------------------------------------------------------------------------------- hardening
def _raw(srv, lines, body=b""):
    """Send a hand-written request (exact headers, incl. Host) and return (status, json body or None)."""
    import socket

    s = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=30)
    s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
    s.shutdown(socket.SHUT_WR)
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    s.close()
    head, _, rest = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    try:
        return status, json.loads(rest)
    except ValueError:
        return status, None


def test_post_needs_lab_header_and_same_origin(server):
    body, ct = _multipart({"target": _tone_wav(), "name": "x"})
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct})  # no X-Echo-Lab
    assert r.status == 403 and "X-Echo-Lab" in json.loads(d)["error"]
    # a cross-origin "simple" form POST as any web page could send it (no custom header possible without preflight)
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, "Origin": "http://evil.example"})
    assert r.status == 403 and "cross-origin" in json.loads(d)["error"]
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, "Origin": "http://evil.example", **LAB})
    assert r.status == 403
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, "Origin": "null", **LAB})
    assert r.status == 403
    r, d = _req(server, "POST", "/api/design", body, {"Content-Type": ct, "Origin": "http://127.0.0.1:1", **LAB})
    assert r.status == 403  # another local port is another origin
    # the preflight a browser would send first is never answered with CORS permission
    r, _ = _req(server, "OPTIONS", "/api/design", headers={"Origin": "http://evil.example",
                                                            "Access-Control-Request-Method": "POST"})
    assert r.status >= 400 and r.getheader("Access-Control-Allow-Origin") is None
    assert server.lab.queued() == 0 and not any(j["name"] == "x" for j in server.lab.recent())


def test_host_header_must_be_local(server):
    port = server.server_address[1]
    for host in (f"127.0.0.1:{port}", f"localhost:{port}", "localhost", f"[::1]:{port}"):
        st, j = _raw(server, ["GET /api/health HTTP/1.1", f"Host: {host}", "Connection: close"])
        assert st == 200 and j["ok"], host
    for host in ("evil.example", f"evil.example:{port}", "127.0.0.1.evil.example", "localhost.evil.example:80"):
        st, j = _raw(server, ["GET /runs/index.json HTTP/1.1", f"Host: {host}", "Connection: close"])
        assert st == 403 and "Host not allowed" in j["error"], host
        st, _ = _raw(server, ["POST /api/design HTTP/1.1", f"Host: {host}", "X-Echo-Lab: 1", "Content-Length: 0",
                              "Connection: close"])
        assert st == 403, host


def test_negative_content_length_refused(server):
    st, j = _raw(server, ["POST /api/design HTTP/1.1", f"Host: 127.0.0.1:{server.server_address[1]}", "X-Echo-Lab: 1",
                          "Content-Type: multipart/form-data; boundary=x", "Content-Length: -1"], b"x" * 100)
    assert st == 400 and "Content-Length" in j["error"]
    st, j = _raw(server, ["POST /api/design HTTP/1.1", f"Host: 127.0.0.1:{server.server_address[1]}", "X-Echo-Lab: 1",
                          "Content-Type: multipart/form-data; boundary=x", "Content-Length: abc"])
    assert st == 411


def _bomb_flac(hours=1.0, sr=8000):
    """A tone burst followed by `hours` of digital silence, FLAC: tiny file, huge decoded size."""
    b = io.BytesIO()
    t = np.arange(int(0.08 * sr)) / sr
    with sf.SoundFile(b, "w", samplerate=sr, channels=1, format="FLAC", subtype="PCM_16") as f:
        f.write(0.5 * np.sin(2 * np.pi * 1500 * t))
        z = np.zeros(sr * 600)
        for _ in range(int(hours * 6)):
            f.write(z)
    return b.getvalue()


def test_decompression_bomb_is_truncated_without_large_memory():
    import tracemalloc

    from stages.custom import MAX_READ_S, load_audio

    data = _bomb_flac(1.0)
    assert len(data) < 2 * 2 ** 20  # 1 h of audio in well under 2 MB (decoded: 230 MB as float64)
    notes = []
    tracemalloc.start()
    x, sr = load_audio(data, notes)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert sr == 8000 and len(x) == int(MAX_READ_S * sr)
    assert peak < 30e6, peak  # 30 s at 8 kHz is 1.9 MB of float64; the whole hour would be 230 MB
    assert notes and "only the first" in notes[0]


@pytest.fixture()
def slow_server(tmp_path):
    """A lab whose 'designer' blocks until released, to fill the queue without running real designs."""
    gate = threading.Event()

    def design(path, **kw):
        gate.wait(60)
        raise RuntimeError("test design released")

    srv = make_server("127.0.0.1", 0, lab=Lab(runs_root=tmp_path / "runs", design_fn=design))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv
    gate.set()
    srv.shutdown()
    srv.server_close()


def test_queue_cap_and_bomb_upload(slow_server):
    from echo.lab import MAX_QUEUED

    body, ct = _multipart({"target": _bomb_flac(0.5), "name": "bomb"})
    r, d = _req(slow_server, "POST", "/api/design", body, {"Content-Type": ct, **LAB})
    assert r.status == 202, d  # truncated to the first 30 s at decode, then trimmed to the tone: a valid target
    t0 = time.time()
    while slow_server.lab.get(json.loads(d)["job_id"])["status"] != "running":
        assert time.time() - t0 < 10
        time.sleep(0.05)
    body, ct = _multipart({"target": _tone_wav(), "name": "q"})
    for _ in range(MAX_QUEUED):
        r, d = _req(slow_server, "POST", "/api/design", body, {"Content-Type": ct, **LAB})
        assert r.status == 202, d
    r, d = _req(slow_server, "POST", "/api/design", body, {"Content-Type": ct, **LAB})
    assert r.status == 429 and "waiting" in json.loads(d)["error"]
    assert slow_server.lab.queued() == MAX_QUEUED


def test_uploads_jobs_and_dot_entries_hidden(slow_server):
    runs = slow_server.lab.runs_root
    (runs / "custom" / "_uploads").mkdir(parents=True, exist_ok=True)
    (runs / "custom" / "_uploads" / "x.audio").write_bytes(b"secret")
    (runs / "custom" / "_jobs").mkdir(parents=True, exist_ok=True)
    (runs / "custom" / "_jobs" / "x.json").write_text("{}")
    (runs / "custom" / ".hidden").write_text("h")
    (runs / "custom" / "visible.txt").write_text("v")
    srv = make_server("127.0.0.1", 0, root=runs, lab=slow_server.lab)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        for path in ("/custom/_uploads/x.audio", "/custom/_uploads/", "/custom/_jobs/x.json", "/custom/_jobs/",
                     "/custom/.hidden", "/custom/%5Fuploads/x.audio"):
            r, d = _req(srv, "GET", path)
            assert r.status == 404 and b"secret" not in d, path
        r, d = _req(srv, "GET", "/custom/")
        assert r.status == 200 and b"visible.txt" in d
        assert b"_uploads" not in d and b"_jobs" not in d and b".hidden" not in d
    finally:
        srv.shutdown()
        srv.server_close()


def test_multi_range_gets_whole_file(server):
    raw = (ROOT / "inputs" / "sources" / "chirp.wav").read_bytes()
    r, d = _req(server, "GET", "/inputs/sources/chirp.wav", headers={"Range": "bytes=0-9,20-29"})
    assert r.status == 200 and d == raw and r.getheader("Content-Range") is None
