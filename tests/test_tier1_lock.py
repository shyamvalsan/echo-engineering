"""The machine-wide Tier 1 lock (stages.common.tier1_lock): a second process blocks until the first releases."""

import subprocess
import sys
import time

from stages.common import tier1_lock, tier1_lock_threads

HOLD = """
import sys, time
from stages.common import tier1_lock
with tier1_lock(path=sys.argv[1], log=lambda *a: print(*a, flush=True)):
    print("HELD", flush=True)
    time.sleep(float(sys.argv[2]))
print("RELEASED", flush=True)
"""

WAIT = """
import sys, time
from stages.common import tier1_lock
t = time.time()
with tier1_lock(path=sys.argv[1], log=lambda *a: print(*a, flush=True), poll_s=0.05, log_every_s=0.5) as w:
    print(f"GOT {time.time() - t:.3f} {w:.3f}", flush=True)
"""


def test_second_process_waits_for_the_first(tmp_path):
    lock = tmp_path / "sub" / "tier1.lock"  # parent dir does not exist yet: the lock creates it
    a = subprocess.Popen([sys.executable, "-c", HOLD, str(lock), "8.0"], stdout=subprocess.PIPE, text=True)
    assert a.stdout.readline().strip() == "HELD"
    b = subprocess.run([sys.executable, "-c", WAIT, str(lock)], capture_output=True, text=True, timeout=60)
    a.wait(timeout=30)
    lines = b.stdout.strip().splitlines()
    got = [ln for ln in lines if ln.startswith("GOT")]
    assert got, b.stdout + b.stderr
    waited = float(got[0].split()[2])
    # A holds for 8 s after printing HELD; B needs a few s to start (imports torch), so it must still wait
    assert 1.0 < waited < 10.0
    assert any(ln.startswith("waiting for Tier 1 lock") for ln in lines)


def test_lock_released_on_exception_and_reentrant_across_calls(tmp_path):
    lock = tmp_path / "tier1.lock"
    try:
        with tier1_lock(path=lock, log=lambda *a: None):
            raise RuntimeError("solver blew up")
    except RuntimeError:
        pass
    t = time.time()
    with tier1_lock(path=lock, log=lambda *a: None) as w:
        assert w < 0.5
    assert time.time() - t < 1.0
    assert 1 <= tier1_lock_threads() <= 8
