# ADR 0005: The record format, versioned as horus-lineage/v1

Status: proposed, pending upstream discussion

## Context

Records are read by external tools, possibly years after they were
written and by software that did not exist when they were written. The
fields must be stable, self-identifying, and allowed to evolve without
silently changing the meaning of old records.

## Decision

Plain JSON, one object per file. Every file carries a format field.
A semantic change to any field is a new version, never an edit.
Readers check the format field and refuse versions they do not know,
rather than guessing.

### run.json, written at run start, completed at the end

```json
{
  "format": "horus-lineage/v1",
  "run": "9c1f4a70e2b84d15",
  "run_scope": "experiment_pipeline/run-123",
  "run_directory": "/work/experiments",
  "workflow": {
    "id": "3f2a1c88-0d41-4e2b-9a77-5c0e1b6f4d23",
    "slug": "experiment_pipeline",
    "name": "Experiment pipeline"
  },
  "started_at": "2026-09-01T14:20:02+00:00",
  "finished_at": "2026-09-01T15:41:17+00:00",
  "status": "completed",
  "definition": {"file": "definition.json", "sha256": "ab41f0..."},
  "source": {"file": "workflow.yaml", "sha256": "5d10c4..."},
  "code": [
    {"path": "scripts/prep.py", "size": 4312, "sha256": "77c2e8..."}
  ],
  "tasks": ["prep", "analyse", "report"]
}
```

Field notes:

    run              minted by the recorder, never the engine's run_scope
                     (ADR 0006)
    run_scope        the engine's value, verbatim, null when unset
    run_directory    the root produced artifacts anchor under, so a
                     reader can tell produced from merely consumed
    definition       the recorder's own projection of the workflow, and
                     the digest every task record cites
    source           the workflow file copied verbatim, null when the
                     workflow was built in Python rather than loaded
                     from YAML
    code             a rollup of every code file any task referenced.
                     Attribution lives on the task records
    status           the workflow's final status

A missing `finished_at` means the run died partway. The task records
that exist are the lineage of how far it got.

`definition.json` is a projection, not a dump. A full model dump would
carry whatever fields third-party targets and executors define, which
may include credentials, and records must be safe to share. The
projection is an explicit allowlist: task ids, names and kinds, executor
and runtime kinds, referenced code paths, target kinds and location ids,
declared artifact ids and paths, and edges. Fields the recorder does not
know about are dropped rather than passed through.

### <task-id>.json, one per task

```json
{
  "format": "horus-lineage/v1",
  "run": "9c1f4a70e2b84d15",
  "execution": "7d40e6b2c1f34a09",
  "definition_sha256": "ab41f0...",
  "recorded_at": "2026-09-01T14:22:31+00:00",
  "task": {
    "id": "analyse",
    "definition_id": "analyse",
    "kind": "horus_task",
    "name": "Analyse batches",
    "status": "completed",
    "skip_reason": null,
    "runs": 1
  },
  "target": {"kind": "ssh", "location_id": "ssh://user@cluster-a"},
  "working_dir": "/scratch/experiment_pipeline/run-123/analyse/7d40e6b2",
  "command": "python analyse.py --in batch_017.csv --out results.parquet",
  "environment": {
    "executor": {"kind": "conda_python_environment", "sha256": "4e77a1..."},
    "runtime": {"kind": "python_script", "sha256": "b2c018..."},
    "config_sha256": "9d3f2e..."
  },
  "code": [
    {"path": "scripts/analyse.py", "size": 4312, "sha256": "77c2e8...",
     "role": "script"}
  ],
  "inputs": [
    {"id": "measurements", "path": "/data/run1/batch_017.csv",
     "size": 812345, "sha256": "9f31a2..."},
    {"id": "calibration", "path": "/data/refs/calibration.dat",
     "size": 40961, "sha256": "1d4c99..."}
  ],
  "outputs": [
    {"id": "results", "path": "/data/run1/batch_017.parquet",
     "size": 192935, "sha256": "db59c2..."}
  ],
  "incomplete": []
}
```

Field notes:

    run, execution     scope ids, re-runs never overwrite history
    definition_sha256  the exact plan this task executed under
    task.status        skipped, failed and cancelled tasks are recorded
                       too, derived in wrap rather than read after the
                       fact (ADR 0007)
    target             kind and location id only, no credentials. A
                       location id may embed a username, as in
                       ssh://user@host, which is identity, not secret
    working_dir        per-run, per-invocation scratch. Changes every
                       run by design, unlike artifact paths
    command            the substituted command, captured by wrapping
                       setup_runtime, null when it could not be captured
    environment        digests of the executor and the runtime, plus
                       config_sha256, the engine's own combined value
    code               digests of the local files this task's runtime
                       referenced, attributed to this task
    sha256             content digest of the bytes, absent when the
                       artifact cannot be hashed
    size               cheap secondary identity for systems without
                       digests
    incomplete         what this record failed to capture, see below

The `environment` digests are hashes only, never the model dumps, for the
same reason `definition.json` is a projection: a third-party executor may
hold credentials. `config_sha256` is copied verbatim from what the engine
computes, so a reader inherits the engine's invalidation rule instead of
reimplementing one that can drift. The two component digests exist
because the engine's combined hash says *that* something changed and not
*which*, and naming the cause is the point.

`code` is per task, not only per run. run.json keeps a rollup for
convenience, but a run-level list can only say that some script changed.
Attributing digests to the task that ran them is what turns a changed
file into a set of affected tasks and, through `target`, the machines
those tasks run on.

### What a change is and is not detectable in

The format answers "what is affected when X changed" for some kinds of X
and honestly cannot for others. A reader should be built knowing which.

**A script changed.** Detectable, and only here. A runtime holds its
script as a path rather than as bytes, so editing the file leaves the
runtime dump identical and `config_sha256` with it. The script is not a
declared input either, so its digest is absent from the fingerprint.

Verified on a local run. Editing a script changed its sha256, and the
engine skipped the task and kept the stale output. The edit does not
vanish, it waits: it applied two runs later, when an unrelated input
change invalidated the cache, so the output moved at a moment that
pointed at the wrong cause. The per-task `code` digests are the only
record of what actually changed.

The exception is a templated script, `script: ${my_script}`, which names
an input artifact rather than a local file. That is an ordinary input,
so the engine invalidates correctly.

**A declared environment changed.** Detectable. An image reference,
a requirements list or an interpreter lives in the executor's model, so
it is inside `config_sha256` and inside the executor digest. The engine
invalidates and the record names the cause.

**A mutable environment reference changed.** Not detectable. An image tag
re-pushed under the same name is byte-identical in the executor's model.
The engine is blind and so is the recorder. Pinning by digest is the only
fix and it belongs to the workflow author.

**A tool on the target host changed.** Not detectable. A package upgrade,
a swapped conda environment or a new driver is outside everything Horus
models. Measuring it is a profiler's job, not a recorder's.

### Skipped tasks

A skipped task is the common case in any workflow that is re-run, and
the two skip reasons are not the same thing.

`complete` means the engine verified that the declared outputs exist and
that a recorded fingerprint matches the current inputs and configuration.
It is a positive confirmation, not an absence of work, and the outputs it
confirms are real files with real digests. The record is therefore
written in full:

    outputs      digested normally, they exist, that is why the task
                 skipped
    inputs       digests read from the engine's fingerprint manifest,
                 which is what the skip decision was made against and is
                 therefore equal to the current input state by
                 construction
    environment  recorded normally, it comes from the task's model
    code         recorded normally, the files are on the orchestrator
                 whether or not the task ran
    command      null, nothing was resolved

`environment` and `code` matter more on a skipped record than on an
executed one. A workflow re-run daily is mostly skips, so omitting them
would mean a changed script maps to none of the tasks that use it,
precisely because those tasks were cached.

A `complete` record joins into a downstream graph identically to an
executed one. Without the fingerprint read it would carry no digests, no
edges would form, and its consumers' inputs would be misread as files
supplied from outside the pipeline. The chain would break exactly where
caching worked best.

`inactive` means no incoming edge was live, so the task is on a branch
that was not taken. It never ran and has no outputs. The record carries
the status and nothing to join, which is accurate rather than a gap.

Nothing marks a run stale. A run made largely of skips is the freshest
confirmation available, and it may be the only run directory a reader
holds. Deciding which runs to weigh is the reader's judgment, not the
recorder's, consistent with ADR 0004.

### Recording what was missed

`incomplete` is a list of short codes naming what this record could not
capture. It is empty in the ordinary case.

    digests_disabled   digests were switched off for this run
    digests_partial    digests were on, and some artifact still has none

A missing fingerprint manifest is not listed. Falling back to hashing the
bytes costs a read and loses nothing, and some task kinds never write one.
What a reader needs is whether an artifact ended up without a digest,
because that is an edge it will not see: a folder, a file that no longer
exists, or a subworkflow port, which is a boundary placeholder rather than
a file on disk.

This is mechanical, not evaluative. The recorder states what it failed to
observe and leaves the reader to decide what that is worth, which is the
same principle as ADR 0004's treatment of missing records: degrade to
unknown, never to clean.

## Consequences

Old records stay readable forever under their own version. Field
additions that change no meaning may land within v1, anything else is v2.

The projection in `definition.json` means the recorder must be updated
when a field worth recording appears upstream. That is the cost of never
leaking a credential by default, and it is the right way round: a
recorder that omits a new field is incomplete, one that passes through
an unknown field may be unpublishable.

A record answers "what is affected when this changed" for three kinds of
change: an input, a script, and a declared environment. Each resolves to
a set of tasks and, through `target`, to the machines those tasks run on.
What that recomputation costs is not recorded and not inferred. The
machines are the signal, and whoever owns them prices it.

Per-task `code` digests make the recorder the only thing that detects an
edited script, since the engine's fingerprint holds the script's path
rather than its bytes. That is a gap worth reporting upstream. Until it
closes, a reader that trusts the engine to invalidate on code changes
will be wrong, and one that reads these digests will not.

The affected set is an upper bound, not an answer. A task re-runs only
when its own inputs or config changed, so a task that produces identical
bytes from changed inputs halts the cascade. A local run shows it: a
whitespace edit to an input re-ran the first task, whose output came out
byte-identical, and both downstream tasks skipped. A reader that walks
the full downstream closure should say which of it is certain.
