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
The lineage page.

A rendered page is the thing most likely to be detached from its records
and quoted a year later, so what it must not do matters as much as what
it shows.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from horus_lineage import report
from tests.unit.test_graph import DEFINITION, RECORDS

BRAND_FACES = 3
"""Inter regular and semibold, plus Inter Tight for display."""

VISIBLE_WORD_BUDGET = 200
"""What fits on a first screen before anything is expanded."""

PLAN: dict[str, Any] = {
    "format": "horus-lineage/v1",
    "run": "d79086aa31e44bdb",
    "workflow": {"id": "81cc0410", "slug": None, "name": "Impact probe"},
    "started_at": "2026-09-02T09:01:34.050766+00:00",
    "finished_at": "2026-09-02T09:01:36.115423+00:00",
    "status": "completed",
    "definition": {"file": "definition.json", "sha256": "424fb10b" * 8},
    "source": None,
    "code": [
        {
            "path": "/w/scripts/prep.py",
            "size": 341,
            "sha256": "1ff65be4" * 8,
            "role": "script",
        }
    ],
    "tasks": ["prep", "analyse", "qc", "report"],
    "_definition": DEFINITION,
}


@pytest.fixture
def page() -> str:
    """The whole page for the diamond fixture."""
    return report.render(PLAN, RECORDS)


class TestSelfContained:
    """
    A run directory travels. Its page has to travel with it.
    """

    def test_it_runs_no_scripts(self, page: str) -> None:
        """
        Including the derivation drawing, which is laid out in Python
        rather than by a library.
        """
        assert "<script" not in page.lower()

    def test_it_fetches_nothing(self, page: str) -> None:
        """
        An offline reader must see the same page as an online one.
        """
        assert "http://" not in page
        assert "https://" not in page
        assert "<link" not in page.lower()

    def test_the_brand_faces_are_embedded(self, page: str) -> None:
        """
        Named-only would degrade to system sans wherever Inter is not
        installed, which is most machines.
        """
        assert page.count("@font-face") == BRAND_FACES
        assert "data:font/woff2;base64" in page


class TestReproducible:
    """
    Two people comparing pages should be comparing runs.
    """

    def test_the_same_run_renders_the_same_bytes(self) -> None:
        """
        Byte equality is what makes two pages comparable by diff.
        """
        assert report.render(PLAN, RECORDS) == report.render(PLAN, RECORDS)

    def test_no_generation_time_is_stamped_in(self, page: str) -> None:
        """
        The run's own timestamps appear; the moment of rendering must
        not, or a rerun diffs against itself.
        """
        assert "2026-09-02T09:01:34" not in page


class TestWhatItLeadsWith:
    """
    Lineage answers accounting first, not how many tasks ran.
    """

    def test_it_states_what_can_be_identified_by_content(
        self, page: str
    ) -> None:
        """
        Accounting leads, because it bounds every other claim.
        """
        assert "4 of 4 artifacts are identified by content" in page

    def test_it_states_what_came_from_outside(self, page: str) -> None:
        """
        What the run did not make is what it cannot vouch for.
        """
        assert "2 came from outside the run" in page

    def test_it_states_how_deep_the_chain_is(self, page: str) -> None:
        """
        Depth is how far a correction upstream would travel.
        """
        assert "the chain is 3 deep" in page

    def test_it_reports_the_runs_own_elapsed_time(self, page: str) -> None:
        """
        Measured, not estimated: run.json brackets the whole run.
        """
        assert "2.1 s" in page

    def test_an_unfinished_run_reports_no_time(self) -> None:
        """
        Without an end there is no elapsed time to report.
        """
        plan = dict(PLAN, finished_at=None)
        assert report.elapsed(plan) is None


class TestDerivationDrawing:
    """
    The flow, as inline SVG.
    """

    def test_every_task_appears_as_a_node(self, page: str) -> None:
        """
        A task missing from the drawing is worse than an ugly drawing.
        """
        drawing = re.search(r"<svg.*?</svg>", page, re.S)
        assert drawing is not None
        for task in ("prep", "analyse", "qc", "report"):
            assert task in drawing.group(0)

    def test_outside_inputs_get_their_own_column(self, page: str) -> None:
        """
        The boundary is visible in the shape, not only in the prose.
        """
        assert "from outside" in page

    def test_stages_are_labelled_in_order(self, page: str) -> None:
        """
        The columns are meaningless unless they say what they are.
        """
        assert "stage 1" in page
        assert "stage 3" in page

    def test_the_drawing_carries_a_text_alternative(self, page: str) -> None:
        """
        A page that prints and gets read aloud needs the shape stated.
        """
        assert 'role="img"' in page
        assert "aria-label" in page


class TestTrustBoundary:
    """
    What the run took from elsewhere gets a section, not a fold.
    """

    def test_outside_artifacts_are_listed(self, page: str) -> None:
        """
        Named, so a withdrawal upstream can be matched against them.
        """
        assert "Taken from outside" in page
        assert "raw.csv" in page
        assert "calibration.txt" in page

    def test_it_names_who_read_each_one(self, page: str) -> None:
        """
        Withdraw the file and this is what is in question.
        """
        after = page.split("Taken from outside", maxsplit=1)[1]
        boundary = after.split("<h2>", maxsplit=1)[0]
        assert "prep" in boundary

    def test_a_run_with_no_outside_inputs_omits_the_section(self) -> None:
        """
        An empty trust boundary is not a finding worth a heading.
        """
        records = [
            {
                "task": {"id": "solo", "status": "completed"},
                "inputs": [],
                "outputs": [],
            }
        ]
        assert "Taken from outside" not in report.render(PLAN, records)


class TestHonesty:
    """
    What is missing is stated, never quietly dropped.
    """

    def test_an_undigested_artifact_is_named(self) -> None:
        """
        Naming it is the difference between a gap and a silent one.
        """
        records = [
            {
                "task": {"id": "prep", "status": "completed"},
                "inputs": [],
                "outputs": [{"id": "folder", "path": "/w/out/"}],
            }
        ]
        page = report.render(PLAN, records)
        assert "1 artifacts have no digest" in page
        assert "prep/out" in page

    def test_a_fully_digested_run_says_nothing_about_gaps(
        self, page: str
    ) -> None:
        """
        A disclaimer with nothing behind it teaches readers to skip them.
        """
        assert "have no digest" not in page

    def test_a_run_that_died_partway_says_so(self) -> None:
        """
        A partial run read as complete is the costliest misreading here.
        """
        page = report.render(dict(PLAN, finished_at=None), RECORDS)
        assert "died partway" in page

    def test_code_digests_explain_why_they_exist(self, page: str) -> None:
        """
        The engine re-runs on an edit. The digests say which file.
        """
        assert "name which file changed" in page

    def test_the_page_says_it_is_not_the_record(self, page: str) -> None:
        """
        The page is a projection; the records are the evidence.
        """
        assert "the run directory is the record" in page


class TestDetailIsFolded:
    """
    Scannable first, complete on expansion.
    """

    def test_the_task_list_is_behind_a_summary(self, page: str) -> None:
        """
        The count belongs in the summary so it reads without expanding.
        """
        assert "<summary>All 4 tasks</summary>" in page

    def test_artifacts_and_code_are_folded(self, page: str) -> None:
        """
        Detail stays reachable without crowding the first screen.
        """
        folds = re.findall(r"<summary>([^<]+)</summary>", page)
        assert any("artifacts produced" in f for f in folds)
        assert any("code files" in f for f in folds)

    def test_little_prose_is_visible_before_expanding(self, page: str) -> None:
        """
        A page someone shows their management opens as a picture, not an
        essay.
        """
        visible = re.sub(r"<style>.*?</style>", "", page, flags=re.S)
        visible = re.sub(r"<details>.*?</details>", "", visible, flags=re.S)
        visible = re.sub(r"<svg.*?</svg>", "", visible, flags=re.S)
        words = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", visible)).split()
        assert len(words) < VISIBLE_WORD_BUDGET


class TestLoading:
    """
    Reading a run directory off disk, in either layout.
    """

    def _write(self, directory: Path, merged: bool) -> None:
        (directory / "run.json").write_text(json.dumps(PLAN))
        (directory / "definition.json").write_text(json.dumps(DEFINITION))
        if merged:
            (directory / "records.jsonl").write_text(
                "\n".join(json.dumps(r) for r in RECORDS) + "\n"
            )
        else:
            for record in RECORDS:
                name = f"{record['task']['id']}.abcd1234.json"
                (directory / name).write_text(json.dumps(record))

    def test_the_per_task_layout_loads(self, tmp_path: Path) -> None:
        """
        One file per task is what the recorder writes by default.
        """
        self._write(tmp_path, merged=False)
        plan, records = report.load(tmp_path)
        assert plan["run"] == PLAN["run"]
        assert len(records) == len(RECORDS)

    def test_the_merged_layout_loads(self, tmp_path: Path) -> None:
        """
        HORUS_LINEAGE_MERGE folds the parts into records.jsonl. Both
        layouts describe the same run.
        """
        self._write(tmp_path, merged=True)
        _, records = report.load(tmp_path)
        assert len(records) == len(RECORDS)

    def test_the_definition_travels_with_the_plan(
        self, tmp_path: Path
    ) -> None:
        """
        Declared edges reach the artifacts a digest cannot.
        """
        self._write(tmp_path, merged=False)
        plan, _ = report.load(tmp_path)
        assert plan["_definition"]["edges"]

    def test_a_directory_without_a_plan_is_refused(
        self, tmp_path: Path
    ) -> None:
        """
        Without run.json there is no run to report on.
        """
        with pytest.raises(SystemExit):
            report.load(tmp_path)


class TestCommand:
    """
    ``horus-lineage report``.
    """

    def test_it_writes_the_page(self, tmp_path: Path) -> None:
        """
        The doctype is what makes the output a page and not a fragment.
        """
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        TestLoading()._write(run_dir, merged=False)
        out = tmp_path / "page.html"
        assert report.main([str(run_dir), "--out", str(out)]) == 0
        assert out.read_text().startswith("<!doctype html>")

    def test_it_writes_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        So the page can be piped without a temporary file.
        """
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        TestLoading()._write(run_dir, merged=False)
        report.main([str(run_dir)])
        assert "<!doctype html>" in capsys.readouterr().out
