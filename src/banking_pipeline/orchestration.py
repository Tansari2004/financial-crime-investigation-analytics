"""Dagster assets and daily schedule for the banking data platform."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, TypeVar

import dagster as dg
import psycopg

from .analytics import publish
from .corrections import ingest_corrections
from .ingest import ingest_file
from .promote import DEFAULT_DSN, promote

T = TypeVar("T")


def _dsn() -> str:
    return os.environ.get("BANKING_DATABASE_URL", DEFAULT_DSN)


def _transient_only(action: Callable[[], T]) -> T:
    try:
        return action()
    except (psycopg.OperationalError,
            psycopg.errors.DeadlockDetected,
            psycopg.errors.SerializationFailure) as exc:
        raise dg.RetryRequested(max_retries=3, seconds_to_wait=30) from exc


@dg.asset(group_name="banking", description="Discover and load IBM transaction files")
def source_files(context) -> dg.MaterializeResult:
    source_dir = Path(os.environ.get("BANKING_SOURCE_DIR", "data/raw"))
    pattern = os.environ.get("BANKING_SOURCE_PATTERN", "*Trans.csv")
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source directory does not exist: {source_dir}")
    files = sorted(source_dir.glob(pattern))
    completed = 0
    skipped = 0
    accepted = 0
    rejected = 0
    for path in files:
        result = _transient_only(lambda path=path: ingest_file(path, _dsn()))
        completed += result["status"] == "completed"
        skipped += result["status"] == "skipped"
        accepted += result.get("accepted_rows", 0)
        rejected += result.get("rejected_rows", 0)
        context.log.info(f"transaction file {path.name}: {result['status']}")
    return dg.MaterializeResult(metadata={
        "discovered_files": len(files), "completed_files": completed,
        "skipped_files": skipped, "accepted_rows": accepted,
        "rejected_rows": rejected,
    })


@dg.asset(deps=[source_files], group_name="banking",
          description="Load explicit, audited correction files")
def correction_files(context) -> dg.MaterializeResult:
    directory = os.environ.get("BANKING_CORRECTION_DIR")
    if not directory:
        return dg.MaterializeResult(metadata={"discovered_files": 0})
    source_dir = Path(directory)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"correction directory does not exist: {source_dir}")
    files = sorted(source_dir.glob("*.csv"))
    completed = 0
    for path in files:
        result = _transient_only(lambda path=path: ingest_corrections(path, _dsn()))
        completed += result["status"] == "completed"
        context.log.info(f"correction file {path.name}: {result['status']}")
    return dg.MaterializeResult(metadata={
        "discovered_files": len(files), "completed_files": completed,
    })


@dg.asset(deps=[source_files, correction_files], group_name="banking",
          description="Incrementally type and promote raw transactions")
def promoted_transactions(context) -> dg.MaterializeResult:
    batches = 0
    inserted = 0
    corrected = 0
    late = 0
    while True:
        result = _transient_only(lambda: promote(_dsn()))
        if result["status"] == "skipped":
            break
        batches += 1
        inserted += result["fact_inserted_rows"]
        corrected += result["corrected_transactions"]
        late += result["late_arriving_rows"]
        context.log.info(f"promotion batch {result['promotion_run_id']}: {result}")
        if batches >= 10000:
            raise RuntimeError("promotion exceeded 10000 batches")
    return dg.MaterializeResult(metadata={
        "batches": batches, "facts_inserted": inserted,
        "transactions_corrected": corrected, "late_arrivals": late,
    })


@dg.asset(deps=[promoted_transactions], group_name="banking",
          description="Refresh marts, reconcile, quality-gate, and publish atomically")
def published_analytics(context) -> dg.MaterializeResult:
    result = _transient_only(lambda: publish(_dsn()))
    context.log.info(f"analytics publication: {result}")
    return dg.MaterializeResult(metadata={
        "status": result["status"],
        "publication_id": result.get("publication_id", result.get("last_publication_id") or 0),
        "affected_days": result.get("affected_days", 0),
        "affected_files": result.get("affected_files", 0),
    })


banking_daily_pipeline = dg.define_asset_job("banking_daily_pipeline")
banking_daily_schedule = dg.ScheduleDefinition(
    name="banking_daily_schedule",
    job=banking_daily_pipeline,
    cron_schedule="0 2 * * *",
    execution_timezone="America/Toronto",
    default_status=dg.DefaultScheduleStatus.STOPPED,
)
defs = dg.Definitions(
    assets=[source_files, correction_files, promoted_transactions, published_analytics],
    jobs=[banking_daily_pipeline],
    schedules=[banking_daily_schedule],
)
