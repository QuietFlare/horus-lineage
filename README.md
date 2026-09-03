# horus-lineage

A Horus runtime plugin that records what each run did: one JSON record per
task, one per run, joined by content digest.

Records are written for every task, including skipped and failed ones.
They hold digests, paths and the resolved command line, never command
output, file contents, or the executor and target settings that could
carry credentials. See [Sharing](#sharing) for the two verbatim fields.

`horus-lineage report` turns a run directory into a single self-contained
page: what the run produced, what it took from outside, and what the result
rests on.

![A lineage report: the derivation drawing, what came from outside the run, and the chain behind the final result](docs/report.png)

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
| `HORUS_LINEAGE_MERGE` | off | Set to `1` to fold the per-task records into a single `records.jsonl` once the run ends. Worth it at a few hundred tasks, or over a network filesystem. |
| `HORUS_LINEAGE_COMMAND` | on | Set to `0` to leave `command` out of every record, for a workflow that passes a secret as an argument. |

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

One file per task is deliberate. Each is written the moment that task
finishes, so a run that dies at task 9 of 200 keeps the 8 that
completed, and tasks running in parallel never contend for one file.
Records are around 2 KB each, so 183 tasks is 185 files and roughly
440 KB.

With `HORUS_LINEAGE_MERGE=1` the parts are folded into one
`records.jsonl`, one record per line, after the last task has been
written:

```
~/.horus-lineage/<run-id>/
  run.json
  definition.json
  records.jsonl
```

The per-task writes still happen during the run, so the crash-safe
behaviour is unchanged: a run killed before it finishes keeps its loose
files. `run.json` and `definition.json` stay separate, since they are
where a reader starts.

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
           "runs": 1,
           "started_at": "2026-09-01T11:02:23.512044+00:00",
           "finished_at": "2026-09-01T11:02:23.640127+00:00"},
  "target": {"kind": "local", "location_id": "local://node-01"},
  "working_dir": "/work/experiment/results/analyse/41ab2a1c...",
  "command": "python3 analyse.py --prepared ... --out ...",
  "environment": {
    "executor": {"kind": "shell", "sha256": "6fa3b9ca..."},
    "runtime": {"kind": "python_script", "sha256": "a814cc0d..."},
    "config_sha256": "a26537d3..."
  },
  "code": [{"path": "scripts/analyse.py", "size": 481, "sha256": "b3f01889...", "role": "script"}],
  "inputs": [{"id": "prepared", "path": "...", "size": 336, "sha256": "b860bf6c...",
              "labels": {"subject": "batch_017"}}],
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

**`labels` carry the domain vocabulary.** A workflow author writes
`labels: {subject: batch_017}` on an artifact and it reaches the record
verbatim, so a reader can group by subject without parsing filenames.
Absent when an artifact has none.

**Group runs by `definition_sha256`.** Run ids namespace nodes within a
reader's graph and never cross a run boundary. Nothing links a re-run to
its predecessor, by design.

**`incomplete` lists what a record could not capture.** `digests_disabled`
means hashing was off for the run, `digests_partial` means it was on and
some artifact still has no digest, which is an edge you will not see.
Treat those records as partial rather than clean.

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
- **A moved manifest is reported, not hidden.** The engine's fingerprint
  manifest sits at an undocumented path. If a release moves it, digests
  are re-hashed and one warning per run says so.

## Sharing

Executor and target settings reach a record only as digests, and the
workflow definition is a projection of known fields, so a plugin that
holds a credential in its model cannot leak it. Two fields are copied as
written and are only as clean as the workflow that produced them:

- `command` is the substituted command line. A secret passed as an
  argument is recorded with it. Pass secrets through the environment,
  which is never recorded, or set `HORUS_LINEAGE_COMMAND=0`.
- `workflow.yaml` is the source file, byte for byte. A secret written
  into it travels with the run directory.

## Known limits

- **`size` is best effort.** `ArtifactStore` exposes a digest and no size,
  so sizes come from a cached directory listing and are omitted when that
  listing is unavailable or too expensive.
- **Folder artifacts have no digest.** The engine's `digest` returns `None`
  for directories, so `sha256` is absent and those artifacts do not join.
- **Cost signals are relative.** `target` is a fact, but the duration
  between `started_at` and `finished_at` is wall clock, which varies
  severalfold for identical work with cluster load and queue wait, and
  `ResourceRequest` fields are advisory hints a target may ignore. Use
  them to rank changes against each other, not to state absolute cost or
  carbon. See
  [`docs/adr/0008`](docs/adr/0008-cost-signals-are-relative.md).
- **The affected set is an upper bound.** A task re-runs only when its own
  inputs or config changed, so a task producing identical bytes from
  changed inputs halts the cascade. Walking the full downstream closure
  overstates what will actually re-run.
- **Environment drift is invisible.** An image tag re-pushed under the same
  name, or a package upgraded on the target host, is byte-identical in the
  executor's model. The engine cannot see it and neither can a record. Pin
  images by digest.

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
