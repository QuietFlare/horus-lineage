# ADR 0004: Pure observer, failures never fail the run

Status: accepted

## Context

A recorder that can break the runs it records will be uninstalled the
first time it does. Compute time is expensive, records are worthless
if nobody dares run the recorder.

## Decision

Every hook wraps its body: any exception is logged as a warning and
swallowed. The plugin never alters task behavior, caching, placement
or results. Recording only.

## Consequences

A recorder failure can silently produce an incomplete run directory.
That is the accepted trade: the extractor treats missing records as
unknown, never as clean, so the failure degrades honestly.
