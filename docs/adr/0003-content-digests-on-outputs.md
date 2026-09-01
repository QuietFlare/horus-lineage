# ADR 0003: Content digests on outputs, on by default

Status: accepted, confirmed upstream

## Context

The engine already digests task inputs (sha256 of the bytes, computed
on the machine holding them) to decide skip or re-run. Outputs are not
digested, because a cache does not need them. A record does: output
digests joined to the next task's input digests give exact edges, and
identity that survives copies and machines.

## Decision

Digest every output as the task finishes, through the engine's own
`ArtifactStore`. On by default, one switch to disable for cost-sensitive
runs.

The upstream author agreed, with the caveat that it is untried: "no
problem calling artifactstore on outputs in after (in theory)". Treat it
as sanctioned rather than proven, and let ADR 0004 absorb the surprises.

Do not digest inputs. The engine already hashes every input to build its
fingerprint and writes the result to `.horus/<task_id>.json`. Read that
file instead. It halves the cost, and it records the value the engine
acted on rather than a second one taken moments later. A local run
confirms the format and that the digests match the files:

    {"inputs": {"items": "dae737a818..."}, "config_hash": "cc9737e763..."}

Size is best effort. `ArtifactStore.digest` returns a digest and nothing
else, and the only route to a size is a directory listing, which is
pathological on a directory holding many files. Record it when a listing
is already at hand and omit it otherwise. A sha256 carries the identity
that size was standing in for.

## Consequences

One sha256 read per output file, on the target that holds it. Records
gain exact cross-task and cross-run joins. Folder artifacts follow
whatever the engine's digest does for them, currently unhashable.

Skipped tasks are digested too. Their outputs exist, which is why they
skipped, so excluding them would lose the edges of every cached task
(ADR 0005).
