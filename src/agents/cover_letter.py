"""
Cover Letter Matcher — Uses a local LLM (Ollama/Qwen3 8B) to select the best
matching cover letter example and builds a user-facing prompt.

No AI generation happens here. The user copies the prompt, generates the CL
externally, and uploads it to the application website.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

from src.config import settings
from src.database import get_db
from src.models import Job, JobStatus, CoverLetter, CoverLetterStatus

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract plain text from a PDF file using PyMuPDF."""
    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text.strip()
    except Exception as e:
        logger.error(f"[cover_letter] Failed to extract text from {pdf_path}: {e}")
        return ""


def load_example_texts() -> list[tuple[str, str]]:
    """Load (filename, text) from all example cover letter PDFs."""
    examples = settings.list_cover_letter_examples()
    results = []
    for pdf_path in examples:
        text = extract_pdf_text(pdf_path)
        if text:
            results.append((pdf_path.name, text))
    return results


async def select_best_cover_letter(
    job_description: str,
    job_title: str,
    job_company: str,
    examples: list[tuple[str, str]],
) -> tuple[str, str]:
    """
    Use a local LLM via Ollama to pick the most relevant cover letter example.
    Returns (filename, full_text) of the best match.
    Falls back to the first example if Ollama is unavailable.
    """
    if not examples:
        return ("", "")
    if len(examples) == 1:
        return examples[0]

    numbered = "\n\n".join(
        f"--- COVER LETTER {i+1} (file: {name}) ---\n{text[:1500]}"
        for i, (name, text) in enumerate(examples)
    )

    prompt = f"""/no_think
You are choosing which existing cover letter is the best starting point to modify for a new job application.

JOB: {job_title} at {job_company}
JOB DESCRIPTION (excerpt):
{job_description[:2000]}

AVAILABLE COVER LETTERS:
{numbered}

Reply with ONLY the number (1, 2, 3, etc.) of the cover letter that is most closely aligned with this job description in terms of industry, skills, and tone. Just the number, nothing else."""

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            answer = resp.json().get("response", "").strip()
            digits = "".join(c for c in answer if c.isdigit())
            if digits:
                idx = int(digits) - 1
                if 0 <= idx < len(examples):
                    logger.info(f"[cover_letter] Local model selected example {idx+1}: {examples[idx][0]}")
                    return examples[idx]
    except httpx.ConnectError:
        logger.warning("[cover_letter] Ollama not reachable — falling back to first example")
    except Exception as e:
        logger.warning(f"[cover_letter] Ollama selection failed: {e} — falling back to first example")

    return examples[0]


def build_user_prompt(
    job_title: str,
    job_company: str,
    job_description: str,
    cover_letter_text: str,
) -> str:
    """Build the copy-ready prompt the user pastes into an external AI."""
    return (
        f"Modify my cover letter for the following specific job listing and description, "
        f"keeping the language simple and direct and sticking to the original language as "
        f"much as possible (but not strictly, if there are any opportunities for improvement):\n\n"
        f"'{job_title} at {job_company}\n\n{job_description}'\n\n"
        f"and here is the cover letter to modify:\n\n"
        f"'{cover_letter_text}'"
    )


async def create_pending_cl_upload(job: Job) -> Optional[CoverLetter]:
    """
    Called by the analyzer when a job requires a cover letter.
    Uses the local model to pick the best example, builds the user-facing prompt,
    creates a CoverLetter record, and sets the job to pending_cl_upload.
    """
    examples = load_example_texts()
    if not examples:
        logger.warning(
            f"[cover_letter] No example cover letters found. "
            f"Upload PDFs to {settings.cover_letter_examples_dir} first."
        )
        selected_name, selected_text = "", "(No example cover letters uploaded yet)"
    else:
        selected_name, selected_text = await select_best_cover_letter(
            job_description=job.description or "",
            job_title=job.title,
            job_company=job.company,
            examples=examples,
        )

    prompt = build_user_prompt(
        job_title=job.title,
        job_company=job.company,
        job_description=job.description or "(no description available)",
        cover_letter_text=selected_text,
    )

    async with get_db() as db:
        cl = CoverLetter(
            job_id=job.id,
            draft_content=f"[Pending your cover letter upload — best matching example: {selected_name or 'none'}]",
            prompt_content=prompt,
            status=CoverLetterStatus.pending,
        )
        db.add(cl)

        job_db = await db.get(Job, job.id)
        job_db.status = JobStatus.pending_cl_upload

    logger.info(
        f"[cover_letter] Pending CL upload created for '{job.title}' at {job.company} "
        f"(matched example: {selected_name or 'none'})"
    )
    return cl
