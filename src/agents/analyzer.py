"""
Analysis Agent — Parses JDs and routes to the correct resume + determines cover letter need.
Uses task-aware model routing with memory rules injected into prompts.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.memory.memory_store import build_rules_block
from src.memory.self_refine import critic_pass, refine_with_feedback
from src.models import Job, JobStatus

logger = logging.getLogger(__name__)


# ── Structured output schema ─────────────────────────────────────────────────
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
        description="How relevant this job is to the candidate's profile. 1.0 = perfect fit.",
    )
    key_requirements: list[str] = Field(
        description="Top 5 most important requirements extracted from the JD."
    )
    reasoning: str = Field(
        description="Brief explanation of why this resume type was chosen and the relevance score."
    )


def _build_analysis_prompt(job: Job, available_categories: list[str]) -> str:
    rules_block = build_rules_block("analyzer")
    return f"""You are analyzing a job description to help a student route their internship application.

Available resume categories: {', '.join(available_categories)}
{rules_block}

Job Details:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or 'N/A'}

Job Description:
{job.description or 'No description available.'}

Instructions:
1. Choose the MOST RELEVANT resume category from the available list.
2. Determine if a cover letter is explicitly required or strongly recommended.
3. Score relevance from 0.0 to 1.0 (intern-level opportunity for a driven student).
4. Extract the top 5 key requirements.

Respond ONLY with valid JSON matching this schema:
{{
  "resume_type": "<category>",
  "cover_letter_required": true/false,
  "relevance_score": 0.0-1.0,
  "key_requirements": ["...", "...", "...", "...", "..."],
  "reasoning": "..."
}}"""


async def analyze_job(job: Job) -> Optional[JobAnalysis]:
    """Call task-routed LLM to analyze a job. Returns structured analysis."""
    available_categories = settings.list_resume_categories()
    if not available_categories:
        available_categories = ["finance", "consulting", "tech", "general"]

    llm = settings.get_llm_for_task("analyzer")
    prompt = _build_analysis_prompt(job, available_categories)
    context = f"Analyze job: {job.title} at {job.company}"
    rules_block = build_rules_block("analyzer")

    try:
        result = await llm.ainvoke(prompt)
        raw = result.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        # Self-refine critic pass
        passed, violation = await critic_pass("analyzer", raw, context, rules_block)
        if not passed and violation:
            raw = await refine_with_feedback(prompt, raw, violation, llm.ainvoke)

        data = json.loads(raw)
        return JobAnalysis(**data)

    except Exception as e:
        logger.error(f"[analyzer] Failed to analyze job {job.id} ({job.title}): {e}")
        return None


async def run_analyzer() -> tuple[int, int]:
    """
    Analyzes all 'new' jobs in the DB.
    Returns (analyzed_count, queued_count).
    """
    logger.info("[analyzer] Starting analysis run...")
    analyzed = 0
    queued = 0

    async with get_db() as db:
        result = await db.execute(select(Job).where(Job.status == JobStatus.new))
        jobs = result.scalars().all()

    logger.info(f"[analyzer] Found {len(jobs)} new jobs to analyze")

    for job in jobs:
        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            job_db.status = JobStatus.analyzing

        analysis = await analyze_job(job)
        if not analysis:
            async with get_db() as db:
                job_db = await db.get(Job, job.id)
                job_db.status = JobStatus.new
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
                # Create pending CL upload (local model picks best example + builds prompt)
                from src.agents.cover_letter import create_pending_cl_upload
                await create_pending_cl_upload(job)
                logger.info(f"[analyzer] '{job.title}' at {job.company} → pending cover letter upload")
            else:
                job_db.status = JobStatus.queued
                queued += 1
                logger.info(f"[analyzer] '{job.title}' at {job.company} → queued (no CL needed)")

    logger.info(f"[analyzer] Done. Analyzed={analyzed}, Queued={queued}")
    return analyzed, queued
