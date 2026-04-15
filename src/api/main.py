"""
FastAPI backend for the job application review dashboard.
Includes: cover letter upload queue, prompt copy workflow, screenshot viewing,
memory rule CRUD, cancellable agent tasks, and usage tracking.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func

from src.database import init_db, get_db
from src.models import Job, JobStatus, CoverLetter, CoverLetterStatus, Application, ApplicationStatus

logger = logging.getLogger(__name__)

app = FastAPI(title="Job Applier Dashboard", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await init_db()
    from src.activity import install_activity_handler
    install_activity_handler()
    logger.info("Database initialized.")


# ── Cancellable Task Registry ─────────────────────────────────────────────────

_running_tasks: dict[str, asyncio.Task] = {}


def _create_tracked_task(task_id: str, coro) -> asyncio.Task:
    """Create an asyncio task that auto-unregisters on completion."""
    task = asyncio.create_task(coro)
    _running_tasks[task_id] = task
    task.add_done_callback(lambda t: _running_tasks.pop(task_id, None))
    return task


@app.get("/api/agents/running")
async def list_running_agents():
    return {
        "tasks": {
            tid: {"running": not task.done(), "cancelled": task.cancelled()}
            for tid, task in _running_tasks.items()
            if not task.done()
        }
    }


@app.post("/api/agents/stop/{task_id}")
async def stop_agent(task_id: str):
    task = _running_tasks.get(task_id)
    if not task or task.done():
        raise HTTPException(404, f"No running task '{task_id}'")
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass
    return {"status": "cancelled", "task_id": task_id}


# ── Response Schemas ──────────────────────────────────────────────────────────

class JobOut(BaseModel):
    id: int
    title: str
    company: str
    location: Optional[str] = None
    url: str
    source: str
    status: str
    resume_type: Optional[str] = None
    cover_letter_required: Optional[bool] = None
    relevance_score: Optional[float] = None
    key_requirements: Optional[list] = None
    created_at: datetime
    class Config:
        from_attributes = True


class QueueItemOut(BaseModel):
    id: int
    job_id: int
    job_title: str
    job_company: str
    job_url: str
    job_description: Optional[str] = None
    prompt_content: Optional[str] = None
    status: str
    created_at: datetime
    class Config:
        from_attributes = True


class ApproveRequest(BaseModel):
    action: str  # "done" | "skip"


class StatsOut(BaseModel):
    total_sourced: int
    total_analyzed: int
    pending_cl_upload: int
    total_queued: int
    total_applied: int
    total_failed: int
    total_skipped: int
    total_new: int = 0


class RuleIn(BaseModel):
    agent: str
    description: str
    correction: str
    example_bad: str = ""
    severity: str = "medium"


class RuleUpdate(BaseModel):
    description: Optional[str] = None
    correction: Optional[str] = None
    example_bad: Optional[str] = None
    severity: Optional[str] = None
    enabled: Optional[bool] = None


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats", response_model=StatsOut)
async def get_stats():
    async with get_db() as db:
        total = (await db.execute(select(func.count(Job.id)))).scalar()
        analyzed = (await db.execute(
            select(func.count(Job.id)).where(Job.status.notin_([JobStatus.new, JobStatus.analyzing]))
        )).scalar()
        pending_cl = (await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.pending_cl_upload)
        )).scalar()
        queued = (await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.queued)
        )).scalar()
        applied = (await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.applied)
        )).scalar()
        failed = (await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.failed)
        )).scalar()
        skipped = (await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.skipped)
        )).scalar()
        new_count = (await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.new)
        )).scalar()

    return StatsOut(
        total_sourced=total,
        total_analyzed=analyzed,
        pending_cl_upload=pending_cl,
        total_queued=queued,
        total_applied=applied,
        total_failed=failed,
        total_skipped=skipped,
        total_new=new_count,
    )


# ── Activity Log ──────────────────────────────────────────────────────────────

@app.get("/api/activity")
async def get_activity(since_id: int = 0, limit: int = 200):
    from src.activity import activity_log
    events = activity_log.get_events(since_id=since_id, limit=limit)
    return {"events": events}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    from src.config import settings
    return settings.model_dump()

@app.patch("/api/settings")
async def update_settings_endpoint(updates: dict):
    from src.config import settings, update_env_file
    update_env_file(updates)
    return settings.model_dump()

# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.get("/api/jobs", response_model=list[JobOut])
async def list_jobs(status: Optional[str] = None, limit: int = 100, offset: int = 0):
    async with get_db() as db:
        query = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
        if status:
            try:
                status_enum = JobStatus(status)
                query = query.where(Job.status == status_enum)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        result = await db.execute(query)
        return result.scalars().all()


@app.get("/api/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: int):
    async with get_db() as db:
        job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/screenshots")
async def get_screenshots(job_id: int):
    async with get_db() as db:
        result = await db.execute(select(Application).where(Application.job_id == job_id))
        app_obj = result.scalar_one_or_none()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"screenshots": app_obj.screenshot_paths or []}


@app.get("/api/screenshots/view")
async def view_screenshot(path: str):
    p = Path(path)
    if not p.exists() or not p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path)


# ── Pending Cover Letter Upload Queue ─────────────────────────────────────────

@app.get("/api/queue", response_model=list[QueueItemOut])
async def list_queue():
    """Return all jobs awaiting cover letter upload by the user."""
    async with get_db() as db:
        result = await db.execute(
            select(CoverLetter, Job)
            .join(Job, CoverLetter.job_id == Job.id)
            .where(CoverLetter.status == CoverLetterStatus.pending)
            .order_by(Job.relevance_score.desc())
        )
        rows = result.all()

    return [
        QueueItemOut(
            id=cl.id,
            job_id=cl.job_id,
            job_title=job.title,
            job_company=job.company,
            job_url=job.url,
            job_description=job.description,
            prompt_content=cl.prompt_content,
            status=cl.status,
            created_at=cl.created_at,
        )
        for cl, job in rows
    ]


@app.get("/api/queue/{cl_id}", response_model=QueueItemOut)
async def get_queue_item(cl_id: int):
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Queue item not found")
        job = await db.get(Job, cl.job_id)
    return QueueItemOut(
        id=cl.id, job_id=cl.job_id, job_title=job.title, job_company=job.company,
        job_url=job.url, job_description=job.description,
        prompt_content=cl.prompt_content, status=cl.status, created_at=cl.created_at,
    )


@app.put("/api/queue/{cl_id}")
async def review_queue_item(cl_id: int, body: ApproveRequest):
    """Mark a pending CL upload as done (user uploaded CL) or skip."""
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Queue item not found")
        job = await db.get(Job, cl.job_id)

        if body.action == "done":
            cl.status = CoverLetterStatus.approved
            cl.reviewed_at = datetime.utcnow()
            job.status = JobStatus.queued
        elif body.action == "skip":
            cl.status = CoverLetterStatus.rejected
            cl.reviewed_at = datetime.utcnow()
            job.status = JobStatus.skipped
        else:
            raise HTTPException(status_code=400, detail="action must be 'done' or 'skip'")

    return {"status": "ok", "action": body.action}


# ── Notification Polling ─────────────────────────────────────────────────────

@app.get("/api/notifications/pending-count")
async def pending_cl_count():
    """Lightweight endpoint for the dashboard to poll for new pending CL uploads."""
    async with get_db() as db:
        count = (await db.execute(
            select(func.count(CoverLetter.id)).where(CoverLetter.status == CoverLetterStatus.pending)
        )).scalar()
    return {"count": count}


# ── Memory / Correction Rules ─────────────────────────────────────────────────

@app.get("/api/memory")
async def get_all_rules():
    from src.memory.memory_store import get_all_rules
    return get_all_rules()


@app.post("/api/memory")
async def create_rule(body: RuleIn):
    from src.memory.memory_store import add_rule
    agents = {"analyzer", "executor", "sourcer"}
    if body.agent not in agents:
        raise HTTPException(status_code=400, detail=f"agent must be one of {agents}")
    rule = add_rule(
        agent=body.agent,
        description=body.description,
        correction=body.correction,
        example_bad=body.example_bad,
        severity=body.severity,
    )
    return rule


@app.patch("/api/memory/{rule_id}")
async def update_rule(rule_id: str, body: RuleUpdate):
    from src.memory.memory_store import update_rule
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    rule = update_rule(rule_id, **updates)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@app.delete("/api/memory/{rule_id}")
async def delete_rule(rule_id: str):
    from src.memory.memory_store import delete_rule
    if not delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted"}


@app.post("/api/memory/condense/{agent}")
async def condense_memory(agent: str):
    from src.memory.memory_store import condense_rules
    valid_agents = {"analyzer", "executor", "sourcer"}
    if agent not in valid_agents:
        raise HTTPException(400, f"agent must be one of {valid_agents}")
    await condense_rules(agent)
    return {"status": "ok", "agent": agent}


# ── Cover Letter Examples (samples for matching) ──────────────────────────────

@app.get("/api/cover-letter/examples")
async def list_examples():
    from src.config import settings
    from src.agents.cover_letter import extract_pdf_text

    examples = settings.list_cover_letter_examples()
    result = []
    for pdf_path in examples:
        text = extract_pdf_text(pdf_path)
        result.append({
            "filename": pdf_path.name,
            "text_preview": text[:500] if text else "(could not extract text)",
            "full_text": text,
            "size_bytes": pdf_path.stat().st_size,
        })
    return result


@app.post("/api/cover-letter/examples")
async def upload_example(file: UploadFile = File(...)):
    from src.config import settings

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    examples_dir = settings.cover_letter_examples_dir
    examples_dir.mkdir(parents=True, exist_ok=True)

    dest = examples_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)

    from src.agents.cover_letter import extract_pdf_text
    text = extract_pdf_text(dest)

    return {
        "filename": file.filename,
        "text_preview": text[:500] if text else "(could not extract text)",
        "size_bytes": len(content),
    }


@app.delete("/api/cover-letter/examples/{filename}")
async def delete_example(filename: str):
    from src.config import settings

    file_path = settings.cover_letter_examples_dir / filename
    if not file_path.exists() or not file_path.suffix.lower() == ".pdf":
        raise HTTPException(status_code=404, detail="Example not found")
    file_path.unlink()
    return {"status": "deleted", "filename": filename}


# ── Profile ──────────────────────────────────────────────────────────────────

@app.get("/api/profile")
async def get_profile():
    import yaml
    profile_path = Path("src/config/profile.yaml")
    if not profile_path.exists():
        return {}
    with open(profile_path) as f:
        return yaml.safe_load(f) or {}


@app.patch("/api/profile")
async def update_profile(updates: dict):
    import yaml
    profile_path = Path("src/config/profile.yaml")

    existing = {}
    if profile_path.exists():
        with open(profile_path) as f:
            existing = yaml.safe_load(f) or {}

    def deep_merge(base: dict, overlay: dict) -> dict:
        for k, v in overlay.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    merged = deep_merge(existing, updates)

    with open(profile_path, "w") as f:
        yaml.dump(merged, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return merged


# ── Sourcing (cancellable) ────────────────────────────────────────────────────

_sourcing_running: set[str] = set()


class SourceResult(BaseModel):
    platform: str
    found: int
    new_jobs: int
    error: Optional[str] = None
    running: bool = False


@app.get("/api/source/status")
async def source_status():
    from src.agents.sourcer import ENABLED_PLATFORMS, PLATFORM_SCRAPERS
    return {
        "running": list(_sourcing_running),
        "enabled_platforms": list(ENABLED_PLATFORMS),
        "all_platforms": list(PLATFORM_SCRAPERS.keys()),
    }


@app.post("/api/source/{platform}", response_model=SourceResult)
async def trigger_source(platform: str):
    from src.agents.sourcer import PLATFORM_SCRAPERS, ENABLED_PLATFORMS

    if platform not in PLATFORM_SCRAPERS:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    if platform not in ENABLED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"'{platform}' is not yet enabled.")

    task_id = f"source_{platform}"
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        return SourceResult(platform=platform, found=0, new_jobs=0, running=True)

    async def _run():
        _sourcing_running.add(platform)
        try:
            from src.agents.sourcer import run_platform_scrape
            await run_platform_scrape(platform)
        except asyncio.CancelledError:
            logger.info(f"[sourcer] {platform} scrape cancelled by user")
        except Exception as e:
            logger.error(f"[sourcer] {platform} scrape failed: {e}")
        finally:
            _sourcing_running.discard(platform)

    _create_tracked_task(task_id, _run())
    return SourceResult(platform=platform, found=0, new_jobs=0, running=True)


# ── Analyze (manual trigger, cancellable) ─────────────────────────────────────

@app.post("/api/analyze")
async def trigger_analyze():
    task_id = "analyze"
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        return {"ok": False, "message": "Analysis already running"}

    async def _run():
        try:
            from src.agents.analyzer import run_analyzer
            analyzed, queued = await run_analyzer()
            logger.info(f"[api] Analysis complete: {analyzed} analyzed, {queued} queued")
        except asyncio.CancelledError:
            logger.info("[api] Analysis cancelled by user")
        except Exception as e:
            logger.error(f"[api] Analysis failed: {e}")

    _create_tracked_task(task_id, _run())
    return {"ok": True, "message": "Analysis started in background. Watch the Activity Log."}


# ── Application Stages (cancellable) ──────────────────────────────────────────

_jobs_filling: set[int] = set()
_jobs_submitting: set[int] = set()


@app.get("/api/pipeline/status")
async def pipeline_status():
    from src.agents.executor import open_browser_session_ids
    return {
        "filling": list(_jobs_filling),
        "submitting": list(_jobs_submitting),
        "sourcing": list(_sourcing_running),
        "analyzing": "analyze" in _running_tasks and not _running_tasks.get("analyze", asyncio.Future()).done(),
        "running_tasks": [tid for tid, t in _running_tasks.items() if not t.done()],
        "browser_open": open_browser_session_ids(),  # job IDs with browser windows kept alive
    }


@app.post("/api/jobs/{job_id}/fill")
async def trigger_fill(job_id: int):
    task_id = f"fill_{job_id}"
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        return {"ok": False, "message": "Fill already in progress for this job"}

    async with get_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status not in (JobStatus.queued, JobStatus.failed, JobStatus.filled):
            raise HTTPException(
                status_code=400,
                detail=f"Job is in status '{job.status}'. Must be 'queued' to fill."
            )
        # Enforce max pending submissions limit
        from src.config import settings as _settings
        filled_count_result = await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.filled)
        )
        filled_count = filled_count_result.scalar() or 0
        if filled_count >= _settings.max_pending_submissions:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"You already have {filled_count} application(s) waiting for your review "
                    f"(limit: {_settings.max_pending_submissions}). Switch to the open browser "
                    "window(s), submit those applications, and confirm them in the dashboard first."
                ),
            )

    async def _run():
        _jobs_filling.add(job_id)
        try:
            from src.agents.executor import fill_job
            await fill_job(job_id)
        except asyncio.CancelledError:
            logger.info(f"[executor] Fill cancelled for job {job_id}")
            from src.agents.executor import close_fill_session
            await close_fill_session(job_id)
            async with get_db() as db:
                job_db = await db.get(Job, job_id)
                if job_db and job_db.status == JobStatus.filling:
                    job_db.status = JobStatus.queued
        except Exception as e:
            logger.error(f"[executor] Fill failed for job {job_id}: {e}")
        finally:
            _jobs_filling.discard(job_id)

    _create_tracked_task(task_id, _run())
    return {"ok": True, "message": "Fill started in background. Watch the Activity Log for progress."}


@app.post("/api/jobs/{job_id}/submit")
async def trigger_submit(job_id: int):
    task_id = f"submit_{job_id}"
    if task_id in _running_tasks and not _running_tasks[task_id].done():
        return {"ok": False, "message": "Submit already in progress for this job"}

    async with get_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != JobStatus.filled:
            raise HTTPException(
                status_code=400,
                detail=f"Job is in status '{job.status}'. Must be 'filled' to submit."
            )

    async def _run():
        _jobs_submitting.add(job_id)
        try:
            from src.agents.executor import submit_job
            await submit_job(job_id)
        except asyncio.CancelledError:
            logger.info(f"[executor] Submit cancelled for job {job_id}")
            async with get_db() as db:
                job_db = await db.get(Job, job_id)
                if job_db and job_db.status == JobStatus.submitting:
                    job_db.status = JobStatus.filled
        except Exception as e:
            logger.error(f"[executor] Submit failed for job {job_id}: {e}")
        finally:
            _jobs_submitting.discard(job_id)

    _create_tracked_task(task_id, _run())
    return {"ok": True, "message": "Submit started in background. Watch the Activity Log for progress."}


@app.post("/api/jobs/{job_id}/confirm-submitted")
async def confirm_submitted(job_id: int):
    """Mark a job as applied after the user manually clicked the submit button on the application page."""
    from src.agents.executor import close_fill_session
    await close_fill_session(job_id)
    async with get_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != JobStatus.filled:
            raise HTTPException(
                status_code=400,
                detail=f"Job is in status '{job.status}'. Must be 'filled' to confirm submission.",
            )
        job.status = JobStatus.applied
        app_result = await db.execute(
            select(Application).where(Application.job_id == job_id).order_by(Application.id.desc())
        )
        app_db = app_result.scalars().first()
        if app_db:
            app_db.status = ApplicationStatus.submitted
            app_db.submitted_at = datetime.utcnow()
        await db.commit()
    return {"ok": True, "status": "applied"}


@app.post("/api/jobs/{job_id}/discard-fill")
async def discard_fill(job_id: int):
    """Close the browser kept open for review and reset job back to queued so it can be re-filled."""
    from src.agents.executor import close_fill_session
    await close_fill_session(job_id)
    async with get_db() as db:
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != JobStatus.filled:
            raise HTTPException(
                status_code=400,
                detail=f"Job is in status '{job.status}'. Must be 'filled' to discard.",
            )
        job.status = JobStatus.queued
        app_result = await db.execute(
            select(Application).where(Application.job_id == job_id).order_by(Application.id.desc())
        )
        app_db = app_result.scalars().first()
        if app_db:
            app_db.status = ApplicationStatus.queued
        await db.commit()
    return {"ok": True, "status": "queued"}


# ── Usage Tracking ────────────────────────────────────────────────────────────

@app.get("/api/usage")
async def get_usage():
    from src.usage import get_usage_summary
    return get_usage_summary()


@app.get("/api/usage/gauge")
async def get_usage_gauge():
    from src.usage import get_gauge_data
    return get_gauge_data()


@app.patch("/api/usage/plan")
async def update_usage_plan(body: dict):
    from src.usage import update_plan
    return update_plan(
        plan_type=body.get("plan_type"),
        custom_limits=body.get("custom_limits"),
        monthly_budget_usd=body.get("monthly_budget_usd"),
    )


# ── Serve dashboard SPA ───────────────────────────────────────────────────────

_dashboard_dist = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "dist")
if os.path.isdir(_dashboard_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dashboard_dist, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(os.path.join(_dashboard_dist, "index.html"))
