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
Shared fixtures.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from horus_runtime.context import HorusContext, _runtime_ctx
from horus_runtime.registry.auto_registry import AutoRegistry

from horus_lineage.config import ENV_DIGESTS, ENV_ROOT


@pytest.fixture(scope="session", autouse=True)
def init_registry() -> None:
    """
    Import every installed ``horus.*`` plugin so registry fields resolve.
    """
    AutoRegistry.init_registry()


@pytest.fixture
def horus_context() -> Generator[HorusContext]:
    """
    A fresh context per test, reset afterwards so nothing leaks.
    """
    ctx = HorusContext()
    ctx.bus.start()
    token = _runtime_ctx.set(ctx)
    try:
        yield ctx
    finally:
        _runtime_ctx.reset(token)


@pytest.fixture
def records_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    """
    Point the recorder at a temporary directory for one test.
    """
    root = tmp_path / "records"
    monkeypatch.setenv(ENV_ROOT, str(root))
    monkeypatch.delenv(ENV_DIGESTS, raising=False)
    yield root
