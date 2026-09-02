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
Reading derivation back out of records.

The fixture is a diamond, because that is the shape that catches the
mistakes: two branches from one source, joined again, so an answer that
merely walks a list looks right until it does not.

    raw.csv -> prep --+-> analyse --+-> report
                      |             |
                      +-> qc -------+
"""

from typing import Any

from horus_lineage import graph


def artifact(
    identifier: str, digest: str | None, path: str | None = None
) -> dict[str, Any]:
    """One input or output entry, as a record carries it."""
    entry: dict[str, Any] = {
        "id": identifier,
        "path": path or f"/work/{identifier}.json",
    }
    if digest is not None:
        entry["sha256"] = digest
    return entry


def task(
    identifier: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    status: str = "completed",
) -> dict[str, Any]:
    """One task record, trimmed to what derivation reads."""
    return {
        "task": {"id": identifier, "status": status},
        "inputs": inputs,
        "outputs": outputs,
    }


RAW = "a" * 64
PREPARED = "b" * 64
ANALYSED = "c" * 64
QC = "d" * 64
REPORT = "e" * 64

RECORDS = [
    task(
        "prep",
        [artifact("raw", RAW, "/data/raw.csv")],
        [artifact("prepared", PREPARED)],
    ),
    task(
        "analyse",
        [
            artifact("prepared", PREPARED),
            artifact("calibration", "f" * 64, "/data/calibration.txt"),
        ],
        [artifact("analysed", ANALYSED)],
    ),
    task(
        "qc",
        [artifact("prepared", PREPARED)],
        [artifact("qc_report", QC)],
        status="skipped",
    ),
    task(
        "report",
        [artifact("analysed", ANALYSED), artifact("qc_report", QC)],
        [artifact("report", REPORT)],
    ),
]

DEFINITION = {
    "edges": [
        {
            "source": "prep",
            "source_output": "prepared",
            "target": "analyse",
            "target_input": "prepared",
        },
        {
            "source": "prep",
            "source_output": "prepared",
            "target": "qc",
            "target_input": "prepared",
        },
        {
            "source": "artifact-raw",
            "source_output": "raw",
            "target": "prep",
            "target_input": "raw",
        },
    ]
}


class TestDerivation:
    """
    Who made what, joined on content rather than on paths.
    """

    def test_an_input_joins_to_whoever_produced_those_bytes(self) -> None:
        """
        The whole design rests on this: no paths, no work directories.
        """
        edges = graph.derivation(RECORDS, DEFINITION)
        internal = sorted(
            (e["producer"], e["consumer"])
            for e in edges
            if e["producer"] != graph.EXTERNAL
        )
        assert internal == [
            ("analyse", "report"),
            ("prep", "analyse"),
            ("prep", "qc"),
            ("qc", "report"),
        ]

    def test_an_input_nothing_produced_came_from_outside(self) -> None:
        """
        Dropping these would make a reference update look like it
        reached nothing.
        """
        edges = graph.derivation(RECORDS, DEFINITION)
        outside = sorted(
            e["name"] for e in edges if e["producer"] == graph.EXTERNAL
        )
        assert outside == ["calibration.txt", "raw.csv"]

    def test_a_declared_edge_covers_an_artifact_with_no_digest(self) -> None:
        """
        A folder digests to nothing, so without the declared fallback
        the task would read as having come from outside.
        """
        records = [
            task("prep", [], [artifact("prepared", None)]),
            task("qc", [artifact("prepared", None)], []),
        ]
        edges = graph.derivation(records, DEFINITION)
        assert [(e["producer"], e["consumer"]) for e in edges] == [
            ("prep", "qc")
        ]

    def test_a_pass_through_task_is_not_its_own_producer(self) -> None:
        """
        Copying an input to an output makes the bytes match, and a naive
        join reports the task as its own ancestor.
        """
        same = "9" * 64
        records = [
            task("make", [], [artifact("out", same)]),
            task("copy", [artifact("in", same)], [artifact("out", same)]),
        ]
        edges = graph.derivation(records, {})
        assert all(e["producer"] != e["consumer"] for e in edges)


class TestExternalInputs:
    """
    The trust boundary: what this run took from somewhere it cannot see.
    """

    def test_each_outside_artifact_appears_once(self) -> None:
        edges = graph.derivation(RECORDS, DEFINITION)
        outside = graph.external_inputs(edges)
        assert [i["name"] for i in outside] == ["calibration.txt", "raw.csv"]

    def test_it_records_every_task_that_read_one(self) -> None:
        """
        Withdraw the file and this is the list of what is in question.
        """
        shared = "7" * 64
        records = [
            task("a", [artifact("ref", shared, "/data/ref.fa")], []),
            task("b", [artifact("ref", shared, "/data/ref.fa")], []),
        ]
        outside = graph.external_inputs(graph.derivation(records, {}))
        assert outside[0]["consumers"] == ["a", "b"]


class TestAccountability:
    """
    How much of what a run produced can be identified by content.
    """

    def test_a_fully_digested_run_accounts_for_everything(self) -> None:
        acct = graph.accountability(RECORDS)
        assert acct["total"] == acct["digested"] == 4
        assert acct["unhashed"] == []

    def test_an_undigested_output_is_named(self) -> None:
        """
        Counting it silently would report complete accounting that the
        run did not achieve.
        """
        records = [task("prep", [], [artifact("folder", None)])]
        acct = graph.accountability(records)
        assert acct["digested"] == 0
        assert acct["unhashed"] == ["prep/folder.json"]


class TestLayers:
    """
    Stages, so the drawing reads in the order work happened.
    """

    def test_sources_come_first_and_joins_come_last(self) -> None:
        layered = graph.layers(RECORDS, graph.derivation(RECORDS, DEFINITION))
        assert layered == [["prep"], ["analyse", "qc"], ["report"]]

    def test_a_task_sits_below_the_deepest_thing_it_reads(self) -> None:
        """
        report reads qc (layer 1) and analyse (layer 1), so it is 2, not
        1, even though one of its inputs was ready earlier.
        """
        layered = graph.layers(RECORDS, graph.derivation(RECORDS, DEFINITION))
        assert layered[-1] == ["report"]

    def test_every_task_is_placed(self) -> None:
        """
        A task missing from the drawing is worse than an ugly drawing.
        """
        layered = graph.layers(RECORDS, graph.derivation(RECORDS, DEFINITION))
        placed = {t for layer in layered for t in layer}
        assert placed == {"prep", "analyse", "qc", "report"}

    def test_unrelated_tasks_share_the_first_layer(self) -> None:
        records = [task("a", [], []), task("b", [], [])]
        assert graph.layers(records, []) == [["a", "b"]]


class TestTrace:
    """
    The chain behind a result, as generations.
    """

    def test_it_walks_back_to_the_outside(self) -> None:
        edges = graph.derivation(RECORDS, DEFINITION)
        chain = graph.trace("report", edges)
        assert chain[0] == ["analyse", "qc"]
        assert graph.EXTERNAL in chain[-1]

    def test_it_stops_at_the_limit(self) -> None:
        """
        The point is the shape of the chain, not every ancestor in a
        large run.
        """
        edges = graph.derivation(RECORDS, DEFINITION)
        assert len(graph.trace("report", edges, limit=1)) == 1

    def test_a_task_with_no_inputs_has_no_chain(self) -> None:
        assert graph.trace("prep", []) == []


class TestTerminals:
    """
    What the run was for: whatever nothing downstream consumed.
    """

    def test_the_final_output_is_terminal(self) -> None:
        edges = graph.derivation(RECORDS, DEFINITION)
        assert graph.terminals(RECORDS, edges) == ["report"]

    def test_a_run_where_nothing_is_consumed_is_all_terminal(self) -> None:
        records = [task("a", [], []), task("b", [], [])]
        assert graph.terminals(records, []) == ["a", "b"]


class TestReuse:
    """
    How much the engine had already done.
    """

    def test_it_counts_each_status(self) -> None:
        counted = graph.reuse(RECORDS)
        assert counted["completed"] == 3
        assert counted["skipped"] == 1
