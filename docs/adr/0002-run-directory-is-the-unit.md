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
      workflow.yaml     source copy, when one exists
      <task-id>.json    one observation per task

Move it whole. Every task record carries the sha256 of the definition
it executed under, so a missing or mismatched plan is detected rather
than silently joined.

## Consequences

Readers always consume a directory, never a lone file. Verification is
a digest comparison, not trust in filenames.
