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
Where records go and how much work goes into them.

Everything is read from the environment once per run, so a run's settings
cannot change under it halfway through.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ENV_ROOT = "HORUS_LINEAGE_DIR"
"""Where run directories are written. Accepts ``@run`` (see below)."""

ENV_DIGESTS = "HORUS_LINEAGE_DIGESTS"
"""Set to a false-ish value to record paths and sizes but no digests."""

BESIDE_THE_RUN = "@run"
"""
``HORUS_LINEAGE_DIR=@run`` writes records under the workflow's own run
directory instead of the launch host default, so lineage travels with the
results it describes. Good when output directories are archived, bad when
they are purgeable scratch.
"""

DEFAULT_ROOT = Path.home() / ".horus-lineage"

_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class LineageConfig:
    """
    Resolved settings for one run.
    """

    root: Path | None
    """
    Directory to write run directories into, or ``None`` for beside the
    run, which is only knowable once the workflow is in hand.
    """

    digests: bool
    """Whether to record content digests (ADR 0003)."""

    @classmethod
    def from_env(cls) -> "LineageConfig":
        """
        Read settings from the environment, falling back to the launch
        host default.
        """
        raw = os.environ.get(ENV_ROOT, "").strip()
        root = None if raw == BESIDE_THE_RUN else Path(raw or DEFAULT_ROOT)
        return cls(root=root, digests=cls._flag(ENV_DIGESTS, True))

    def resolve_root(self, run_directory: Path) -> Path:
        """
        The directory run directories go under, given this run's own
        output root.
        """
        if self.root is not None:
            return self.root
        return run_directory / ".horus-lineage"

    @staticmethod
    def _flag(name: str, default: bool) -> bool:
        """
        Read a boolean environment variable.
        """
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() not in _FALSE
