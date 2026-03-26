"""
Cover Letter Agent — Generates personalized cover letter drafts.

Uses user-demarcated boundaries in the template to identify which sections
the LLM should rewrite. The rest of the template is preserved verbatim.

Template boundary syntax:
  <<<SECTION: section_name>>>
  (existing content or instructions here)
  <<<END_SECTION>>>

The LLM will rewrite the content between these markers. Everything else
in the template is kept exactly as-is.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.models import Job, JobStatus, CoverLetter, CoverLetterStatus

logger = logging.getLogger(__name__)

# Regex to find all demarcated sections
SECTION_RE = re.compile(
    r"<<<SECTION:\s*(?P<name>[^>]+)>>>\n(?P<content>.*?)<<<END_SECTION>>>",
    re.DOTALL
)


def parse_sections(template: str) -> dict[str, str]:
    """
    Extract all user-demarcated sections from the template.
    Returns {section_name: existing_content}.
    """
    sections = {}
    for match in SECTION_RE.finditer(template):
        name = match.group("name").strip()
        content = match.group("content").strip()
        sections[name] = content
    return sections


def apply_generated_sections(template: str, generated: dict[str, str]) -> str:
    """
    Replace the content inside each <<<SECTION>>> with LLM-generated text.
    Removes the boundary markers but preserves all other template text.
    """
    result = template
    for name, new_content in generated.items():
        pattern = re.compile(
            rf"<<<SECTION:\s*{re.escape(name)}\s*>>>\n.*?<<<END_SECTION>>>",
            re.DOTALL
        )
        result = pattern.sub(new_content, result)
    return result


async def generate_section(
    section_name: str,
    existing_content: str,
    job: Job,
    client: AsyncOpenAI,
) -> str:
    """Call LLM to generate a single cover letter section."""
    prompt = f"""You are writing a section of a cover letter for a job application.

Job Details:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or 'N/A'}
- Key Requirements: {', '.join(job.key_requirements or [])}

Job Description:
{(job.description or '')[:3000]}

Section to write: "{section_name}"

Current content / instructions for this section:
{existing_content}

Instructions:
- Write ONLY the content for this specific section. Do not write a greeting, signature, or other sections.
- Keep it concise (2-4 sentences max unless the section instructions say otherwise).
- Be specific to this company and role — avoid generic filler.
- Match a professional but authentic tone.
- Output ONLY the text for this section, no labels or headers.
"""
    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()


async def generate_cover_letter(job: Job) -> Optional[str]:
    """
    Full cover letter generation for a job.
    Returns the complete draft string, or None on failure.
    """
    template_path = settings.cover_letter_template
    if not template_path.exists():
        logger.error(f"[cover_letter] Template not found: {template_path}")
        return None

    template = template_path.read_text(encoding="utf-8")
    sections = parse_sections(template)

    if not sections:
        logger.warning(
            "[cover_letter] No <<<SECTION>>> markers found in template. "
            "Using template as-is with only company/job substitution."
        )
        # Fall back to simple variable substitution
        draft = template.replace("{{company}}", job.company)
        draft = draft.replace("{{title}}", job.title)
        return draft

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    generated: dict[str, str] = {}

    for section_name, existing_content in sections.items():
        logger.info(f"[cover_letter] Generating section '{section_name}' for job {job.id}")
        try:
            generated[section_name] = await generate_section(
                section_name, existing_content, job, client
            )
        except Exception as e:
            logger.error(f"[cover_letter] Failed to generate section '{section_name}': {e}")
            generated[section_name] = existing_content  # fall back to original

    draft = apply_generated_sections(template, generated)
    return draft


async def run_cover_letter_agent() -> int:
    """
    Generates cover letter drafts for all jobs with status 'drafting_cl'.
    Returns the number of drafts created.
    """
    logger.info("[cover_letter] Starting cover letter generation run...")
    created = 0

    async with get_db() as db:
        result = await db.execute(select(Job).where(Job.status == JobStatus.drafting_cl))
        jobs = result.scalars().all()

    logger.info(f"[cover_letter] {len(jobs)} jobs need cover letters")

    for job in jobs:
        draft = await generate_cover_letter(job)
        if not draft:
            logger.error(f"[cover_letter] Failed for job {job.id}. Will retry next run.")
            continue

        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            job_db.status = JobStatus.awaiting_review

            # Get section names that were generated
            template = settings.cover_letter_template.read_text(encoding="utf-8")
            sections = parse_sections(template)

            cl = CoverLetter(
                job_id=job.id,
                draft_content=draft,
                modified_sections={name: {} for name in sections.keys()},
                status=CoverLetterStatus.pending,
            )
            db.add(cl)
            created += 1

        logger.info(
            f"[cover_letter] Draft created for '{job.title}' at {job.company}"
        )

    logger.info(f"[cover_letter] Done. Created {created} drafts.")
    return created
