from __future__ import annotations

import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Run


@contextmanager
def track_run(session: Session, job: str, mode: str) -> Iterator[Run]:
    """Write a `runs` row for one job. Records failure with traceback, then re-raises.

    The run row is committed on its own first, so a failure that rolls back the job's
    data still leaves a record of the attempt.
    """
    run = Run(job=job, mode=mode, status="running", started_at=datetime.now(timezone.utc))
    session.add(run)
    session.commit()
    t0 = time.monotonic()
    try:
        yield run
    except BaseException:
        session.rollback()
        run.status = "failed"
        run.error = traceback.format_exc()[-4000:]
        raise
    else:
        run.status = "ok"
    finally:
        run.finished_at = datetime.now(timezone.utc)
        run.duration_s = time.monotonic() - t0
        session.add(run)
        session.commit()
