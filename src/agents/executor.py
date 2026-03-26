"""
Execution Agent — Uses browser-use to fill and submit job application forms.
Works on any ATS: Workday, Greenhouse, Lever, iCIMS, proprietary sites.

Key feature: Takes a screenshot after every page/section before moving on.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.memory.memory_store import build_rules_block
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


async def execute_application(
    job: Job,
    cover_letter_content: str | None,
    job_records_dir: Path,
) -> tuple[bool, list[str], str]:
    """
    Use browser-use to fill and submit a job application.
    Takes a screenshot after every page before moving on.

    Returns:
        (success: bool, screenshot_paths: list[str], final_message: str)
    """
    try:
        from browser_use import Agent, Controller
        from browser_use.browser.browser import Browser, BrowserConfig
    except ImportError:
        logger.error("[executor] browser-use not installed.")
        return False, [], "browser-use not installed"

    profile = load_user_profile()
    job_records_dir.mkdir(parents=True, exist_ok=True)

    # Cover letter PDF
    cl_pdf_path: str | None = None
    if cover_letter_content:
        cl_pdf = job_records_dir / "cover_letter.pdf"
        if cover_letter_to_pdf(cover_letter_content, cl_pdf):
            cl_pdf_path = str(cl_pdf.absolute())

    # Resume
    resume_type = job.resume_type or "general"
    resume_path = settings.get_resume_path(resume_type)
    if not resume_path.exists():
        resume_path = settings.get_resume_path("general")
    if not resume_path.exists():
        logger.error(f"[executor] No resume found for type '{resume_type}'.")
        return False, [], f"Resume not found: {resume_type}"

    cl_instruction = (
        f"Upload the cover letter PDF from: {cl_pdf_path}"
        if cl_pdf_path
        else "No cover letter needed. Skip any cover letter upload field."
    )
    submit_instruction = (
        "Click the final SUBMIT button and wait for a confirmation message."
        if settings.auto_submit
        else "Fill all fields but DO NOT click submit. Stop after filling the last page."
    )

    # Memory rules for executor
    rules_block = build_rules_block("executor")

    screenshot_paths: list[str] = []
    page_counter = [0]  # mutable for closure

    async def on_page_complete(page_name: str, screenshot_bytes: bytes | None) -> None:
        """Called by the agent after each page/section completion."""
        page_counter[0] += 1
        if screenshot_bytes:
            sc_path = job_records_dir / f"page_{page_counter[0]:02d}_{page_name.replace(' ', '_')}.png"
            sc_path.write_bytes(screenshot_bytes)
            screenshot_paths.append(str(sc_path))
            logger.info(f"[executor] Screenshot saved: {sc_path.name}")

    task = f"""You are applying for a job on behalf of a candidate. Be precise and thorough.

Application URL: {job.url}
Resume PDF path: {resume_path.absolute()}
{cl_instruction}
{rules_block}

Candidate Profile:
{profile}

CRITICAL INSTRUCTIONS — follow these exactly:
1. Navigate to the application URL.
2. If you see a login page, look for options like "Apply as Guest", "Apply with Resume",
   or "Continue without account" to avoid requiring a new account.
3. Fill in ALL required fields using the candidate profile. Be careful with dropdowns and date fields.
4. Upload the resume PDF when prompted for a resume or CV file.
5. {cl_instruction}
6. Answer ANY screening questions honestly based on the profile.

AFTER COMPLETING EACH PAGE OR SECTION (before clicking Next/Continue):
- Take a screenshot of the completed page to verify the information
- Only proceed to the next page after taking the screenshot

7. {submit_instruction}
8. After the final step, take a final screenshot.
9. Return one of these status messages:
   - SUBMITTED: Application successfully submitted. Confirmation: [confirmation text]
   - FILLED: All fields completed but not submitted (auto_submit=false)
   - ERROR: [describe what went wrong]
"""

    llm = settings.get_llm_fast()
    agent = Agent(task=task, llm=llm)

    try:
        result = await agent.run()
        final = result.final_result() or ""

        # Collect any screenshots the agent captured
        try:
            if hasattr(result, "screenshots") and result.screenshots:
                for i, sc_bytes in enumerate(result.screenshots):
                    sc_path = job_records_dir / f"page_{i+1:02d}_agent.png"
                    sc_path.write_bytes(sc_bytes)
                    if str(sc_path) not in screenshot_paths:
                        screenshot_paths.append(str(sc_path))
        except Exception:
            pass

        success = "SUBMITTED" in final.upper() or "FILLED" in final.upper()
        return success, screenshot_paths, final

    except Exception as e:
        logger.error(f"[executor] Agent error for job {job.id}: {e}")
        return False, screenshot_paths, str(e)


async def run_executor() -> int:
    """
    Execute applications for all queued jobs.
    Returns count of successfully submitted applications.
    """
    logger.info("[executor] Starting execution run...")
    submitted = 0

    async with get_db() as db:
        result = await db.execute(select(Job).where(Job.status == JobStatus.queued))
        jobs = result.scalars().all()

    logger.info(f"[executor] {len(jobs)} jobs queued for application")

    for job in jobs:
        cover_letter_content: str | None = None
        if job.cover_letter_required:
            async with get_db() as db:
                cl_result = await db.execute(
                    select(CoverLetter).where(
                        CoverLetter.job_id == job.id,
                        CoverLetter.status == CoverLetterStatus.approved,
                    )
                )
                cl = cl_result.scalar_one_or_none()
                if not cl:
                    logger.info(f"[executor] Job {job.id} awaiting approved cover letter.")
                    continue
                cover_letter_content = cl.approved_content or cl.draft_content

        # Mark as in progress
        async with get_db() as db:
            job_db = await db.get(Job, job.id)
            job_db.status = JobStatus.applying
            app = Application(
                job_id=job.id,
                status=ApplicationStatus.in_progress,
                started_at=datetime.utcnow(),
            )
            db.add(app)

        job_records_dir = settings.records_dir / f"job_{job.id}"

        try:
            success, screenshot_paths, final_msg = await execute_application(
                job, cover_letter_content, job_records_dir
            )
        except Exception as e:
            success = False
            screenshot_paths = []
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
                    app_db.screenshot_paths = screenshot_paths
                submitted += 1
            else:
                job_db.status = JobStatus.failed
                if app_db:
                    app_db.status = ApplicationStatus.failed
                    app_db.error_log = final_msg
                    app_db.screenshot_paths = screenshot_paths

    logger.info(f"[executor] Done. Submitted {submitted} applications.")
    return submitted
