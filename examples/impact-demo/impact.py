"""
A stand-in for Clew's extract-horus, reading only a run directory.

Answers "if this file changes, which tasks are affected, and where do they
run" using nothing but the records. Deliberately small: the point is to
check that the records carry enough, not to build the real extractor.
"""

import hashlib
import json
import sys
from pathlib import Path


def load(run_dir):
    """Every task record in a run directory, plus its definition."""
    records = {}
    for path in sorted(run_dir.glob("*.json")):
        if path.name in ("run.json", "definition.json"):
            continue
        record = json.loads(path.read_text())
        records[record["task"]["id"]] = record
    definition = json.loads((run_dir / "definition.json").read_text())
    return records, definition


def downstream(definition):
    """task -> tasks that consume something it produces, from the edges."""
    children = {}
    for edge in definition["edges"]:
        children.setdefault(edge["source"], set()).add(edge["target"])
    return children


def affected(run_dir, changed):
    """
    Which tasks a change to *changed* reaches.

    Returns the tasks that certainly re-run and the transitive closure
    that might.
    """
    records, definition = load(run_dir)
    children = downstream(definition)
    digest = hashlib.sha256(Path(changed).read_bytes()).hexdigest()
    target = str(Path(changed).resolve())

    direct = set()
    for task_id, record in records.items():
        # An input this task consumes, matched by path or by content.
        for entry in record["inputs"]:
            if entry["path"] == target or entry.get("sha256") == digest:
                direct.add(task_id)
        # A script or environment file this task reads.
        for entry in record["code"]:
            if entry["path"] == target:
                direct.add(task_id)

    closure, queue = set(direct), list(direct)
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in closure:
                closure.add(child)
                queue.append(child)

    where = {t: records[t]["target"]["location_id"] for t in closure}
    return direct, closure, where


if __name__ == "__main__":
    run_dir = Path(sys.argv[1])
    changed = sys.argv[2]
    direct, closure, where = affected(run_dir, changed)
    print(f"changed: {changed}")
    print(f"  certainly re-runs : {sorted(direct)}")
    print(f"  upper bound       : {sorted(closure)}")
    for task, location in sorted(where.items()):
        print(f"    {task:10} runs on {location}")
