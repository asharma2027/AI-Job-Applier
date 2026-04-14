"""
Job Sourcing Agent — manual per-platform scraping triggered from the dashboard.

Active platforms:
  - Handshake (authenticated SSO browser session via browser-use)

Disabled platforms (buttons shown but not yet implemented):
  - LinkedIn, Indeed, WellFound, Glassdoor
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.models import Job, JobStatus

logger = logging.getLogger(__name__)


class JobListing(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    url: str
    description: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Handshake — UChicago SSO + Duo MFA aware
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_handshake() -> list[JobListing]:
    """
    Scrape Handshake using browser-use with UChicago SSO login.

    The login flow is:
      1. Handshake → "College Students and Alumni" → identity.uchicago.edu
      2. CNet ID + password on UChicago's SSO page
      3. Duo Mobile push — agent waits patiently (step_timeout=300s) for approval
      4. Extract internship listings
    """
    use_sso = bool(settings.uchicago_cnet_id and settings.uchicago_password)

    if not use_sso and (not settings.handshake_email or not settings.handshake_password):
        logger.warning("[sourcer] Handshake credentials not configured. Set UCHICAGO_CNET_ID / UCHICAGO_PASSWORD in .env")
        return []

    try:
        from browser_use import Agent
    except ImportError:
        logger.warning("[sourcer] browser-use not installed")
        return []

    llm = settings.get_browser_use_llm_for_task("sourcer")

    if use_sso:
        task = f"""
You are logging into Handshake using University of Chicago SSO credentials and extracting internship listings.

LOGIN FLOW — follow each step precisely:

1. Navigate to: https://uchicago.joinhandshake.com/login
2. Look for and click the button/link labelled "College Students and Alumni login" or "Sign in with your institution".
3. You will land on an institution search page. Type "University of Chicago" and select it if prompted, then proceed.
4. On the UChicago identity page (identity.uchicago.edu or similar):
   a. Enter the CNet ID: {settings.uchicago_cnet_id}
   b. If it asks for email format, use: {settings.uchicago_cnet_id}@uchicago.edu
   c. Click Next / Continue.
5. Enter the password: {settings.uchicago_password}
   Click Sign In / Login.
6. DUO MOBILE MFA — CRITICAL WAITING STEP:
   You will see a Duo Security two-factor authentication screen.
   DO NOT click anything or try to bypass Duo.
   The user will approve the Duo Mobile push notification on their phone.
   Simply WAIT — this may take 1 to 3 minutes. The page will automatically advance once approved.
   If you see a "Send Push" button, click it once to send the push, then wait.
7. Once back on Handshake (you are logged in), navigate to: Jobs section.
8. Apply the "Internship" job type filter.
9. Scroll through the first 2 pages of results.
10. For each listing visible, extract:
    - title (job title)
    - company (employer name)
    - location (city or "Remote")
    - url (the full URL to that specific job posting on Handshake)
11. Return ALL extracted listings as a single JSON array with this exact format:
    [{{"title": "...", "company": "...", "location": "...", "url": "https://..."}}]
    Include ONLY the JSON array in your final answer — no other text.
"""
    else:
        task = f"""
You are logging into Handshake and extracting internship listings.

LOGIN FLOW:
1. Navigate to: https://app.joinhandshake.com/login
2. Enter email: {settings.handshake_email}
3. Enter password: {settings.handshake_password}
4. Complete login.
5. Navigate to Jobs and filter by Internships.
6. Scroll through the first 2 pages of results.
7. For each listing extract: title, company, location, url.
8. Return ALL extracted listings as a JSON array:
   [{{"title": "...", "company": "...", "location": "...", "url": "https://..."}}]
   Only the JSON array in your final answer.
"""

    try:
        # step_timeout=300 gives 5 minutes per step — critical for the Duo wait
        agent = Agent(task=task, llm=llm, step_timeout=300)
        result = await agent.run()

        listings: list[JobListing] = []
        if result and result.final_result():
            raw_text = result.final_result()
            start = raw_text.find("[")
            end = raw_text.rfind("]") + 1
            if start != -1 and end > start:
                items = json.loads(raw_text[start:end])
                for item in items:
                    if isinstance(item, dict) and "url" in item and "title" in item:
                        item.setdefault("description", None)
                        try:
                            listings.append(JobListing(**item))
                        except Exception:
                            pass

        logger.info(f"[sourcer] Handshake: found {len(listings)} listings")
        return listings

    except Exception as e:
        logger.error(f"[sourcer] Handshake scrape failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Public board stubs — disabled until proxies / auth are configured
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_linkedin() -> list[JobListing]:
    logger.warning("[sourcer] LinkedIn scraping is currently disabled.")
    return []

async def scrape_indeed() -> list[JobListing]:
    logger.warning("[sourcer] Indeed scraping is currently disabled.")
    return []

async def scrape_wellfound() -> list[JobListing]:
    logger.warning("[sourcer] WellFound scraping is currently disabled.")
    return []

async def scrape_glassdoor() -> list[JobListing]:
    logger.warning("[sourcer] Glassdoor scraping is currently disabled.")
    return []


PLATFORM_SCRAPERS = {
    "handshake": scrape_handshake,
    "linkedin": scrape_linkedin,
    "indeed": scrape_indeed,
    "wellfound": scrape_wellfound,
    "glassdoor": scrape_glassdoor,
}

ENABLED_PLATFORMS = {"handshake"}


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — called by the dashboard per-platform button
# ─────────────────────────────────────────────────────────────────────────────

async def run_platform_scrape(platform: str) -> dict:
    """
    Scrape a single platform and persist results.
    Returns a summary dict: {platform, found, new_jobs, error}.
    """
    if platform not in PLATFORM_SCRAPERS:
        return {"platform": platform, "found": 0, "new_jobs": 0, "error": f"Unknown platform: {platform}"}

    if platform not in ENABLED_PLATFORMS:
        return {"platform": platform, "found": 0, "new_jobs": 0, "error": f"{platform} is not yet enabled"}

    logger.info(f"[sourcer] Starting scrape: {platform}")
    try:
        scraper = PLATFORM_SCRAPERS[platform]
        listings = await scraper()
        new_jobs = await persist_listings(listings, platform)
        logger.info(f"[sourcer] {platform}: {len(listings)} found, {new_jobs} new")
        return {"platform": platform, "found": len(listings), "new_jobs": new_jobs, "error": None}
    except Exception as e:
        logger.error(f"[sourcer] {platform} failed: {e}")
        return {"platform": platform, "found": 0, "new_jobs": 0, "error": str(e)}
