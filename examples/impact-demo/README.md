# Impact demo

Checks the premise the record format rests on: that the records predict
what Horus will actually re-run when something changes.

Each scenario reads a run directory, predicts which tasks a change
reaches, then applies the change and runs the workflow so the prediction
can be compared against what the engine really did. The prediction is made
first, and uses nothing but the records.

## Run it

From an environment with `horus-runtime` and `horus-lineage` installed:

```bash
./demo.sh
```

One scenario at a time:

```bash
./demo.sh 4
```

If `horus` is not on your `PATH`, point at it directly:

```bash
HORUS=/path/to/.venv/bin/horus ./demo.sh
```

The demo writes records to `~/.horus-lineage` and **deletes that directory
first** so the baseline is clean. To keep your own records, send it
elsewhere:

```bash
HORUS_LINEAGE_DIR=/tmp/demo-records ./demo.sh
```

It restores every file it edits, and leaves `results/` behind.

## The workflow

A diamond, so an impact question has a non-trivial answer:

```
data/raw.csv ──> prep ──┬──> analyse ──┐
                        │              ├──> report
                        └──> qc ───────┘

data/calibration.txt ──> analyse
data/reference.txt ────> report
```

## What each scenario shows

| # | Change | Point |
|---|---|---|
| 1 | `calibration.txt` | Reaches `analyse` and `report`, not the parallel `qc` branch |
| 2 | `raw.csv` | The root input, so everything is downstream |
| 3 | `reference.txt` | Feeds only the last task, so nothing else moves |
| 4 | `scripts/qc.py` | A script, which the engine's fingerprint cannot see |

Scenarios 1 to 3 match the engine exactly.

Scenario 4 is the interesting one. The engine holds a runtime's script as
a path rather than as bytes, and the script is not a declared input, so
editing it changes neither `config_sha256` nor any input digest. The task
skips with stale code and the workflow reports success. The records name
the affected tasks anyway, and say `engine detects it: False`, which is
the caveat a reader has to surface: these tasks are affected, and Horus
will not recompute them without its cache being cleared.

## impact.py

About 80 lines, reading only a run directory. Topology comes from the
`edges` in `definition.json`, identity from the content digests, code
changes from each task's `code` entries, and the machine each affected
task runs on from `target.location_id`.

It reports both a lower and an upper bound rather than one number. A task
re-runs only when its own inputs or config changed, so a cascade halts
wherever a task produces identical bytes from changed inputs. The full
downstream closure is a ceiling, not an answer.

This is a stand-in for Clew's `extract-horus`, not a replacement for it.
