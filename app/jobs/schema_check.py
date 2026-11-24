"""Compare the live database schema with the models; optionally add what's missing.

Catches a database that was copied or restored without some of its constraints or indexes,
which `alembic upgrade` can't see because the version stamp still says it's up to date.
Prints table/constraint names only, never data or connection details.

  python -m app.jobs.schema_check            report; exit 1 on any difference
  python -m app.jobs.schema_check --repair   add missing primary keys, indexes, unique
                                             constraints and foreign keys (only those; anything
                                             else is reported)
"""

from __future__ import annotations

import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.schema import AddConstraint, CreateIndex

from app.db.models import Base
from app.db.session import get_engine

REPAIRABLE = {"sync_sequence", "add_pk", "add_index", "add_constraint", "add_fk"}
ORDER = {"sync_sequence": -1, "add_pk": 0, "add_index": 1, "add_constraint": 1, "add_fk": 2}  # FKs need their target's key


def missing_primary_keys(conn: Connection) -> list:
    """compare_metadata doesn't report a missing primary key, so check those separately."""
    insp = inspect(conn)
    existing = set(insp.get_table_names())
    return [("add_pk", t.primary_key) for t in Base.metadata.sorted_tables
            if t.name in existing and t.primary_key.columns
            and not insp.get_pk_constraint(t.name).get("constrained_columns")]


def id_sequences(conn: Connection) -> list[tuple[str, str]]:
    """(table, sequence) for every table whose `id` takes its default from a sequence."""
    existing = set(inspect(conn).get_table_names())
    out = []
    for t in Base.metadata.sorted_tables:
        if t.name in existing and "id" in t.c:
            seq = conn.scalar(text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": t.name})
            if seq:
                out.append((t.name, seq))
    return out


def lagging_sequences(conn: Connection) -> list:
    """A restore that skips setval leaves sequences behind max(id): new rows collide with old ones."""
    out = []
    for table, seq in id_sequences(conn):
        top = conn.scalar(text(f'SELECT max(id) FROM "{table}"'))
        last, called = conn.execute(text(f"SELECT last_value, is_called FROM {seq}")).one()
        nxt = last + 1 if called else last
        if top is not None and nxt <= top:
            out.append(("sync_sequence", table, seq, top))
    return out


def differences(conn: Connection) -> list:
    return (lagging_sequences(conn) + missing_primary_keys(conn)
            + compare_metadata(MigrationContext.configure(conn), Base.metadata))


def describe(diff) -> str:
    if diff[0] == "sync_sequence":
        return f"sync_sequence {diff[1]} (sequence behind max(id) {diff[3]})"
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
    for diff in sorted(diffs, key=lambda d: 9 if isinstance(d, list) else ORDER.get(d[0], 9)):
        if isinstance(diff, list) or diff[0] not in REPAIRABLE:
            failed.append(f"not repairable here: {describe(diff)}")
            continue
        try:
            with engine.begin() as conn:
                if diff[0] == "sync_sequence":
                    _, table, seq, top = diff
                    conn.execute(text("SELECT setval(:s, :v)"), {"s": seq, "v": top})
                elif diff[0] == "add_pk":
                    renumbered = _renumber_duplicate_ids(conn, diff[1].table.name)
                    if renumbered:
                        print(f"schema repair: gave {renumbered} duplicate-id rows in {diff[1].table.name} new ids")
                    conn.execute(AddConstraint(diff[1]))
                else:
                    conn.execute(CreateIndex(diff[1]) if diff[0] == "add_index" else AddConstraint(diff[1]))
            added += 1
        except Exception as exc:  # e.g. duplicate rows block a unique constraint
            failed.append(f"{describe(diff)}: {type(exc).__name__}: {str(exc).splitlines()[0]}")
    return added, failed


def _renumber_duplicate_ids(conn: Connection, table: str) -> int:
    """Rows that reused an id (sequence behind after a restore) get fresh ids; the first copy
    of each id keeps it. Only for tables with a sequence-backed `id`; references to a duplicated
    id stay pointing at the first copy, since which row they meant can't be known."""
    seq = conn.scalar(text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table})
    if not seq:
        return 0
    res = conn.execute(text(f"""
        UPDATE "{table}" SET id = nextval('{seq}')
        WHERE ctid IN (SELECT ctid FROM (SELECT ctid, row_number() OVER (PARTITION BY id ORDER BY ctid) AS n
                                         FROM "{table}") d WHERE n > 1)"""))
    return res.rowcount or 0


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
