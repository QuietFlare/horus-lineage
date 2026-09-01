# ADR 0001: Split the record into plan and observation

Status: proposed, pending upstream discussion

## Context

A lineage record must say what a run intended and what actually happened.
These are not the same thing. The runtime, executor and code are decided
before the run. The target a task lands on, the paths its artifacts
resolve to and its final status are only knowable at execution time.
Duplicating the plan into every task record repeats identical data per
task. Recording only the plan misses what happened.

W3C PROV and Workflow Run RO-Crate both model this split as prospective
versus retrospective provenance.

## Decision

Write the plan once per run, at run start: the workflow definition, its
source file when one exists, and digests of referenced code files. Write
one observation per task, when it finishes: status, target, resolved
paths, sizes, content digests, the resolved command, timestamps.

## Consequences

A task record is not self-explanatory alone, it needs its run directory
(see ADR 0002). A run that dies partway still leaves its plan and the
records of how far it got, because the plan is written first.

"When it finishes" is not a single hook. A task's final status is
assigned after the task middleware chain returns, and a skipped task
never enters that chain at all, so the observation is assembled from
three hooks rather than one. ADR 0007 covers where each attaches.
