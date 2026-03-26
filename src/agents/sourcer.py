"""
Job Sourcing Agent — Crawl4AI + browser-use to gather listings from:
  - Handshake (authenticated browser session)
  - LinkedIn, Indeed, WellFound (public Crawl4AI)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, LLMExtractionStrategy
from pydantic import BaseModel
from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.models import Job, JobStatus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Pydantic schema for extracted job listing
# ─────────────────────────────────────────────
class JobListing(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    url: str
    description: Optional[str] = None


# ─────────────────────────────────────────────
# Public board scrapers via Crawl4AI
# ─────────────────────────────────────────────
PUBLIC_BOARD_URLS = {
    "linkedin": "https://www.linkedin.com/jobs/search/?keywords=internship&f_JT=I&f_TP=1",
    "indeed": "https://www.indeed.com/jobs?q=internship&jt=internship",
    "wellfound": "https://wellfound.com/jobs?jobType=internship",
    "glassdoor": "https://www.glassdoor.com/Job/internship-jobs-SRCH_KO0,10.htm",
}


async def scrape_public_board(source: str, url: str) -> list[JobListing]:
    """Use Crawl4AI with LLM extraction to pull listings from a public board."""
    extraction_strategy = LLMExtractionStrategy(
        provider=f"{settings.llm_provider}/{settings.llm_model}",
        api_token=settings.openai_api_key or settings.anthropic_api_key,
        schema=JobListing.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Extract all internship job listings from this page. "
            "For each listing, extract the job title, company name, location, "
            "application URL (the link to the full job posting), and a brief description if visible. "
            "Return as a JSON array."
        ),
    )

    browser_cfg = BrowserConfig(headless=True, verbose=False)
    run_cfg = CrawlerRunConfig(extraction_strategy=extraction_strategy)

    listings: list[JobListing] = []
    try:
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)
            if result.extracted_content:
                raw = json.loads(result.extracted_content)
                if isinstance(raw, list):
                    for item in raw:
                        try:
                            listings.append(JobListing(**item))
                        except Exception:
                            pass
    except Exception as e:
        logger.error(f"[sourcer] Failed to scrape {source}: {e}")

    logger.info(f"[sourcer] {source}: found {len(listings)} listings")
    return listings


async def scrape_handshake() -> list[JobListing]:
    """
    Scrape Handshake using browser-use with authenticated session.
    Falls back gracefully if credentials not set.
    """
    if not settings.handshake_email or not settings.handshake_password:
        logger.warning("[sourcer] Handshake credentials not set. Skipping.")
        return []

    try:
        from browser_use import Agent
        from langchain_openai import ChatOpenAI
        from langchain_anthropic import ChatAnthropic

        if settings.llm_provider == "openai":
            llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)
        else:
            llm = ChatAnthropic(model=settings.llm_model, api_key=settings.anthropic_api_key)

        task = f"""
        1. Go to https://app.joinhandshake.com/login
        2. Log in with email '{settings.handshake_email}' and password '{settings.handshake_password}'
        3. Navigate to Jobs -> Internships filter
        4. Extract the first 20 internship listings: for each get title, company, location, and application URL
        5. Return results as a JSON array with fields: title, company, location, url
        """

        agent = Agent(task=task, llm=llm)
        result = await agent.run()

        # Parse the agent's output (it should return JSON)
        listings: list[JobListing] = []
        if result and result.final_result():
            raw_text = result.final_result()
            try:
                # Find JSON array in the output
                start = raw_text.find("[")
                end = raw_text.rfind("]") + 1
                if start != -1 and end > start:
                    items = json.loads(raw_text[start:end])
                    for item in items:
                        if isinstance(item, dict) and "url" in item:
                            item.setdefault("description", None)
                            try:
                                listings.append(JobListing(**item))
                            except Exception:
                                pass
            except json.JSONDecodeError:
                pass

        logger.info(f"[sourcer] Handshake: found {len(listings)} listings")
        return listings

    except ImportError:
        logger.warning("[sourcer] browser-use not installed. Install with: pip install browser-use")
        return []
    except Exception as e:
        logger.error(f"[sourcer] Handshake scrape failed: {e}")
        return []


# ─────────────────────────────────────────────
# Deduplicate and persist to DB
# ─────────────────────────────────────────────
async def persist_listings(listings: list[JobListing], source: str) -> int:
    """Insert new job listings into the DB, skipping duplicates. Returns count of new jobs."""
    new_count = 0
    async with get_db() as db:
        for listing in listings:
            if not listing.url or not listing.title or not listing.company:
                continue
            existing = await db.execute(select(Job).where(Job.url == listing.url))
            if existing.scalar_one_or_none():
                continue
            job = Job(
                url=listing.url,
                title=listing.title,
                company=listing.company,
                location=listing.location,
                description=listing.description,
                source=source,
                status=JobStatus.new,
            )
            db.add(job)
            new_count += 1
    logger.info(f"[sourcer] {source}: persisted {new_count} new jobs")
    return new_count


async def run_sourcer() -> int:
    """
    Main sourcing pipeline. Scrapes all configured job boards and persists results.
    Returns total number of new jobs discovered.
    """
    logger.info("[sourcer] Starting sourcing run...")
    total_new = 0

    # Run public board scrapes concurrently
    tasks = [scrape_public_board(source, url) for source, url in PUBLIC_BOARD_URLS.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for source, result in zip(PUBLIC_BOARD_URLS.keys(), results):
        if isinstance(result, Exception):
            logger.error(f"[sourcer] {source} failed: {result}")
            continue
        new = await persist_listings(result, source)
        total_new += new

    # Handshake (sequential — requires authenticated session)
    handshake_listings = await scrape_handshake()
    new = await persist_listings(handshake_listings, "handshake")
    total_new += new

    logger.info(f"[sourcer] Run complete. Total new jobs: {total_new}")
    return total_new
