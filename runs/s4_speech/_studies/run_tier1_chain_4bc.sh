#!/bin/bash
# Stage 4 Tier 1 chain for 4b (ma, ba, om) and 4c (strip configs); the machine-wide lock serializes the solves
cd /home/shyam/projects/echo
export PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore NUMBA_NUM_THREADS=8 S4_THREADS=3 ECHO_WHISPER_THREADS=2
for s in 4b 4c; do
  echo "=== $(date) start $s"
  uv run python -m stages.s4_speech --only $s --skip-studies
  echo "=== $(date) end $s (exit $?)"
done
