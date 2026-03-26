"""
Execution Agent — Uses browser-use to fill and submit job application forms.
Works on any ATS: Workday, Greenhouse, Lever, iCIMS, proprietary sites.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.models import Job, JobStatus, Application, ApplicationStatus, CoverLetter, CoverLetterStatus

logger = logging.getLogger(__name__)


def load_user_profile() -> dict:
    """Load user profile from YAML for form filling."""
    import yaml
    profile_path = Path("src/config/profile.yaml")
    if not profile_path.exists():
        logger.warning("[executor] profile.yaml not found. Form filling may be incomplete.")
        return {}
    with open(profile_path) as f:
        return yaml.safe_load(f) or {}


def cover_letter_to_pdf(content: str, output_path: Path) -> bool:
    """Convert markdown cover letter to PDF via WeasyPrint."""
    try:
        import markdown2
        from weasyprint import HTML
        html_content = markdown2.markdown(content)
        styled_html = f"""<!DOCTYPE html>
<html><head><style>
body {{ font-family: 'Georgia', serif; font-size: 12pt; line-height: 1.6;
       margin: 1in; max-width: 6.5in; color: #222; }}
p {{ margin: 0 0 12pt 0; }}
</style></head><body>{html_content}</body></html>"""
        HTML(string=styled_html).write_pdf(str(output_path))
        return True
    except Exception as e:
        logger.error(f"[executor] PDF generation failed: {e}")
        return False


async def execute_application(job: Job, cover_letter_content: str | None) -> bool:
    """
    Use browser-use to fill and submit a job application.
    Returns True on success.
    """
    try:
        from browser_use import Agent
        from langchain_openai import ChatOpenAI
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        logger.error("[executor] browser-use not installed. Run: pip install browser-use")
        return False

    profile = load_user_profile()
    records_dir = settings.records_dir
    records_dir.mkdir(parents=True, exist_ok=True)

    # Prepare cover letter PDF if needed
    cl_pdf_path: str | None = None
    if cover_letter_content:
        cl_pdf = records_dir / f"cover_letter_{job.id}.pdf"
        if cover_letter_to_pdf(cover_letter_content, cl_pdf):
            cl_pdf_path = str(cl_pdf.absolute())

    # Determine resume path
    resume_type = job.resume_type or "general"
    resume_path = settings.get_resume_path(resume_type)
    if not resume_path.exists():
        # Try general fallback
        resume_path = settings.get_resume_path("general")
    if not resume_path.exists():
        logger.error(f"[executor] No resume found for type '{resume_type}'. Aborting.")
        return False

    submit_instruction = (
        "Click the final submit button and wait for confirmation."
        if settings.auto_submit
        else "Fill all fields but DO NOT click submit. Take a screenshot and stop."
    )

    cl_instruction = (
        f"Upload the cover letter PDF from: {cl_pdf_path}"
        if cl_pdf_path
        else "There is no cover letter to upload. Skip any cover letter upload field."
    )

    task = f"""
You are applying for a job on behalf of the candidate.

Application URL: {job.url}
Resume PDF path: {resume_path.absolute()}
{cl_instruction}

Candidate Profile:
{profile}

Instructions:
1. Navigate to the application URL.
2. If you encounter a login page for the ATS (Workday, Greenhouse, etc.), look for 
   'Apply with Resume' or 'Apply without account' options to avoid requiring login.
3. Fill in ALL required fields using the candidate profile above.
4. Upload the resume PDF when prompted for a resume/CV.
5. {cl_instruction}
6. Answer any screening questions honestly based on the profile.
7. {submit_instruction}
8. Take a screenshot when done.
9. Return a brief status message: SUBMITTED, FILLED (if not submitted), or ERROR: reason.
"""

    if settings.llm_provider == "openai":
        llm = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)
    else:
        llm = ChatAnthropic(model=settings.llm_model, api_key=settings.anthropic_api_key)

    agent = Agent(task=task, llm=llm)
    result = await agent.run()

    # Record screenshot
    screenshot_path = None
    try:
        # browser-use Agent exposes last screenshot
        if hasattr(result, "screenshots") and result.screenshots:
            sc = records_dir / f"screenshot_{job.id}.png"
            sc.write_bytes(result.screenshots[-1])
            screenshot_path = str(sc)
    except Exception:
        pass

    final = result.final_result() or ""
    success = "SUBMITTED" in final.upper() or "FILLED" in final.upper()

    logger.info(f"[executor] Job {job.id}: {final[:100]}")
    return success, screenshot_path, final


async def run_executor() -> int:
    """
    Execute applications for all queued jobs (ready, no CL needed or CL approved).
    Returns count of successfully submitted applications.
    """
    logger.info("[executor] Starting execution run...")
    submitted = 0

    async with get_db() as db:
        result = await db.execute(select(Job).where(Job.status == JobStatus.queued))
        jobs = result.scalars().all()

    logger.info(f"[executor] {len(jobs)} jobs queued for application")

    for job in jobs:
        # Get cover letter if applicable
        cover_letter_content: str | None = None
        if job.cover_letter_required:
            async with get_db() as db:
                cl_result = await db.execute(
                    select(CoverLetter).where(
                        CoverLetter.job_id == job.id,
                        CoverLetter.status == CoverLetterStatus.approved
                    )
                )
                cl = cl_result.scalar_one_or_none()
                if not cl:
                    logger.info(f"[executor] Job {job.id} awaiting approved cover letter. Skipping.")
                    continue
                cover_letter_content = cl.approved_content or cl.draft_content

        # Mark as in progress
        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            job_db.status = JobStatus.applying
            app = Application(job_id=job.id, status=ApplicationStatus.in_progress, started_at=datetime.utcnow())
            db.add(app)

        try:
            success, screenshot_path, final_msg = await execute_application(job, cover_letter_content)
        except Exception as e:
            success = False
            screenshot_path = None
            final_msg = str(e)
            logger.error(f"[executor] Error applying to job {job.id}: {e}")

        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            app_result = await db.execute(select(Application).where(Application.job_id == job.id))
            app_db = app_result.scalar_one_or_none()

            if success:
                job_db.status = JobStatus.applied
                if app_db:
                    app_db.status = (
                        ApplicationStatus.submitted if settings.auto_submit
                        else ApplicationStatus.paused
                    )
                    app_db.submitted_at = datetime.utcnow() if settings.auto_submit else None
                    app_db.screenshot_path = screenshot_path
                submitted += 1
            else:
                job_db.status = JobStatus.failed
                if app_db:
                    app_db.status = ApplicationStatus.failed
                    app_db.error_log = final_msg
                    app_db.screenshot_path = screenshot_path

    logger.info(f"[executor] Done. Submitted {submitted} applications.")
    return submitted
