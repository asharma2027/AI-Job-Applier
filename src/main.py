"""
Main entry point — starts the FastAPI dashboard.

All agent actions (sourcing, analysis, drafting, filling, submitting) are
triggered explicitly from the dashboard. No LLM calls happen on startup.

Usage:
    python -m src.main              # start the dashboard API
    python -m src.main --run-once   # run the full pipeline once and exit
"""
from __future__ import annotations

import asyncio
import logging
import sys

import click
import uvicorn

from src.config import settings
from src.database import init_db
from src.activity import install_activity_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

install_activity_handler()


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
@click.option("--run-once", is_flag=True, help="Run the pipeline once and exit.")
def main(run_once: bool):
    async def _main():
        await init_db()

        if run_once:
            logger.info("Running pipeline once...")
            from src.orchestrator import run_pipeline_once
            result = await run_pipeline_once()
            logger.info(f"Pipeline result: {result}")
            return

        logger.info("Starting in dashboard mode. All agent actions are manual.")
        await run_api()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
