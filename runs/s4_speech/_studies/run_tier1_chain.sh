#!/bin/bash
# Stage 4 Tier 1 chain: 4a, 4b (ma, ba, om), 4c; one design solve each (studies reused from _studies/)
cd /home/shyam/projects/echo
export PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore NUMBA_NUM_THREADS=8 S4_THREADS=4 ECHO_WHISPER_THREADS=2
for s in 4a 4b 4c; do
  echo "=== $(date) start $s"
  uv run python -m stages.s4_speech --only $s --skip-studies
  echo "=== $(date) end $s (exit $?)"
done
