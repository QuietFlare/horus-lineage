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
Getting JSON onto local disk without leaving half a file behind.

Writes are local by design. A network mount or object store belongs on
the other side of an ``rsync``, not inside a middleware: ADR 0004 can
swallow an exception but it cannot rescue a hung write, which stalls the
task instead of failing it.
"""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
"""Anything that has no business in a filename."""

_MAX_STEM = 120
"""Leaves room for a suffix well inside every filesystem's limit."""


def now() -> str:
    """
    The current time as a timezone-aware ISO 8601 string.
    """
    return datetime.now(UTC).isoformat()


def canonical(payload: Any) -> bytes:
    """
    *payload* as bytes that are identical for identical content, so a
    digest over them means something across machines and runs.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest_of(payload: Any) -> str:
    """
    sha256 of *payload* in its canonical form.
    """
    return hashlib.sha256(canonical(payload)).hexdigest()


def safe_name(task_id: str) -> str:
    """
    *task_id* as a filename that cannot escape its directory.

    Task ids are workflow-author strings. Map clones carry brackets, and
    nothing stops an id holding a slash or dots, so the id is sanitized
    and disambiguated with a short digest of the original.
    """
    stem = _UNSAFE.sub("_", task_id)[:_MAX_STEM] or "task"
    suffix = hashlib.sha256(task_id.encode()).hexdigest()[:8]
    return f"{stem}.{suffix}.json"


class RunWriter:
    """
    Writes one run's records into one directory.
    """

    def __init__(self, directory: Path) -> None:
        """
        Open *directory*, creating it if it is not there yet.
        """
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, payload: Any) -> Path:
        """
        Write *payload* as JSON to *name*, replacing any previous copy in
        one step so a reader never sees a partial file.
        """
        path = self.directory / name
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(
            json.dumps(payload, indent=2, ensure_ascii=False).encode()
        )
        os.replace(temporary, path)
        return path

    def write_bytes(self, name: str, payload: bytes) -> Path:
        """
        Copy raw bytes in, for the workflow source file.
        """
        path = self.directory / name
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        return path

    def write_task(self, task_id: str, payload: Any) -> Path:
        """
        Write one task record under a filename derived from *task_id*.
        """
        return self.write(safe_name(task_id), payload)
