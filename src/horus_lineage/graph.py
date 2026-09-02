#
# horus-lineage
# Copyright (C) 2026 QuietFlare
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""
Reading derivation back out of a run directory.

The records say what each task consumed and produced, with a digest on
every artifact. That is enough to rebuild what came from what: an input
whose sha256 matches some task's output was produced by that task, and
one matching nothing came from outside the run.

Declared edges from ``definition.json`` fill the gaps, because two kinds
of artifact carry no digest. Folders, which the engine will not hash,
and subworkflow ports, which are placeholders with no file behind them.

Nothing here renders. It answers structural questions so the report can
state them plainly.
"""

from collections import Counter
from pathlib import Path
from typing import Any

Record = dict[str, Any]

EXTERNAL = "EXTERNAL"
"""Producer of an artifact this run consumed but did not make."""


def producers(records: list[Record]) -> dict[str, str]:
    """
    sha256 -> the task that produced it.

    First producer wins. A pass-through task emits bytes identical to
    its input, and the origin is the more useful answer than the copy.
    """
    found: dict[str, str] = {}
    for record in records:
        for output in record.get("outputs", []):
            digest = output.get("sha256")
            if digest:
                found.setdefault(digest, record["task"]["id"])
    return found


def declared(definition: Record) -> dict[tuple[str, str], str]:
    """
    (consumer, input id) -> producer, from the workflow's own edges.
    Consulted only where a digest is missing.
    """
    edges: dict[tuple[str, str], str] = {}
    for edge in (definition or {}).get("edges", []):
        source, target = edge.get("source"), edge.get("target")
        target_input = edge.get("target_input")
        if not source or not target or not target_input:
            continue
        if source.startswith("artifact-"):
            continue
        edges[(target, target_input)] = source
    return edges


def derivation(records: list[Record], definition: Record) -> list[Record]:
    """
    One entry per consumed artifact: who made it, who read it, and what
    it was.
    """
    by_digest = producers(records)
    by_edge = declared(definition)

    edges: list[Record] = []
    for record in records:
        consumer = record["task"]["id"]
        for entry in record.get("inputs", []):
            digest = entry.get("sha256")
            producer = by_digest.get(digest) if digest else None
            if producer is None or producer == consumer:
                producer = by_edge.get((consumer, entry.get("id")))
            edges.append(
                {
                    "producer": producer or EXTERNAL,
                    "consumer": consumer,
                    "name": Path(entry.get("path", "")).name,
                    "path": entry.get("path", ""),
                    "sha256": digest,
                }
            )
    return edges


def external_inputs(edges: list[Record]) -> list[Record]:
    """
    What this run took from outside itself, deduplicated by path.

    The trust boundary: everything here was made somewhere this run
    cannot see, so a retraction or a reference update upstream lands
    exactly on this list.
    """
    seen: dict[str, Record] = {}
    for edge in edges:
        if edge["producer"] != EXTERNAL:
            continue
        current = seen.setdefault(edge["path"], dict(edge, consumers=[]))
        if edge["consumer"] not in current["consumers"]:
            current["consumers"].append(edge["consumer"])
    return sorted(seen.values(), key=lambda e: e["name"])


def accountability(records: list[Record]) -> Record:
    """
    How much of what this run produced can be identified by content.

    An artifact without a digest is not evidence of anything: it cannot
    be matched to a later run, and a claim about it rests on its path.
    """
    total = digested = 0
    unhashed: list[str] = []
    for record in records:
        for output in record.get("outputs", []):
            total += 1
            if output.get("sha256"):
                digested += 1
            else:
                unhashed.append(
                    f"{record['task']['id']}/"
                    f"{Path(output.get('path', '')).name}"
                )
    return {"total": total, "digested": digested, "unhashed": unhashed}


def layers(records: list[Record], edges: list[Record]) -> list[list[str]]:
    """
    Tasks arranged into dependency layers, sources first.

    A task sits one layer deeper than the deepest thing it consumes, so
    the result reads left to right as the order work actually happened.
    Any cycle (which the engine forbids) would leave tasks unplaced, so
    leftovers are appended rather than dropped.
    """
    tasks = [record["task"]["id"] for record in records]
    upstream: dict[str, set[str]] = {task: set() for task in tasks}
    for edge in edges:
        if edge["producer"] != EXTERNAL and edge["producer"] in upstream:
            upstream[edge["consumer"]].add(edge["producer"])

    depth: dict[str, int] = {}
    remaining = set(tasks)
    while remaining:
        ready = [t for t in remaining if all(u in depth for u in upstream[t])]
        if not ready:
            ready = sorted(remaining)  # a cycle; place them anyway
        for task in ready:
            depth[task] = max(
                (depth[u] + 1 for u in upstream[task]), default=0
            )
            remaining.discard(task)

    grouped: dict[int, list[str]] = {}
    for task, d in depth.items():
        grouped.setdefault(d, []).append(task)
    return [sorted(grouped[d]) for d in sorted(grouped)]


def trace(final: str, edges: list[Record], limit: int = 4) -> list[list[str]]:
    """
    How *final* came to be, as generations of ancestors.

    Breadth first and depth limited: the point is to show the shape of
    the chain, not to enumerate a large run.
    """
    parents: dict[str, set[str]] = {}
    for edge in edges:
        parents.setdefault(edge["consumer"], set()).add(edge["producer"])

    generations: list[list[str]] = []
    frontier = {final}
    seen = {final}
    while frontier and len(generations) < limit:
        nxt: set[str] = set()
        for node in frontier:
            nxt |= parents.get(node, set())
        nxt -= seen
        if not nxt:
            break
        seen |= nxt
        generations.append(sorted(nxt))
        frontier = {n for n in nxt if n != EXTERNAL}
    return generations


def terminals(records: list[Record], edges: list[Record]) -> list[str]:
    """
    Tasks nothing downstream consumed: what this run was for.
    """
    consumed = {edge["producer"] for edge in edges}
    return sorted(
        record["task"]["id"]
        for record in records
        if record["task"]["id"] not in consumed
    )


def depth_of(layered: list[list[str]]) -> int:
    """How many stages deep the run goes."""
    return len(layered)


def reuse(records: list[Record]) -> Counter[str]:
    """How many tasks ran, and how many the engine had already done."""
    return Counter(record["task"].get("status", "") for record in records)
