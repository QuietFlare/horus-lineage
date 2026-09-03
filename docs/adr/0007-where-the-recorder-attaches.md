# ADR 0007: Where the recorder attaches, and why not the obvious place

Status: accepted

## Context

ADR 0001 says a task observation is written when the task finishes. The
obvious implementation is the task middleware's `after` hook. Reading the
engine shows that hook cannot do the job, for two independent reasons.

**Status is not final in `after`.** The default middleware `wrap` runs
`after` in a `finally`, so it does fire for failed and cancelled tasks.
But `BaseTask.run` assigns COMPLETED, FAILED or CANCELED in the
`try/except/else` *around* the middleware chain, after it has returned.
Inside `after` the status is always RUNNING.

**Skipped tasks never arrive.** `BaseTask.run` sets SKIPPED and returns
before the chain is entered. The upstream author confirmed this and
suggested the target middleware instead, since that one dispatches every
task. That suggestion needs one correction: `BaseTarget.dispatch` wraps
`_dispatch`, which only calls `asyncio.create_task(task.run())` and
returns. The scheduler awaits `target.wait()` separately, afterwards. So
the target middleware's `after` fires the moment a task is *scheduled*,
sees PENDING, and never sees a skip either.

## Decision

Four middlewares, each attached where the fact it records is actually
available.

**Workflow.** Mints the run id and writes `run.json` at start, then
`finished_at` and the final status when the chain returns.

**Task.** Overrides `wrap` rather than using `after`, so it observes
whether `call_next` raised and derives the status the engine is about to
assign. This is the full record: resolved paths, sizes, digests, the
command. Executed tasks only.

**Target.** Overrides `wrap`, calls `call_next` to let the dispatch
proceed, then awaits `target.wait()` and swallows whatever it raises.
By then the task's status is final for every outcome, skips included.
It writes a record only for tasks the task middleware never saw.

**Runtime.** Wraps `setup_runtime`, whose return value is the substituted
command. Its context carries both the runtime and the task, so the
captured command is attributed to a task id and handed to the task
middleware through the run's session state.

## Consequences

The target middleware awaits a future the scheduler was about to await
on the very next line, inside the same `try` that already handles both
its exceptions and its cancellation. Task-level concurrency is unchanged,
because each ready task is its own coroutine. Awaiting an `asyncio.Task`
twice is safe and the second await returns immediately, so the
scheduler's own `wait()` still raises exactly what it would have raised.
This is the one place the recorder touches control flow at all, and ADR
0004 still holds: it adds no failure path of its own.

The same applies to `finished_at`, which horus-runtime 0.5.0 stamps in
the same block as the status. Inside `wrap` it is still unset, so the
task record stamps the moment the chain returned, which is the instant
the engine is about to write. `started_at` is set before the chain and
is read as is.

Deriving status in `wrap` rather than reading `task.status` means the
recorder reimplements a mapping the engine owns. If upstream ever moves
the status assignment inside the chain, this becomes redundant rather
than wrong.

Skip capture would be simpler if task middleware were invoked with a
skip context, which the upstream author offered to consider. The design
does not depend on it. If it lands, the target middleware's role shrinks
to nothing and it can be dropped.
