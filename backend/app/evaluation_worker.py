from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .db import Database
from .learning_service import validate_evaluator_output
from .openai_client import evaluate_learning_snapshot


logger = logging.getLogger("uvicorn.error")


async def process_one_evaluation(database: Database, settings: Settings) -> bool:
    job = database.claim_evaluation_job()
    if job is None:
        return False
    try:
        output = await evaluate_learning_snapshot(
            settings,
            source_id=job.source_id,
            snapshot=job.input_snapshot,
            model=settings.evaluator_model,
            reasoning_effort=settings.evaluator_reasoning_effort,
        )
        results = validate_evaluator_output(output, job.input_snapshot)
        database.apply_evaluation_results(
            job=job,
            model=settings.evaluator_model,
            raw_output=output,
            results=results,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("learning_evaluation_failed job_id=%s source_id=%s", job.id, job.source_id)
        database.fail_evaluation_job(job=job, error=str(error))
    return True


async def evaluation_worker_loop(database: Database, settings: Settings) -> None:
    while True:
        processed = await process_one_evaluation(database, settings)
        if not processed:
            await asyncio.sleep(settings.evaluation_worker_interval_seconds)
