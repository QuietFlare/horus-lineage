# ADR 0003: Content digests on outputs, on by default

Status: proposed, pending upstream discussion

## Context

The engine already digests task inputs (sha256 of the bytes, computed
on the machine holding them) to decide skip or re-run. Outputs are not
digested, because a cache does not need them. A record does: output
digests joined to the next task's input digests give exact edges, and
identity that survives copies and machines.

## Decision

Digest every output in the task middleware after hook, through the
engine's own ArtifactStore, and record digest plus size per artifact.
On by default, one switch to disable for cost-sensitive runs.

## Consequences

One sha256 read per output file, on the target that holds it. Records
gain exact cross-task and cross-run joins. Folder artifacts follow
whatever the engine's digest does for them, currently unhashable.
