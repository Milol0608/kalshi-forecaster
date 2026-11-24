"""Compare the live database schema with the models; optionally add what's missing.

Catches a database that was copied or restored without some of its constraints or indexes,
which `alembic upgrade` can't see because the version stamp still says it's up to date.
Prints table/constraint names only, never data or connection details.

  python -m app.jobs.schema_check            report; exit 1 on any difference
  python -m app.jobs.schema_check --repair   add missing indexes, unique constraints and
                                             foreign keys (only those; anything else is reported)
"""

from __future__ import annotations

import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine
from sqlalchemy.schema import AddConstraint, CreateIndex

from app.db.models import Base
from app.db.session import get_engine

REPAIRABLE = {"add_index", "add_constraint", "add_fk"}


def differences(conn: Connection) -> list:
    return compare_metadata(MigrationContext.configure(conn), Base.metadata)


def describe(diff) -> str:
    if isinstance(diff, list):  # column-level changes come as a list of tuples
        return f"{diff[0][0]} {diff[0][2]}.{diff[0][3]}"
    kind, obj = diff[0], diff[1]
    table = getattr(obj, "table", None)
    cols = ", ".join(c.name for c in getattr(obj, "columns", []))
    return f"{kind} {getattr(table, 'name', obj)}({cols}) {getattr(obj, 'name', '') or ''}".rstrip()


def repair(engine: Engine) -> tuple[int, list[str]]:
    """Add each missing index/constraint in its own transaction. Returns (added, failures)."""
    with engine.connect() as conn:
        diffs = differences(conn)
    added, failed = 0, []
    # Indexes and unique constraints first, so foreign keys find their targets indexed.
    for diff in sorted(diffs, key=lambda d: isinstance(d, list) or d[0] == "add_fk"):
        if isinstance(diff, list) or diff[0] not in REPAIRABLE:
            failed.append(f"not repairable here: {describe(diff)}")
            continue
        ddl = CreateIndex(diff[1]) if diff[0] == "add_index" else AddConstraint(diff[1])
        try:
            with engine.begin() as conn:
                conn.execute(ddl)
            added += 1
        except Exception as exc:  # e.g. duplicate rows block a unique constraint
            failed.append(f"{describe(diff)}: {type(exc).__name__}: {str(exc).splitlines()[0]}")
    return added, failed


def main(argv: list[str]) -> int:
    engine = get_engine()
    if "--repair" in argv:
        added, failed = repair(engine)
        print(f"schema repair: added {added}")
        for f in failed:
            print("schema repair failed:", f)
    with engine.connect() as conn:
        diffs = differences(conn)
    for d in diffs:
        print("schema difference:", describe(d))
    print(f"schema check: {len(diffs)} difference(s)")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
