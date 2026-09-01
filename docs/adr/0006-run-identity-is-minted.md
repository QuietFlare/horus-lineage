# ADR 0006: The recorder mints the run id

Status: accepted

## Context

ADR 0002 makes the run directory the unit of storage, so every run needs
an identity. The obvious candidate was the engine's own `run_scope`. The
upstream author confirmed it is new on every launch, so that runs never
overwrite each other's logs and intermediate results.

Reading the field says something the confirmation did not:

    run_scope: str | None = None
    """Opaque, caller-set relative path fragment nested under a
    non-co-located target's own working directory when anchoring tasks.
    This class does not interpret its contents -- a caller such as the
    orchestrator composes it (e.g. f"{workflow_slug}/{run_id}") and
    assigns it before run()."""

It is `None` whenever no orchestrator assigned one, which is every plain
CLI run of a YAML workflow. It is explicitly opaque, so a reader may not
parse an id out of it. It is consulted only when anchoring non-co-located
targets, so it is a placement detail that happens to change per run, not
a run identity.

## Decision

The recorder mints its own run id in the workflow middleware, once, at
run start: sixteen random hex characters, unique by construction and
never parsed for meaning.

Two engine values are recorded beside it, verbatim, because they answer
different questions:

    run_scope        the engine's per-run scratch fragment, may be null.
                     Joins a record back to the engine's own layout when
                     an orchestrator set one.
    run_directory    the root produced artifacts anchor under. Artifacts
                     the workflow produced resolve beneath it, artifacts
                     it only consumed resolve outside it.

`run_directory` is the structural boundary between produced and consumed
artifacts, and the engine draws it that way itself: a declared path is
anchored under the run root when some task produces it, and under the
base directory otherwise. Recording it gives a reader that classification
directly instead of inferring it from a digest that matched nothing.

Note that it is not per-run scratch. It is generally stable across runs,
and its stability is what makes resumption work (ADR 0007). The per-run
scratch is the task working directory, which nests `run_scope` and a
fresh invocation id.

## Consequences

Records are self-identifying on any run, orchestrated or not. The
recorder's id and the engine's scope may disagree without either being
wrong, because they answer different questions: which record set is
this, and where did the engine put the scratch.

A run id is meaningless outside its run directory, which is the point.
It namespaces nodes so that many run directories load into one graph
without collision, and nothing else.

Downstream joins never use it:

    run id             namespaces task nodes within a reader's graph
    definition_sha256  groups runs of the same workflow definition
    content digests    build every edge, within and across runs

A re-run gets a new run directory of records while its artifacts keep
their paths and digests, so successive runs join through content alone.
No field links one run to another, and none is invented, because the
recorder cannot populate one reliably.
