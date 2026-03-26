"""
Analysis Agent — Parses JDs and routes to the correct resume + determines cover letter need.
"""
from __future__ import annotations

import logging
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.models import Job, JobStatus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Structured output schema
# ─────────────────────────────────────────────
class JobAnalysis(BaseModel):
    resume_type: str = Field(
        description=(
            "The most relevant resume category for this job. "
            "Must exactly match one of the available categories provided."
        )
    )
    cover_letter_required: bool = Field(
        description="True if the job posting explicitly requires or strongly recommends a cover letter."
    )
    relevance_score: float = Field(
        ge=0.0, le=1.0,
        description="How relevant this job is to the candidate's profile. 1.0 = perfect fit."
    )
    key_requirements: list[str] = Field(
        description="Top 5 most important requirements extracted from the JD."
    )
    reasoning: str = Field(
        description="Brief explanation of why this resume type was chosen and the relevance score."
    )


def _build_analysis_prompt(job: Job, available_categories: list[str]) -> str:
    return f"""You are analyzing a job description to help a candidate route their application.

Available resume categories: {', '.join(available_categories)}

Job Details:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or 'N/A'}

Job Description:
{job.description or 'No description available.'}

Instructions:
1. Choose the MOST RELEVANT resume category from the available list.
2. Determine if a cover letter is explicitly required or strongly recommended.
3. Score relevance from 0.0 to 1.0 based on how well this internship fits a driven student seeking finance, consulting, or tech opportunities.
4. Extract the top 5 key requirements.
"""


async def analyze_job(job: Job) -> Optional[JobAnalysis]:
    """Call LLM to analyze a job posting. Returns structured analysis or None on failure."""
    available_categories = settings.list_resume_categories()
    if not available_categories:
        # Default fallback categories
        available_categories = ["finance", "consulting", "tech", "general"]

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    prompt = _build_analysis_prompt(job, available_categories)

    try:
        response = await client.beta.chat.completions.parse(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            response_format=JobAnalysis,
            temperature=0.2,
        )
        return response.choices[0].message.parsed
    except Exception as e:
        logger.error(f"[analyzer] Failed to analyze job {job.id} ({job.title}): {e}")
        return None


async def run_analyzer() -> tuple[int, int]:
    """
    Analyzes all 'new' jobs in the DB.
    Returns (analyzed_count, queued_count) — queued means passed relevance threshold.
    """
    logger.info("[analyzer] Starting analysis run...")
    analyzed = 0
    queued = 0

    async with get_db() as db:
        result = await db.execute(select(Job).where(Job.status == JobStatus.new))
        jobs = result.scalars().all()

    logger.info(f"[analyzer] Found {len(jobs)} new jobs to analyze")

    for job in jobs:
        # Mark as analyzing
        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            job_db.status = JobStatus.analyzing

        analysis = await analyze_job(job)
        if not analysis:
            async with get_db() as db:
                job_db = await db.get(Job, job.id)
                job_db.status = JobStatus.new  # retry next run
            continue

        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            job_db.resume_type = analysis.resume_type
            job_db.cover_letter_required = analysis.cover_letter_required
            job_db.relevance_score = analysis.relevance_score
            job_db.key_requirements = analysis.key_requirements
            analyzed += 1

            if analysis.relevance_score < settings.min_relevance_score:
                job_db.status = JobStatus.skipped
                logger.info(
                    f"[analyzer] Skipped '{job.title}' at {job.company} "
                    f"(score={analysis.relevance_score:.2f})"
                )
            elif analysis.cover_letter_required:
                job_db.status = JobStatus.drafting_cl
                logger.info(
                    f"[analyzer] '{job.title}' at {job.company} → needs cover letter"
                )
            else:
                job_db.status = JobStatus.queued
                queued += 1
                logger.info(
                    f"[analyzer] '{job.title}' at {job.company} → queued (no CL needed)"
                )

    logger.info(f"[analyzer] Done. Analyzed={analyzed}, Queued={queued}")
    return analyzed, queued
