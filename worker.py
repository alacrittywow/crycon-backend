#!/usr/bin/env python3
"""Claim and execute one registered Crycon background job."""

import argparse
import logging
import signal
import sys
import threading
import time
import uuid

from crycon.job_handlers import build_job_handler_registry
from crycon.jobs import run_next_job
from crycon.observability import emit_event
from crycon.supabase_jobs import SupabaseParserJobRepository
from db_supabase import get_supabase_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one queued Crycon job.")
    parser.add_argument(
        "--worker-id",
        default=f"worker-{uuid.uuid4().hex[:12]}",
        help="Lease owner stored in parser_jobs",
    )
    parser.add_argument(
        "--stale-after",
        type=int,
        default=900,
        help="Seconds before a silent worker lease may be recovered",
    )
    parser.add_argument("--loop", action="store_true", help="Keep polling for jobs")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between empty queue checks in loop mode",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    logger = logging.getLogger("crycon.worker")

    client = get_supabase_client()
    jobs = SupabaseParserJobRepository(client)
    handlers = build_job_handler_registry(client, jobs, args.worker_id)
    stopping = threading.Event()
    idle_logged = False

    emit_event(
        logger,
        "worker_started",
        worker_id=args.worker_id,
        loop=args.loop,
        poll_interval=args.poll_interval,
        stale_after_seconds=args.stale_after,
    )

    def stop(_signum, _frame) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping.is_set():
        started = time.monotonic()
        try:
            outcome = run_next_job(
                jobs,
                args.worker_id,
                handlers.handle,
                stale_after_seconds=max(1, args.stale_after),
            )
        except Exception as error:
            # The lifecycle already stores a safe error type. Do not print an
            # exception message here because it may contain credentials.
            emit_event(
                logger,
                "job_failed",
                worker_id=args.worker_id,
                error_type=type(error).__name__,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            if not args.loop:
                raise
            stopping.wait(max(0.1, args.poll_interval))
            continue

        if outcome is None:
            if not idle_logged:
                emit_event(logger, "worker_idle", worker_id=args.worker_id)
                idle_logged = True
            if not args.loop:
                break
            stopping.wait(max(0.1, args.poll_interval))
            continue

        idle_logged = False
        emit_event(
            logger,
            "job_finished",
            worker_id=args.worker_id,
            job_id=outcome.job_id,
            job_type=outcome.job_type,
            attempt_count=outcome.attempt_count,
            status=outcome.status,
            result_count=outcome.result_count,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        if not args.loop:
            break

    emit_event(logger, "worker_stopped", worker_id=args.worker_id)


if __name__ == "__main__":
    main()
