"""
Execution Agent — browser-use to fill and submit job application forms.

Two explicit stages, each triggered manually from the dashboard:
  1. fill_job(job_id)   — fills every field, stops before Submit, keeps browser open for user review
  2. User manually reviews the open browser window and clicks Submit themselves

Works on any ATS: Workday, Greenhouse, Lever, iCIMS, proprietary sites.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from src.config import settings
from src.database import get_db
from src.memory.memory_store import build_rules_block
from src.models import Job, JobStatus, Application, ApplicationStatus, CoverLetter, CoverLetterStatus

logger = logging.getLogger(__name__)

# ── Live browser sessions kept open for user review after fill ────────────────
# Maps job_id → BrowserSession instance.  Cleared when user confirms or discards.
_open_fill_sessions: dict[int, Any] = {}


def has_open_browser_session(job_id: int) -> bool:
    return job_id in _open_fill_sessions


def open_browser_session_ids() -> list[int]:
    return list(_open_fill_sessions.keys())


async def close_fill_session(job_id: int) -> None:
    """Force-close the browser window kept open for user review."""
    session = _open_fill_sessions.pop(job_id, None)
    if session:
        try:
            await session.kill()
        except Exception as e:
            logger.warning(f"[executor] Error killing browser session for job {job_id}: {e}")


def load_user_profile() -> dict:
    import yaml
    profile_path = Path("src/config/profile.yaml")
    if not profile_path.exists():
        logger.warning("[executor] profile.yaml not found. Form filling may be incomplete.")
        return {}
    with open(profile_path) as f:
        return yaml.safe_load(f) or {}


def cover_letter_to_pdf(content: str, output_path: Path) -> bool:
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


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Fill form (never clicks Submit)
# ─────────────────────────────────────────────────────────────────────────────

async def fill_job(job_id: int) -> dict:
    """
    Open the application form, fill every field, and STOP before the Submit button.
    Takes a screenshot of the completed final page.
    Sets job status to `filled`.
    Returns a summary dict.
    """
    async with get_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            return {"ok": False, "message": f"Job {job_id} not found"}
        if job.status not in (JobStatus.queued, JobStatus.failed, JobStatus.filled):
            return {"ok": False, "message": f"Job {job_id} is in status '{job.status}' — expected 'queued'"}

    try:
        from browser_use import Agent
    except ImportError:
        return {"ok": False, "message": "browser-use not installed"}

    profile = load_user_profile()
    rules_block = build_rules_block("executor")
    job_records_dir = settings.records_dir / f"job_{job_id}"
    job_records_dir.mkdir(parents=True, exist_ok=True)

    # Check if the user already uploaded the cover letter to the application website
    user_uploaded_cl = False
    cl_pdf_path: str | None = None
    async with get_db() as db:
        job = await db.get(Job, job_id)
        if job.cover_letter_required:
            cl_result = await db.execute(
                select(CoverLetter).where(
                    CoverLetter.job_id == job_id,
                    CoverLetter.status == CoverLetterStatus.approved,
                )
            )
            cl = cl_result.scalar_one_or_none()
            if cl:
                if cl.approved_content and not cl.approved_content.startswith("["):
                    cl_pdf = job_records_dir / "cover_letter.pdf"
                    if cover_letter_to_pdf(cl.approved_content, cl_pdf):
                        cl_pdf_path = str(cl_pdf.absolute())
                else:
                    user_uploaded_cl = True

    resume_type = job.resume_type or "general"
    resume_path = settings.get_resume_path(resume_type)
    if not resume_path.exists():
        resume_path = settings.get_resume_path("general")
    if not resume_path.exists():
        return {"ok": False, "message": f"No resume found for type '{resume_type}'"}

    if cl_pdf_path:
        cl_instruction = f"Upload the cover letter PDF from: {cl_pdf_path}"
    elif user_uploaded_cl:
        cl_instruction = (
            "The cover letter has already been uploaded by the user. "
            "Skip any cover letter upload field — do NOT re-upload or overwrite it."
        )
    else:
        cl_instruction = "No cover letter needed. Skip any cover letter upload field."

    safeguards_block = """
### 🛑 ABSOLUTE HARD STOP — DO NOT SUBMIT 🛑
This is the FILL stage only. You must NEVER click the final Submit button.

FORBIDDEN:
- Clicking Submit / Apply / Send Application / Finish / Complete / Confirm / Finalize / Done.
- Pressing Enter on any final confirmation dialog.
- Clicking Withdraw, Delete, or Remove.
- Modifying the candidate's global profile.

ALLOWED:
- Clicking Next / Continue / Save / Save & Continue / Review to advance through pages.
- Filling text fields, selecting dropdowns, checking boxes, uploading files.
- Taking screenshots.

WHEN YOU REACH THE FINAL PAGE:
1. Fill all remaining fields.
2. Take a screenshot showing the completed form WITH the submit button VISIBLE BUT NOT CLICKED.
3. STOP. Report status as FILLED.
"""

    task = f"""You are filling a job application form on behalf of a candidate. STOP before submitting.

Application URL: {job.url}
Resume PDF path: {resume_path.absolute()}
{cl_instruction}
{rules_block}
{safeguards_block}

Candidate Profile:
{profile}

INSTRUCTIONS:
1. Navigate to the application URL.
2. If a login is needed, look for "Apply as Guest", "Apply with Resume", or "Continue without account".
3. Fill ALL required fields using the candidate profile.
4. Upload the resume PDF when asked for a resume or CV.
5. {cl_instruction}
6. Answer screening questions honestly based on the profile.
7. After completing each page, take a screenshot BEFORE clicking Next/Continue.
8. On the FINAL page: fill all remaining fields, take a screenshot showing the submit button, then STOP.
9. Return: FILLED — [brief summary of pages completed]
"""

    # Mark as filling
    async with get_db() as db:
        job_db = await db.get(Job, job_id)
        job_db.status = JobStatus.filling
        existing_app = await db.execute(select(Application).where(Application.job_id == job_id))
        app = existing_app.scalar_one_or_none()
        if not app:
            app = Application(job_id=job_id, status=ApplicationStatus.in_progress, started_at=datetime.utcnow())
            db.add(app)
        else:
            app.status = ApplicationStatus.in_progress
            app.started_at = datetime.utcnow()

    screenshot_paths: list[str] = []
    page_counter = [0]

    async def on_page_complete(page_name: str, screenshot_bytes: bytes | None) -> None:
        page_counter[0] += 1
        if screenshot_bytes:
            sc_path = job_records_dir / f"fill_{page_counter[0]:02d}_{page_name.replace(' ', '_')}.png"
            sc_path.write_bytes(screenshot_bytes)
            screenshot_paths.append(str(sc_path))

    llm = settings.get_browser_use_llm_for_task("executor")

    # Create a visible, persistent browser session so the window stays open after fill.
    # The user can then switch to that window, review the completed form, and click Submit.
    browser_session = None
    try:
        from browser_use import BrowserSession
        browser_session = BrowserSession(
            headless=False,   # must be visible so the user can see and interact with it
            keep_alive=True,  # do NOT close the browser when agent.run() finishes
        )
        # Register immediately so cancellation paths can always find and close it.
        _open_fill_sessions[job_id] = browser_session
        agent = Agent(task=task, llm=llm, browser_session=browser_session)
    except Exception as e:
        logger.warning(f"[executor] Could not create persistent BrowserSession ({e}); falling back to default agent.")
        browser_session = None
        agent = Agent(task=task, llm=llm)

    try:
        agent.on_page_complete = on_page_complete
    except Exception:
        pass

    try:
        result = await agent.run()
        final = result.final_result() or ""

        # Collect agent screenshots
        try:
            if hasattr(result, "screenshots") and result.screenshots:
                for i, sc_bytes in enumerate(result.screenshots):
                    sc_path = job_records_dir / f"fill_agent_{i+1:02d}.png"
                    sc_path.write_bytes(sc_bytes)
                    if str(sc_path) not in screenshot_paths:
                        screenshot_paths.append(str(sc_path))
        except Exception:
            pass

        success = "FILLED" in final.upper() or "SUBMITTED" in final.upper()

        async with get_db() as db:
            job_db = await db.get(Job, job_id)
            app_result = await db.execute(select(Application).where(Application.job_id == job_id))
            app_db = app_result.scalar_one_or_none()

            if success:
                job_db.status = JobStatus.filled
                if app_db:
                    app_db.status = ApplicationStatus.filled
                    app_db.screenshot_paths = screenshot_paths
                if browser_session:
                    logger.info(
                        f"[executor] Job {job_id} filled — browser window kept open for user review. "
                        "Switch to the browser window, review the form, then click Submit yourself."
                    )
                else:
                    logger.info(f"[executor] Job {job_id} filled successfully. Awaiting manual submit.")
            else:
                job_db.status = JobStatus.failed
                if app_db:
                    app_db.status = ApplicationStatus.failed
                    app_db.error_log = final
                    app_db.screenshot_paths = screenshot_paths
                if browser_session:
                    await close_fill_session(job_id)
                logger.error(f"[executor] Job {job_id} fill failed: {final[:200]}")

        return {"ok": success, "message": final, "screenshots": len(screenshot_paths)}

    except asyncio.CancelledError:
        # Python 3.9+ CancelledError is a BaseException and bypasses `except Exception`.
        # Always close any keep_alive browser session on cancellation to avoid orphan windows.
        await close_fill_session(job_id)
        raise

    except Exception as e:
        await close_fill_session(job_id)
        async with get_db() as db:
            job_db = await db.get(Job, job_id)
            if job_db:
                job_db.status = JobStatus.failed
        logger.error(f"[executor] fill_job error for job {job_id}: {e}")
        return {"ok": False, "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Submit (clicks the final Submit button)
# ─────────────────────────────────────────────────────────────────────────────

async def submit_job(job_id: int) -> dict:
    """
    Re-open the application, navigate to the final page, and click Submit.
    Most ATSs (Workday, Greenhouse, Lever) persist form state server-side,
    so navigating back to the application URL restores the saved progress.
    Sets job status to `applied`.
    Returns a summary dict.
    """
    async with get_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            return {"ok": False, "message": f"Job {job_id} not found"}
        if job.status != JobStatus.filled:
            return {"ok": False, "message": f"Job {job_id} is in status '{job.status}' — expected 'filled'"}

    try:
        from browser_use import Agent
    except ImportError:
        return {"ok": False, "message": "browser-use not installed"}

    rules_block = build_rules_block("executor")
    job_records_dir = settings.records_dir / f"job_{job_id}"
    job_records_dir.mkdir(parents=True, exist_ok=True)

    task = f"""You are submitting a job application that was previously filled out and saved.

Application URL: {job.url}
{rules_block}

INSTRUCTIONS:
1. Navigate to the application URL: {job.url}
2. Look for "Continue Application", "Resume Application", "Your saved application", or similar.
   If you see the application form already in progress, navigate through to the final page.
3. Navigate any review or summary pages until you reach the FINAL page with the Submit button.
4. Verify the form looks correct (fields are filled).
5. Click the FINAL SUBMIT / APPLY / SEND APPLICATION button.
6. Wait for the confirmation page or confirmation message.
7. Take a screenshot of the confirmation.
8. Return: SUBMITTED — [paste the confirmation text or message you see on screen]
   If you cannot find the submit button or the application is gone, return: ERROR — [explain what you see]
"""

    # Mark as submitting
    async with get_db() as db:
        job_db = await db.get(Job, job_id)
        job_db.status = JobStatus.submitting

    screenshot_paths: list[str] = []
    page_counter = [0]

    async def on_page_complete(page_name: str, screenshot_bytes: bytes | None) -> None:
        page_counter[0] += 1
        if screenshot_bytes:
            sc_path = job_records_dir / f"submit_{page_counter[0]:02d}_{page_name.replace(' ', '_')}.png"
            sc_path.write_bytes(screenshot_bytes)
            screenshot_paths.append(str(sc_path))

    llm = settings.get_browser_use_llm_for_task("executor")
    agent = Agent(task=task, llm=llm)
    agent.on_page_complete = on_page_complete

    try:
        result = await agent.run()
        final = result.final_result() or ""

        try:
            if hasattr(result, "screenshots") and result.screenshots:
                for i, sc_bytes in enumerate(result.screenshots):
                    sc_path = job_records_dir / f"submit_agent_{i+1:02d}.png"
                    sc_path.write_bytes(sc_bytes)
                    if str(sc_path) not in screenshot_paths:
                        screenshot_paths.append(str(sc_path))
        except Exception:
            pass

        success = "SUBMITTED" in final.upper()

        async with get_db() as db:
            job_db = await db.get(Job, job_id)
            app_result = await db.execute(select(Application).where(Application.job_id == job_id))
            app_db = app_result.scalar_one_or_none()

            if success:
                job_db.status = JobStatus.applied
                if app_db:
                    app_db.status = ApplicationStatus.submitted
                    app_db.submitted_at = datetime.utcnow()
                    existing = app_db.screenshot_paths or []
                    app_db.screenshot_paths = existing + screenshot_paths
                    app_db.confirmation_text = final
                logger.info(f"[executor] Job {job_id} submitted successfully.")
            else:
                job_db.status = JobStatus.filled  # revert — still filled, not submitted
                if app_db:
                    app_db.status = ApplicationStatus.filled
                    app_db.error_log = final
                logger.error(f"[executor] Job {job_id} submit failed: {final[:200]}")

        return {"ok": success, "message": final, "screenshots": len(screenshot_paths)}

    except Exception as e:
        async with get_db() as db:
            job_db = await db.get(Job, job_id)
            if job_db:
                job_db.status = JobStatus.filled  # revert to filled so user can retry
        logger.error(f"[executor] submit_job error for job {job_id}: {e}")
        return {"ok": False, "message": str(e)}
