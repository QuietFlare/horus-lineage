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
Records what a Horus run did, without changing what it does.

Four middlewares write one JSON record per task plus one per run, into a
run directory that is moved whole and joined by content digest. See
``docs/adr/`` for the design, ADR 0005 for the record format.
"""

RECORD_FORMAT = "horus-lineage/v1"
"""
Value of the ``format`` field on every record this package writes.

Readers check it and refuse versions they do not know. A semantic change
to any field is a new version, never an edit (ADR 0005).
"""
