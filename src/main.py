"""
Main entry point — starts the background agent + FastAPI dashboard concurrently.

Usage:
    python -m src.main              # run both scheduler and dashboard
    python -m src.main --api-only   # run only the dashboard
    python -m src.main --run-once   # run the pipeline once and exit
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import click
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.database import init_db
from src.orchestrator import run_pipeline_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run_scheduler():
    """Start the APScheduler to run the pipeline periodically."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline_once,
        trigger="interval",
        minutes=settings.scrape_interval_minutes,
        id="pipeline",
        name="Job Application Pipeline",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started. Pipeline will run every {settings.scrape_interval_minutes} minutes."
    )

    # Run immediately on startup
    logger.info("Running initial pipeline pass...")
    await run_pipeline_once()

    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


async def run_api():
    """Start the FastAPI dashboard."""
    config = uvicorn.Config(
        "src.api.main:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)
    logger.info(
        f"Dashboard starting at http://{settings.dashboard_host}:{settings.dashboard_port}"
    )
    await server.serve()


@click.command()
@click.option("--api-only", is_flag=True, help="Run only the dashboard API.")
@click.option("--run-once", is_flag=True, help="Run the pipeline once and exit.")
def main(api_only: bool, run_once: bool):
    async def _main():
        await init_db()

        if run_once:
            logger.info("Running pipeline once...")
            result = await run_pipeline_once()
            logger.info(f"Pipeline result: {result}")
            return

        if api_only:
            await run_api()
        else:
            # Run both concurrently
            await asyncio.gather(
                run_scheduler(),
                run_api(),
            )

    asyncio.run(_main())


if __name__ == "__main__":
    main()
