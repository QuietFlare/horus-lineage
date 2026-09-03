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
Tests for the projections, which need no run to exercise.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from horus_builtin.artifact.file import FileArtifact
from horus_runtime.core.target.channel import RemoteDirEntry
from horus_runtime.logging import horus_logger

from horus_lineage.config import LineageConfig
from horus_lineage.record import (
    ArtifactReader,
    _instant,
    _probe_manifest,
    code_files,
    labels_of,
    read_fingerprint,
)
from horus_lineage.session import LineageSession


class Unlabelled:
    """
    An artifact from an engine predating ``BaseArtifact.labels``.
    """

    id = "measurements"
    path = Path("/data/x.csv")


class TestLabelsOf:
    """
    Domain metadata, read defensively.

    A recorder that raised on an older engine would fail the run it is
    supposed to observe, so every shape short of a string mapping reads
    as "no labels".
    """

    def test_an_engine_without_the_field_reports_none(self) -> None:
        """
        The field arrived upstream after this recorder did.
        """
        assert labels_of(Unlabelled()) == {}  # type: ignore[arg-type]

    def test_an_unlabelled_artifact_reports_none(self) -> None:
        """
        The common case, and it must not add an empty key to records.
        """
        artifact = FileArtifact(id="measurements", path=Path("/data/x.csv"))
        assert labels_of(artifact) == {}

    def test_string_labels_survive(self) -> None:
        """
        What a reader groups on.
        """
        artifact = FileArtifact(id="scored", path=Path("/data/x.parquet"))
        labels = {"subject": "batch_017", "role": "measurement"}
        object.__setattr__(artifact, "labels", dict(labels))
        assert labels_of(artifact) == labels

    def test_values_a_reader_cannot_compare_are_dropped(self) -> None:
        """
        Labels are index keys. A value that is not a string is worse than
        an absent one, because it looks groupable and is not.
        """
        artifact = FileArtifact(id="scored", path=Path("/data/x.parquet"))
        mixed: dict[Any, Any] = {"subject": "batch_017", "replicate": 3}
        object.__setattr__(artifact, "labels", mixed)
        assert labels_of(artifact) == {"subject": "batch_017"}

    def test_something_that_is_not_a_mapping_reports_none(self) -> None:
        """
        A plugin could put anything there. Refuse rather than guess.
        """
        artifact = FileArtifact(id="scored", path=Path("/data/x.parquet"))
        object.__setattr__(artifact, "labels", ["subject=batch_017"])
        assert labels_of(artifact) == {}


def _owner(fields: dict[str, Any], declared: list[Path] | None) -> Any:
    """A runtime or executor stand-in. ``None`` means no accessor."""
    owner = SimpleNamespace(model_dump=lambda **_kwargs: dict(fields))
    if declared is not None:
        owner.local_files = lambda: list(declared)
    return owner


class TestCodeFiles:
    """
    Local files come from ``local_files()`` and carry their field name.
    """

    def test_a_declared_file_is_digested_under_its_field(
        self, tmp_path: Path
    ) -> None:
        """
        The role is the field the path came from, ``script`` here.
        """
        script = tmp_path / "prep.py"
        script.write_text("print(1)\n")
        task: Any = SimpleNamespace(
            runtime=_owner({"script": str(script)}, [script]),
            executor=_owner({}, []),
        )
        [entry] = code_files(task)
        assert entry["role"] == "script"
        assert entry["path"] == str(script)
        assert entry["size"] == script.stat().st_size

    def test_an_executor_file_is_included(self, tmp_path: Path) -> None:
        """
        A conda environment file is code for impact purposes.
        """
        env = tmp_path / "environment.yaml"
        env.write_text("dependencies: []\n")
        task: Any = SimpleNamespace(
            runtime=_owner({}, []),
            executor=_owner({"environment_file": str(env)}, [env]),
        )
        [entry] = code_files(task)
        assert entry["role"] == "environment_file"

    def test_an_owner_without_the_accessor_is_scanned(
        self, tmp_path: Path
    ) -> None:
        """
        A third-party runtime older than 0.5.0 still gets its script.
        """
        script = tmp_path / "run.sh"
        script.write_text("true\n")
        task: Any = SimpleNamespace(
            runtime=_owner({"entry": str(script)}, None),
            executor=_owner({}, None),
        )
        assert [e["role"] for e in code_files(task)] == ["entry"]

    def test_a_missing_file_is_left_out(self, tmp_path: Path) -> None:
        """
        A path that does not resolve cannot be digested.
        """
        task: Any = SimpleNamespace(
            runtime=_owner({}, [tmp_path / "gone.py"]),
            executor=_owner({}, []),
        )
        assert code_files(task) == []

    def test_an_accessor_that_raises_is_tolerated(self) -> None:
        """
        ADR 0004: a broken plugin must not fail the run.
        """
        runtime = _owner({}, [])
        runtime.local_files = lambda: 1 / 0
        task: Any = SimpleNamespace(runtime=runtime, executor=_owner({}, []))
        assert code_files(task) == []


class TestInstant:
    """
    Task timestamps, as strings a reader can order.
    """

    def test_an_aware_datetime_keeps_its_offset(self) -> None:
        """
        The engine stamps in UTC.
        """
        stamp = datetime(2026, 9, 1, 14, 20, 2, tzinfo=UTC)
        assert _instant(stamp) == "2026-09-01T14:20:02+00:00"

    def test_a_naive_datetime_is_read_as_utc(self) -> None:
        """
        A timestamp without an offset cannot be ordered across hosts.
        """
        assert _instant(datetime(2026, 9, 1, 14, 20, 2)) == (
            "2026-09-01T14:20:02+00:00"
        )

    def test_anything_else_is_null(self) -> None:
        """
        A skipped task has no stamps.
        """
        assert _instant(None) is None
        assert _instant("2026-09-01") is None


def _session(tmp_path: Path) -> LineageSession:
    return LineageSession(
        run="run",
        directory=tmp_path,
        config=LineageConfig(root=tmp_path, digests=True, merge=False),
        definition_sha256="abc",
    )


class TestManifestProbe:
    """
    A confirmed skip without a manifest is reported once per run.
    """

    @pytest.fixture
    def warnings(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Capture what the recorder logs."""
        seen: list[str] = []
        monkeypatch.setattr(horus_logger.log, "warning", seen.append)
        return seen

    @staticmethod
    def _task(skip_reason: str | None) -> Any:
        reason = (
            None if skip_reason is None else SimpleNamespace(value=skip_reason)
        )
        return SimpleNamespace(id="prep", skip_reason=reason)

    def test_a_confirmed_skip_warns_once(
        self, tmp_path: Path, warnings: list[str]
    ) -> None:
        """
        Every task in a cached run would hit this, one warning is enough.
        """
        session = _session(tmp_path)
        skipped: Any = SimpleNamespace(value="skipped")
        _probe_manifest(self._task("complete"), skipped, session)
        _probe_manifest(self._task("complete"), skipped, session)
        assert len(warnings) == 1
        assert "prep" in warnings[0]

    def test_an_executed_task_is_silent(
        self, tmp_path: Path, warnings: list[str]
    ) -> None:
        """
        An executed task may never have had a manifest.
        """
        completed: Any = SimpleNamespace(value="completed")
        _probe_manifest(self._task(None), completed, _session(tmp_path))
        assert warnings == []

    def test_an_inactive_skip_is_silent(
        self, tmp_path: Path, warnings: list[str]
    ) -> None:
        """
        A branch not taken never wrote a manifest.
        """
        skipped: Any = SimpleNamespace(value="skipped")
        _probe_manifest(self._task("inactive"), skipped, _session(tmp_path))
        assert warnings == []


class FakeRemoteTarget:
    """
    A target whose files live elsewhere, answering over a channel.
    """

    kind = "fake"

    def __init__(self, listing: list[RemoteDirEntry] | None) -> None:
        """``None`` refuses every listing."""
        self.listing = listing
        self.resolved_working_directory = "/remote/work"
        self.files: dict[str, bytes] = {}

    def path_on_target(self, artifact: Any) -> str:
        """Artifacts live under one remote directory."""
        return f"/remote/data/{Path(str(artifact.path)).name}"

    async def list_dir(self, _path: str) -> list[RemoteDirEntry]:
        """The configured listing, or a refusal."""
        if self.listing is None:
            raise OSError("listing refused")
        return self.listing

    async def get_file(self, path: str) -> bytes:
        """Only files put there by a test exist."""
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


def _entry(path: str, size: int) -> RemoteDirEntry:
    return RemoteDirEntry(
        name=Path(path).name, path=path, is_dir=False, size=size
    )


class TestArtifactReaderOnARemoteTarget:
    """
    Sizes and digests resolved through a target that is not local.
    """

    async def test_size_comes_from_the_listing(self) -> None:
        """
        The store offers a digest and no size, so the listing is asked.
        """
        target = FakeRemoteTarget([_entry("/remote/data/x.csv", 812)])
        reader = ArtifactReader(target, digests=False)  # type: ignore[arg-type]
        artifact = FileArtifact(id="x", path=Path("/data/x.csv"))
        entry = await reader.entry(artifact, known_digest="a" * 64)
        assert entry == {
            "id": "x",
            "path": "/remote/data/x.csv",
            "size": 812,
            "sha256": "a" * 64,
        }

    async def test_a_refused_listing_leaves_size_out(self) -> None:
        """
        A missing size is normal, not an error (ADR 0003).
        """
        target = FakeRemoteTarget(None)
        reader = ArtifactReader(target, digests=False)  # type: ignore[arg-type]
        artifact = FileArtifact(id="x", path=Path("/data/x.csv"))
        entry = await reader.entry(artifact)
        assert "size" not in entry
        assert "sha256" not in entry

    async def test_the_listing_is_read_once_per_directory(self) -> None:
        """
        A directory of a thousand outputs is listed once, not a thousand
        times.
        """
        target = FakeRemoteTarget([_entry("/remote/data/x.csv", 1)])
        calls = 0
        original = target.list_dir

        async def counted(_path: str) -> list[RemoteDirEntry]:
            nonlocal calls
            calls += 1
            return await original(_path)

        target.list_dir = counted  # type: ignore[method-assign]
        reader = ArtifactReader(target, digests=False)  # type: ignore[arg-type]
        for name in ("x.csv", "y.csv"):
            await reader.entry(FileArtifact(id=name, path=Path(name)))
        assert calls == 1


class TestReadFingerprintOnARemoteTarget:
    """
    The manifest is fetched over the target's channel.
    """

    async def test_it_reads_the_manifest_from_the_workdir(self) -> None:
        """
        The engine files it under the target's working directory.
        """
        target = FakeRemoteTarget([])
        target.files["/remote/work/.horus/prep.json"] = (
            b'{"inputs": {"raw": "ab"}}'
        )
        task: Any = SimpleNamespace(id="prep", target=target)
        assert await read_fingerprint(task) == {"inputs": {"raw": "ab"}}

    async def test_a_missing_manifest_is_none(self) -> None:
        """
        A fetch that fails is a fallback to hashing, not a failure.
        """
        task: Any = SimpleNamespace(id="prep", target=FakeRemoteTarget([]))
        assert await read_fingerprint(task) is None

    async def test_a_corrupt_manifest_is_none(self) -> None:
        """
        Half a file is worth nothing.
        """
        target = FakeRemoteTarget([])
        target.files["/remote/work/.horus/prep.json"] = b"{"
        task: Any = SimpleNamespace(id="prep", target=target)
        assert await read_fingerprint(task) is None
