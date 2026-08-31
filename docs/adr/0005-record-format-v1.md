# ADR 0005: The record format, versioned as horus-lineage/v1

Status: proposed, pending upstream discussion

## Context

Records are read by external tools, possibly years after they were
written and by software that did not exist when they were written. The
fields must be stable, self-identifying, and allowed to evolve without
silently changing the meaning of old records.

## Decision

Plain JSON, one object per file. Every file carries a format field,
"horus-lineage/v1". A semantic change to any field is a new version,
never an edit. Readers check the format field and refuse versions they
do not know, rather than guessing.

Per run, run.json:

    run            the engine's run scope id
    workflow       id and name
    started_at     ISO 8601, written at run start
    finished_at    written at clean completion, absent means the run died
    definition     the workflow dump, plus sha256 of the source file
    code           digests of script files referenced by the definition

Per task, <task-id>.json:

    run, execution        scope ids, re-runs never overwrite
    definition_sha256     the exact plan this task executed under
    recorded_at           ISO 8601
    task                  id, kind, status, skip_reason
    target                kind and name only, no credentials
    inputs, outputs       per artifact: id, path, size, sha256

## Consequences

Old records stay readable forever under their own version. The target
field deliberately excludes connection details, records must be safe to
share. Field additions that change no meaning may land within v1,
anything else is v2.
