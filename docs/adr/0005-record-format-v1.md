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

### run.json, written at run start, finished_at added at clean completion

```json
{
  "format": "horus-lineage/v1",
  "run": "b3f2c9a1",
  "workflow": {"id": "c0ffee12", "name": "experiment_pipeline"},
  "started_at": "2026-09-01T14:20:02+00:00",
  "finished_at": "2026-09-01T15:41:17+00:00",
  "definition": {"file": "workflow.yaml", "sha256": "ab41f0..."},
  "code": [
    {"path": "scripts/prep.py", "size": 4312, "sha256": "77c2e8..."}
  ],
  "tasks": ["process_batch_017", "process_batch_018", "merge_results"]
}
```

A missing finished_at means the run died partway. The task records
that exist are the lineage of how far it got.

### <task-id>.json, one per task, written when it finishes

```json
{
  "format": "horus-lineage/v1",
  "run": "b3f2c9a1",
  "execution": "7d40e6b2",
  "definition_sha256": "ab41f0...",
  "recorded_at": "2026-09-01T14:22:31+00:00",
  "task": {
    "id": "process_batch_017",
    "kind": "horus_task",
    "status": "COMPLETED",
    "skip_reason": null
  },
  "target": {"kind": "ssh", "name": "cluster-a"},
  "inputs": [
    {"id": "measurements", "path": "/data/run1/batch_017.csv",
     "size": 812345, "sha256": "9f31a2..."},
    {"id": "calibration", "path": "/data/refs/calibration.dat",
     "size": 40961, "sha256": "1d4c99..."}
  ],
  "outputs": [
    {"id": "results", "path": "/data/run1/batch_017.parquet",
     "size": 192935, "sha256": "db59c2..."}
  ]
}
```

Field notes:

    run, execution        scope ids, re-runs never overwrite history
    definition_sha256     the exact plan this task executed under
    task.status           skipped and failed tasks are recorded too
    target                kind and name only, no credentials, records
                          must be safe to share
    sha256                content digest of the bytes, absent when the
                          artifact cannot be hashed
    size                  cheap secondary identity for systems
                          without digests

## Consequences

Old records stay readable forever under their own version. Field
additions that change no meaning may land within v1, anything else
is v2.
