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
One page for one run: what it did, where, and what it produced.

    horus-lineage report ~/.horus-lineage/<run-id> --out run.html

A run directory is JSON, which is the right shape for a reader and the
wrong shape for a person deciding whether a run is worth investigating.
This turns one into a page that answers that in a glance and keeps the
detail a click away.

Same rules as the record itself: no scripts, nothing fetched, no
generation timestamp. The same run directory renders to the same bytes,
so two people comparing pages are comparing runs.

WHAT IT WILL NOT DO
-------------------
Report a duration per task. The record has none, and wall clock would be
indicative rather than measured anyway (ADR 0008). The run's own elapsed
time is real and is shown, because run.json brackets it directly.
"""

import argparse
import html
import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from horus_lineage import graph
from horus_lineage.style import STYLE, masthead

Record = dict[str, Any]
"""One task record, as ADR 0005 describes it."""

PLAN = "run.json"
DEFINITION = "definition.json"
MERGED = "records.jsonl"

A_MINUTE = 90
"""Past this many seconds, minutes read better than seconds."""

SEVERAL_MACHINES = 2
"""Below this, "where it ran" answers a question nobody asked."""

STATUS_KIND = {
    "completed": "ok",
    "skipped": "",
    "failed": "bad",
    "canceled": "bad",
}


def esc(value: Any) -> str:
    """HTML-escape anything, including None."""
    return html.escape("" if value is None else str(value))


def tag(text: str, kind: str = "") -> str:
    """A small badge. Colour only where it means something."""
    return f'<span class="tag {kind}">{esc(text)}</span>'


def load(run_dir: str | Path) -> tuple[Record, list[Record]]:
    """The plan and every task record, whichever layout was written."""
    run_dir = Path(run_dir)
    plan_path = run_dir / PLAN
    if not plan_path.exists():
        raise SystemExit(f"horus-lineage: no {PLAN} in {run_dir}")

    merged = run_dir / MERGED
    if merged.exists():
        records = [
            json.loads(line)
            for line in merged.read_text().splitlines()
            if line.strip()
        ]
    else:
        records = [
            json.loads(p.read_text())
            for p in sorted(run_dir.glob("*.json"))
            if p.name not in (PLAN, DEFINITION)
        ]
    plan = json.loads(plan_path.read_text())
    definition_path = run_dir / DEFINITION
    # Declared edges reach the artifacts a digest cannot: folders, and
    # subworkflow ports, which have no file behind them.
    plan["_definition"] = (
        json.loads(definition_path.read_text())
        if definition_path.exists()
        else {}
    )
    return plan, records


def elapsed(plan: Record) -> str | None:
    """
    How long the run took, or None while it is unfinished.

    This one is measured rather than estimated: run.json brackets the
    whole run, so it is wall clock for something that actually happened.
    """
    started, finished = plan.get("started_at"), plan.get("finished_at")
    if not started or not finished:
        return None
    delta = (
        datetime.fromisoformat(finished) - datetime.fromisoformat(started)
    ).total_seconds()
    if delta < 1:
        return f"{delta * 1000:.0f} ms"
    if delta < A_MINUTE:
        return f"{delta:.1f} s"
    return f"{delta / 60:.1f} min"


def counts(items: Iterable[tuple[str, Any, str]]) -> str:
    """The row of figures a reader takes in first."""
    tiles = "".join(
        f'<div class="count{(" " + kind) if kind else ""}">'
        f"<b>{esc(value)}</b><span>{esc(label)}</span></div>"
        for label, value, kind in items
    )
    return f'<div class="counts">{tiles}</div>'


def headline(
    plan: Record,
    records: list[Record],
    edges: list[Record],
    layered: list[list[str]],
) -> str:
    """
    What this run can account for, before anything else.

    Not how many tasks ran. Whether every artifact it produced can be
    identified by content, what it took from outside itself, and how
    deep the chain behind the result is.
    """
    acct = graph.accountability(records)
    outside = graph.external_inputs(edges)
    status = graph.reuse(records)
    took = elapsed(plan)

    complete = bool(acct["total"]) and acct["digested"] == acct["total"]
    story = [
        f"{acct['digested']} of {acct['total']} artifacts are identified "
        "by content"
        if acct["total"]
        else "this run produced nothing"
    ]
    if outside:
        story.append(f"{len(outside)} came from outside the run")
    story.append(f"the chain is {len(layered)} deep")
    if took:
        story.append(f"it took {took}")

    tiles: list[tuple[str, Any, str]] = [
        (
            "accounted for",
            f"{round(100 * acct['digested'] / acct['total'])}%"
            if acct["total"]
            else "-",
            "" if complete else "unknown",
        ),
        ("artifacts", acct["total"], ""),
        ("from outside", len(outside), ""),
        ("stages deep", len(layered), ""),
    ]
    if status.get("skipped"):
        tiles.append(("reused", status["skipped"], ""))

    return (
        f"<h1>{esc(plan['workflow']['name'])}</h1>"
        f'<p class="lede">{esc(", ".join(story))}.</p>'
        f"{counts(tiles)}"
    )


def flow(
    records: list[Record], edges: list[Record], layered: list[list[str]]
) -> str:
    """
    The derivation, drawn: outside inputs first, then each stage.

    Laid out here rather than by a library, so the page carries no
    script and still prints.
    """
    status = {r["task"]["id"]: r["task"].get("status", "") for r in records}
    outside = graph.external_inputs(edges)
    columns: list[tuple[str, list[str]]] = []
    if outside:
        columns.append(("from outside", [e["name"] for e in outside]))
    columns += [(f"stage {i + 1}", layer) for i, layer in enumerate(layered)]
    if not columns:
        return ""

    col_w, row_h, pad = 172, 34, 16
    height = pad * 2 + max(len(items) for _, items in columns) * row_h
    width = col_w * len(columns)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="derivation across '
        f'{len(columns)} stages">'
    ]
    for c, (label, items) in enumerate(columns):
        x = c * col_w + 8
        parts.append(
            f'<text x="{x}" y="12" class="svg-label">{esc(label)}</text>'
        )
        for r, item in enumerate(items):
            y = pad + 6 + r * row_h
            kind = status.get(item)
            fill = {
                "completed": "var(--accent)",
                "skipped": "var(--steel)",
            }.get(kind or "", "var(--border)")
            opacity = ".3" if kind == "skipped" else ("1" if kind else ".5")
            parts.append(
                f'<rect x="{x}" y="{y}" rx="4" width="{col_w - 30}" '
                f'height="24" fill="hsl({fill})" fill-opacity="{opacity}" '
                'stroke="hsl(var(--border))"/>'
                f'<text x="{x + 8}" y="{y + 16}" class="svg-node">'
                f"{esc(item[:18])}</text>"
            )
            if c < len(columns) - 1:
                parts.append(
                    f'<line x1="{x + col_w - 30}" y1="{y + 12}" '
                    f'x2="{x + col_w}" y2="{y + 12}" '
                    'stroke="hsl(var(--border))" stroke-width="1.5"/>'
                )
    parts.append("</svg>")

    return (
        "<h2>How it was derived</h2>"
        '<div class="panel"><div class="tablewrap">'
        f"{''.join(parts)}</div>"
        '<div class="barkey" style="margin-top:.85rem">'
        '<span><i class="dot" style="background:hsl(var(--accent))"></i>'
        "executed</span>"
        '<span><i class="dot" style="background:hsl(var(--steel));'
        'opacity:.3"></i>reused from cache</span>'
        '<span><i class="dot" style="background:hsl(var(--border))"></i>'
        "from outside</span></div></div>"
    )


def boundary(edges: list[Record]) -> str:
    """
    What this run trusted from elsewhere.

    The list a person acts on when data upstream is retracted or a
    reference is corrected, so it gets a section rather than a fold.
    """
    outside = graph.external_inputs(edges)
    if not outside:
        return ""
    rows = "".join(
        "<tr>"
        f'<td class="mono">{esc(item["name"])}</td>'
        f'<td class="mono">{esc(", ".join(item["consumers"]))}</td>'
        f'<td class="hash">'
        f"{esc(item['sha256'][:16]) if item['sha256'] else 'no digest'}</td>"
        "</tr>"
        for item in outside
    )
    return (
        "<h2>Taken from outside</h2>"
        '<div class="panel"><p class="note">These were not produced here. '
        "If one is withdrawn or corrected, everything downstream of it is "
        "in question.</p>"
        '<div class="tablewrap"><table><thead><tr><th>Artifact</th>'
        "<th>Read by</th><th>sha256</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div>"
    )


def provenance(records: list[Record], edges: list[Record]) -> str:
    """For each thing this run was for, the generations behind it."""
    final = graph.terminals(records, edges)
    if not final:
        return ""
    blocks = ""
    for task in final:
        chain = graph.trace(task, edges)
        if not chain:
            continue
        steps = [f"<b>{esc(task)}</b>"]
        for generation in chain:
            steps.append(
                '<span class="mono">'
                + esc(
                    ", ".join(
                        "outside" if n == graph.EXTERNAL else n
                        for n in generation
                    )
                )
                + "</span>"
            )
        arrow = ' <span style="color:hsl(var(--accent))">&larr;</span> '
        blocks += f'<p style="margin:.35rem 0">{arrow.join(steps)}</p>'
    if not blocks:
        return ""
    return (
        f'<h2>What the result rests on</h2><div class="panel">{blocks}</div>'
    )


def unaccounted(records: list[Record]) -> str:
    """
    Artifacts with no digest, stated. A page that omits them reads as
    complete accounting when it is not.
    """
    acct = graph.accountability(records)
    if not acct["unhashed"]:
        return ""
    items = "".join(
        f"<li><code>{esc(name)}</code></li>" for name in acct["unhashed"]
    )
    return (
        f"<details><summary>{len(acct['unhashed'])} artifacts have no "
        "digest</summary>"
        '<div class="panel warn"><p>A folder cannot be hashed, and a '
        "subworkflow port has no file behind it. These cannot be matched "
        "to a later run, so any claim about them rests on their path.</p>"
        f'<ul class="coverage">{items}</ul></div></details>'
    )


def where(records: list[Record]) -> str:
    """
    Share of the run per machine, drawn as length. Omitted entirely when
    every task ran in one place, which is most runs.
    """
    counted = Counter(
        r["target"]["location_id"]
        for r in records
        if r.get("target", {}).get("location_id")
    )
    if len(counted) < SEVERAL_MACHINES:
        return ""
    top = max(counted.values())
    rows = "".join(
        '<div class="spread-row">'
        f'<span class="mono">{esc(where_)}</span>'
        f'<span class="track"><i style="width:{100 * n / top:.4g}%">'
        "</i></span>"
        f'<span class="num">{n}</span></div>'
        for where_, n in counted.most_common()
    )
    return (
        "<h2>Where it ran</h2>"
        f'<div class="panel"><div class="spread">{rows}</div></div>'
    )


def tasks(records: list[Record]) -> str:
    """Every task, with the state the engine left it in."""
    rows = ""
    for record in sorted(records, key=lambda r: r["task"]["id"]):
        task = record["task"]
        status = task.get("status", "")
        outputs = record.get("outputs", [])
        digested = sum(1 for o in outputs if o.get("sha256"))
        rows += (
            "<tr>"
            f"<td><b>{esc(task['id'])}</b></td>"
            f"<td>{tag(status, STATUS_KIND.get(status, ''))}</td>"
            f"<td>{len(record.get('inputs', []))}</td>"
            f"<td>{len(outputs)}"
            + (
                f' <span class="hash">{digested} digested</span>'
                if digested != len(outputs)
                else ""
            )
            + "</td>"
            f'<td class="mono">'
            f"{esc(record.get('target', {}).get('kind', ''))}</td>"
            "</tr>"
        )
    return (
        f"<details><summary>All {len(records)} tasks</summary>"
        '<div class="panel tablewrap"><table><thead><tr><th>Task</th>'
        "<th>Status</th><th>Inputs</th><th>Outputs</th><th>Target</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div></details>"
    )


def produced(records: list[Record]) -> str:
    """
    What this run leaves behind, with the digest that identifies it.
    Folded: it is the longest list and the least often read.
    """
    rows = ""
    n = 0
    for record in sorted(records, key=lambda r: r["task"]["id"]):
        for output in record.get("outputs", []):
            n += 1
            digest = output.get("sha256")
            rows += (
                "<tr>"
                f'<td class="mono">{esc(Path(output.get("path", "")).name)}'
                "</td>"
                f'<td class="mono">{esc(record["task"]["id"])}</td>'
                f"<td>{esc(output.get('size', ''))}</td>"
                f'<td class="hash">{esc(digest[:16]) if digest else ""}</td>'
                "</tr>"
            )
    if not n:
        return ""
    return (
        f"<details><summary>{n} artifacts produced</summary>"
        '<div class="panel tablewrap"><table><thead><tr><th>Name</th>'
        "<th>From</th><th>Bytes</th><th>sha256</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    )


def gaps(plan: Record, records: list[Record]) -> str:
    """
    What the recorder could not capture. Folded, never dropped: a run
    that quietly recorded less than it should still looks complete.
    """
    notes = []
    missing = [r["task"]["id"] for r in records if r.get("incomplete")]
    if missing:
        notes.append(
            f"{len(missing)} records are partial: "
            + ", ".join(
                f"{t} ({', '.join(r['incomplete'])})"
                for t, r in (
                    (r["task"]["id"], r)
                    for r in records
                    if r.get("incomplete")
                )
            )
        )
    if not plan.get("finished_at"):
        notes.append(
            "This run has no finish time, so it died partway. "
            "The records here are how far it got."
        )
    if not plan.get("source"):
        notes.append(
            "No workflow file was copied, so the projected "
            "definition is the only description of the plan."
        )
    if not notes:
        return ""
    items = "".join(f"<li>{esc(note)}</li>" for note in notes)
    return (
        "<details><summary>What this run did not record</summary>"
        f'<div class="panel warn"><ul class="coverage">{items}</ul></div>'
        "</details>"
    )


def code(plan: Record) -> str:
    """The scripts this run executed, digested. The engine sees none."""
    files = plan.get("code") or []
    if not files:
        return ""
    rows = "".join(
        "<tr>"
        f'<td class="mono">{esc(Path(f["path"]).name)}</td>'
        f"<td>{esc(f.get('size', ''))}</td>"
        f'<td class="hash">{esc(f["sha256"][:16])}</td>'
        "</tr>"
        for f in files
    )
    return (
        f"<details><summary>{len(files)} code files</summary>"
        '<div class="panel"><p class="note">The engine\'s own cache '
        "cannot see these: a runtime holds its script as a path, not as "
        "bytes. These digests are the only record that the code was what "
        "it was.</p>"
        '<div class="tablewrap"><table><thead><tr><th>File</th>'
        "<th>Bytes</th><th>sha256</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div></details>"
    )


def render(plan: Record, records: list[Record]) -> str:
    """
    The whole page, as one string.

    Ordered by what someone asks of lineage: can we account for it,
    where did it come from, what did we trust from elsewhere, and what
    does the result rest on. The task list is engineering detail and
    sits at the bottom, folded.
    """
    definition = plan.get("_definition") or {}
    edges = graph.derivation(records, definition)
    layered = graph.layers(records, edges)

    body = "".join(
        [
            headline(plan, records, edges, layered),
            flow(records, edges, layered),
            boundary(edges),
            provenance(records, edges),
            unaccounted(records),
            tasks(records),
            produced(records),
            code(plan),
            gaps(plan, records),
            '<p class="note" style="margin-top:2rem">Run '
            f'<span class="hash">{esc(plan["run"])}</span>, definition '
            f'<span class="hash">'
            f"{esc(plan['definition']['sha256'][:16])}</span>. "
            "This page is a view; the run directory is the record.</p>",
        ]
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(plan['workflow']['name'])}</title>"
        f"<style>{STYLE}</style></head><body>"
        f"{masthead('horus-lineage')}"
        f"<main>{body}</main></body></html>"
    )


def main(argv: list[str] | None = None) -> int:
    """The ``horus-lineage report`` command."""
    parser = argparse.ArgumentParser(
        prog="horus-lineage report",
        description="Render one run directory as a single HTML page.",
    )
    parser.add_argument(
        "run_dir", help="a ~/.horus-lineage/<run-id> directory"
    )
    parser.add_argument(
        "--out", default="-", help="output path, or - for stdout"
    )
    args = parser.parse_args(argv)

    page = render(*load(args.run_dir))
    if args.out == "-":
        print(page)
    else:
        Path(args.out).write_text(page)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
