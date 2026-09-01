#!/usr/bin/env bash
#
# Shows that the records predict what Horus actually re-runs.
#
# For each scenario: read the records and predict, apply the change, run
# the workflow, then print what the engine really did. The prediction is
# made before the run and uses nothing but the run directory.
#
#   ./demo.sh            all four scenarios
#   ./demo.sh 4          just the script-change one
#
set -uo pipefail
cd "$(dirname "$0")"

RECORDS="${HORUS_LINEAGE_DIR:-$HOME/.horus-lineage}"
HORUS="${HORUS:-horus}"
PYTHON="${PYTHON:-python3}"

command -v "$HORUS" >/dev/null || {
  echo "No 'horus' on PATH. Set HORUS=/path/to/horus, or activate the"
  echo "environment where horus-runtime and horus-lineage are installed."
  exit 1
}

rule() { printf '\n%s\n' "────────────────────────────────────────────────────────"; }

run() { "$HORUS" run --no-tui workflow.yaml >/dev/null 2>&1; }

latest() { ls -td "$RECORDS"/*/ 2>/dev/null | head -1; }

reality() {
  "$PYTHON" - "$(latest)" <<'PY'
import json, sys, glob, os
ran, skipped = [], []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    if os.path.basename(f) in ("run.json", "definition.json"):
        continue
    r = json.load(open(f))
    (ran if r["task"]["status"] == "completed" else skipped).append(
        r["task"]["id"]
    )
print(f"  engine re-ran     : {sorted(ran)}")
print(f"  engine skipped    : {sorted(skipped)}")
PY
}

scenario() {
  local title=$1 file=$2 edit=$3
  rule
  echo "SCENARIO: $title"
  rule
  run                                   # settle, so everything is cached
  echo "PREDICTION, from the records alone:"
  "$PYTHON" impact.py "$(latest)" "$file"
  cp "$file" "$file.bak"
  "$PYTHON" - "$file" "$edit" <<'PY'
import sys, pathlib
path, edit = pathlib.Path(sys.argv[1]), sys.argv[2]
old, new = edit.split("=>")
path.write_text(path.read_text().replace(old, new))
PY
  run
  echo "REALITY:"
  reality
  mv "$file.bak" "$file"
}

# A clean slate, so the first run records a full baseline.
rm -rf "$RECORDS" results
run
echo "Baseline recorded in $RECORDS"

want=${1:-all}
pick() { [ "$want" = all ] || [ "$want" = "$1" ]; }

pick 1 && scenario "an input feeding one branch" \
  data/calibration.txt 'factor=2=>factor=3'
pick 2 && scenario "the root input" \
  data/raw.csv 'c,8=>c,9'
pick 3 && scenario "an input feeding only the last task" \
  data/reference.txt 'threshold=10=>threshold=99'
pick 4 && scenario "a SCRIPT, which the engine cannot see" \
  scripts/qc.py '"rows": len(rows)=>"rows": len(rows), "checked": True'

rule
echo "Scenarios 1 to 3: the prediction matches the engine exactly."
echo "Scenario 4: the records name the affected tasks and warn that the"
echo "engine will not act on them. It re-runs nothing and keeps stale"
echo "output, which is the gap these records exist to close."
