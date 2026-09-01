# horus-lineage

A Horus runtime plugin that records what each run did: one JSON record per
task, one per run, joined by content digest.

Records are written for every task, including skipped and failed ones, and
are safe to share (no credentials, no command output, no file contents).

## Install

```bash
uv pip install horus-lineage
```

Registration is automatic. The plugin declares four `horus.middleware.*`
entry points, which Horus loads at boot, so there is nothing to enable and
no workflow change. Run workflows exactly as before:

```bash
horus run workflow.yaml
```

Verify it is active:

```bash
python -c "from importlib.metadata import entry_points as e; print([x.name for x in e(group='horus.middleware.task')])"
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HORUS_LINEAGE_DIR` | `~/.horus-lineage` | Where run directories are written. Set to `@run` to write under the workflow's own run directory, or to any absolute path. |
| `HORUS_LINEAGE_DIGESTS` | on | Set to `0`, `false`, `no` or `off` to record paths and sizes without hashing. Records written this way carry no edges. |

Writes are local only. Point `HORUS_LINEAGE_DIR` at a local filesystem and
sync afterwards. A network mount or object store inside a middleware can
block without raising, which stalls the task rather than failing it.

## Output

One directory per run, moved as a unit:

```
~/.horus-lineage/<run-id>/
  run.json          the plan, written at start, closed at the end
  definition.json   the projected workflow, digested by every task record
  workflow.yaml     source copy, when the workflow came from a file
  <task-id>.<hash>.json
```

Task filenames are sanitized and suffixed with a short digest of the
original id, so map clones and ids containing separators stay distinct.

### run.json

```json
{
  "format": "horus-lineage/v1",
  "run": "d79086aa31e44bdb",
  "run_scope": null,
  "run_directory": "/work/experiment/results",
  "workflow": {"id": "81cc0410-...", "slug": null, "name": "Pipeline"},
  "started_at": "2026-09-01T11:02:23.498427+00:00",
  "finished_at": "2026-09-01T11:02:23.667623+00:00",
  "status": "completed",
  "definition": {"file": "definition.json", "sha256": "424fb10b..."},
  "source": null,
  "code": [{"path": "scripts/prep.py", "size": 341, "sha256": "1ff65be4...", "role": "script"}],
  "tasks": ["prep", "analyse", "report"]
}
```

A missing `finished_at` means the run died partway. The task records that
exist are the lineage of how far it got.

### Task record

```json
{
  "format": "horus-lineage/v1",
  "run": "d79086aa31e44bdb",
  "execution": "41ab2a1c9ee14cc7a40e6ee9c223db58",
  "definition_sha256": "424fb10b...",
  "recorded_at": "2026-09-01T11:02:23.641852+00:00",
  "task": {"id": "analyse", "definition_id": null, "kind": "horus_task",
           "name": "Analyse", "status": "completed", "skip_reason": null,
           "runs": 1},
  "target": {"kind": "local", "location_id": "local://node-01"},
  "working_dir": "/work/experiment/results/analyse/41ab2a1c...",
  "command": "python3 analyse.py --prepared ... --out ...",
  "environment": {
    "executor": {"kind": "shell", "sha256": "6fa3b9ca..."},
    "runtime": {"kind": "python_script", "sha256": "a814cc0d..."},
    "config_sha256": "a26537d3..."
  },
  "code": [{"path": "scripts/analyse.py", "size": 481, "sha256": "b3f01889...", "role": "script"}],
  "inputs": [{"id": "prepared", "path": "...", "size": 336, "sha256": "b860bf6c..."}],
  "outputs": [{"id": "analysed", "path": "...", "size": 33, "sha256": "314ffd24..."}],
  "incomplete": []
}
```

Field reference and versioning rules: [`docs/adr/0005`](docs/adr/0005-record-format-v1.md).

## Reading records

Check `format` and refuse unknown versions rather than guessing. Field
additions that change no meaning land within `v1`, anything else is `v2`.

**Topology comes from `definition.json`.** Its `edges` are the declared
graph. Do not derive topology from digests alone: any pass-through step
(copy, move, rename, a filter that removes nothing) produces an output
byte-identical to its input, which reads as a self-edge.

**Identity comes from digests.** Use `sha256` to join across runs, to
detect that an artifact is unchanged, and to confirm a declared edge
actually carried the bytes it claims. An input digest matching no recorded
output is external to the run.

**Group runs by `definition_sha256`.** Run ids namespace nodes within a
reader's graph and never cross a run boundary. Nothing links a re-run to
its predecessor, by design.

**`incomplete` lists what a record could not capture**, for example
`["fingerprint"]` or `["digests_disabled"]`. Treat those records as
partial rather than clean.

## Behaviour

- **Never fails a run.** Every hook swallows and logs its own errors. A
  broken recorder or an unwritable destination leaves the run untouched.
  Cancellation still propagates.
- **Skipped tasks are recorded in full.** Their outputs exist, so they are
  digested normally, and their input digests are read from the engine's
  fingerprint manifest. Omitting them would break every edge through a
  cached task.
- **Input digests are not recomputed.** The engine already hashes inputs to
  build its fingerprint. Records reuse that value, so bytes are read once
  per run and the record matches the value the engine acted on.
- **Re-runs never overwrite history.** Each run gets its own directory.

## Known limits

- **`size` is best effort.** `ArtifactStore` exposes a digest and no size,
  so sizes come from a cached directory listing and are omitted when that
  listing is unavailable or too expensive.
- **Folder artifacts have no digest.** The engine's `digest` returns `None`
  for directories, so `sha256` is absent and those artifacts do not join.
- **`source` is currently always `null`.** `BaseWorkflow.from_yaml` retains
  the workflow file's directory but not its path.
- **Code files are found heuristically**, by scanning each runtime's own
  fields for values resolving to a local file with a code suffix.
- **The engine does not invalidate on script edits.** A runtime holds its
  script as a path, so editing the file changes neither `config_sha256` nor
  any input digest, and the task will skip with stale code. The per-task
  `code` digests detect this, which means a record can report a task as
  affected that Horus will not re-run without clearing its cache. A
  templated script (`script: ${artifact}`) is an ordinary input and
  invalidates correctly.

## Development

```bash
uv sync --group dev
uv run make lint    # ruff, ruff format, mypy strict
uv run make test    # pytest with coverage
```

Design decisions are recorded as ADRs in [`docs/adr/`](docs/adr/). Read
0005 before changing the record shape.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
