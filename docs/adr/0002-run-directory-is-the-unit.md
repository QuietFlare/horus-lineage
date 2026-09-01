# ADR 0002: The run directory is the unit, files reference by digest

Status: proposed, pending upstream discussion

## Context

Splitting plan from observation (ADR 0001) means files reference each
other. References can dangle or, worse, silently point at the wrong
plan when files are moved between run directories.

## Decision

The unit of storage and distribution is the run directory:

    ~/.horus-lineage/<run>/
      run.json          the plan, written at run start
      definition.json   the projected workflow definition, digested
      workflow.yaml     source copy, when one exists
      <task-id>.json    one observation per task

Move it whole. Every task record carries the sha256 of the definition
it executed under, so a missing or mismatched plan is detected rather
than silently joined.

One file per task, rather than one file per run, because each is
written as its task finishes: a run that dies keeps what it completed,
and parallel tasks never contend for one file. A run may be folded into
a single `records.jsonl` afterwards, which is a layout choice made once
the writing is over and changes nothing about what was recorded.

## Consequences

Readers always consume a directory, never a lone file. Verification is
a digest comparison, not trust in filenames.

A reader must handle both layouts: `<task-id>.<hash>.json` files, or one
`records.jsonl` holding the same objects one per line.
