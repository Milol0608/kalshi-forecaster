"""Compare the live database schema with the models and print any difference.

Catches a database that was copied or restored without some of its constraints or indexes,
which `alembic upgrade` can't see because the version stamp still says it's up to date.
Prints table/constraint names only, never data or connection details. Exit 1 on any difference.
"""

from __future__ import annotations

import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db.models import Base
from app.db.session import get_engine


def main() -> int:
    with get_engine().connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    for d in diffs:
        print("schema difference:", d)
    print(f"schema check: {len(diffs)} difference(s)")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
