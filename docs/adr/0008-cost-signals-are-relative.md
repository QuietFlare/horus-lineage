# ADR 0008: Cost signals are relative, and say so

Status: accepted

## Context

The question behind this recorder is what a change costs to recompute.
Records already answer which tasks are affected. The obvious next step is
to attach a price: where each task ran, and how long it took.

Both are cheap to record. `target.location_id` is already in every task
record. Duration is two timestamps around the task middleware's `wrap`,
and the engine already measures it in `horus_builtin`'s `task_time`
middleware, which logs "completed in 3.42 seconds" and discards it.

The risk is not in recording them. It is in what a reader then claims.

## Decision

Record both, and state their accuracy in the format itself.

**`target` is a fact.** A location id is deterministic across process
restarts and unique per machine. Which machine ran a task is the
strongest cost signal available without measuring anything: a fan-out
that lands on a GPU cluster is expensive whatever the clock says.

**Duration is indicative, not measured consumption.** Wall clock for
identical work varies with cluster load, cache state and concurrent
jobs. On a scheduler the span includes queue wait, which is not compute
at all. The same task can differ several fold between runs while
consuming the same energy.

**Declared resources are hints.** `ResourceRequest` says so directly:
every field is advisory and "targets are free to round up, ignore
unsupported fields, or reject a request they cannot satisfy". `cpus: 4`
is a request, not a measurement.

So a reader may use these to compare, and may not use them to assert:

    supported     ranking one change against another
                  "this trigger reaches ten times more compute"
                  "most of this lands on the GPU cluster"

    not supported absolute cost or carbon figures
                  anything a third party would audit as consumption

Carbon accounting needs CPU time, core count, hardware TDP, datacentre
overhead and grid intensity. Wall clock and an advisory core count are
none of those.

## Consequences

Anything presenting these numbers labels them as indicative. A report
that prints hours without that label invites a claim the data does not
support, and a wrong carbon figure is worse than none because someone
will publish it.

Real consumption stays out of scope. The engine already exposes
`ResourceScope`, documented as existing "so an observer can find and
measure it", and nothing consumes it. Measuring a live process is a
profiler's job and a different plugin. This one records what the engine
already computed.

A skipped task has no duration, because it did not run. The cost of
recomputing it comes from the last run in which it actually executed,
which is a cross-run lookup on the same digests everything else joins
by. A run made mostly of skips therefore prices almost nothing on its
own, and that is honest rather than missing.
