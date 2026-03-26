"""
FastAPI backend for the job application review dashboard.
Includes: cover letter queue, prompt copy/paste workflow, screenshotviewing,
memory rule CRUD, and stats.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, func

from src.database import init_db, get_db
from src.models import Job, JobStatus, CoverLetter, CoverLetterStatus, Application, ApplicationStatus

logger = logging.getLogger(__name__)

app = FastAPI(title="Job Applier Dashboard", version="0.2.0")

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
    logger.info("Database initialized.")


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


class CoverLetterOut(BaseModel):
    id: int
    job_id: int
    job_title: str
    job_company: str
    draft_content: str
    prompt_content: Optional[str] = None
    approved_content: Optional[str] = None
    status: str
    modified_sections: Optional[dict] = None
    created_at: datetime
    class Config:
        from_attributes = True


class ApproveRequest(BaseModel):
    content: str
    action: str  # "approve" | "reject"


class PasteRequest(BaseModel):
    pasted_response: str  # Raw LLM output from user


class StatsOut(BaseModel):
    total_sourced: int
    total_analyzed: int
    pending_review: int
    total_queued: int
    total_applied: int
    total_failed: int
    total_skipped: int


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
        pending = (await db.execute(
            select(func.count(CoverLetter.id)).where(CoverLetter.status == CoverLetterStatus.pending)
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

    return StatsOut(
        total_sourced=total,
        total_analyzed=analyzed,
        pending_review=pending,
        total_queued=queued,
        total_applied=applied,
        total_failed=failed,
        total_skipped=skipped,
    )


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    from src.config import settings
    # We can safely return the dump because this is a local dashboard
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
    """Return list of screenshot paths for a job's application."""
    async with get_db() as db:
        result = await db.execute(select(Application).where(Application.job_id == job_id))
        app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"screenshots": app.screenshot_paths or []}


@app.get("/api/screenshots/view")
async def view_screenshot(path: str):
    """Serve a screenshot image by absolute path."""
    p = Path(path)
    if not p.exists() or not p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path)


# ── Cover Letter Queue ────────────────────────────────────────────────────────

@app.get("/api/queue", response_model=list[CoverLetterOut])
async def list_queue():
    async with get_db() as db:
        result = await db.execute(
            select(CoverLetter, Job)
            .join(Job, CoverLetter.job_id == Job.id)
            .where(CoverLetter.status == CoverLetterStatus.pending)
            .order_by(Job.relevance_score.desc())
        )
        rows = result.all()

    return [
        CoverLetterOut(
            id=cl.id,
            job_id=cl.job_id,
            job_title=job.title,
            job_company=job.company,
            draft_content=cl.draft_content,
            prompt_content=cl.prompt_content,
            approved_content=cl.approved_content,
            status=cl.status,
            modified_sections=cl.modified_sections,
            created_at=cl.created_at,
        )
        for cl, job in rows
    ]


@app.get("/api/queue/{cl_id}", response_model=CoverLetterOut)
async def get_queue_item(cl_id: int):
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Cover letter not found")
        job = await db.get(Job, cl.job_id)
    return CoverLetterOut(
        id=cl.id, job_id=cl.job_id, job_title=job.title, job_company=job.company,
        draft_content=cl.draft_content, prompt_content=cl.prompt_content,
        approved_content=cl.approved_content, status=cl.status,
        modified_sections=cl.modified_sections, created_at=cl.created_at,
    )


@app.get("/api/queue/{cl_id}/prompt")
async def get_prompt(cl_id: int):
    """Return the copy-ready LLM prompt for this cover letter."""
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Cover letter not found")
    return {"prompt": cl.prompt_content or "No prompt generated yet."}


@app.post("/api/queue/{cl_id}/paste")
async def paste_response(cl_id: int, body: PasteRequest):
    """
    Accept a pasted LLM response, parse sections, apply to template, and
    store the merged draft for user review.
    """
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Cover letter not found")

    from src.config import settings
    from src.agents.cover_letter import apply_pasted_response

    template_path = settings.cover_letter_template
    template = template_path.read_text() if template_path.exists() else cl.draft_content

    merged, sections = apply_pasted_response(template, body.pasted_response)

    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        cl.draft_content = merged
        cl.modified_sections = sections

    return {"draft_content": merged, "sections_applied": list(sections.keys())}


@app.put("/api/queue/{cl_id}")
async def review_cover_letter(cl_id: int, body: ApproveRequest):
    """Approve or reject a cover letter."""
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Cover letter not found")
        job = await db.get(Job, cl.job_id)

        if body.action == "approve":
            cl.approved_content = body.content
            cl.status = CoverLetterStatus.approved
            cl.reviewed_at = datetime.utcnow()
            job.status = JobStatus.queued
        elif body.action == "reject":
            cl.status = CoverLetterStatus.rejected
            cl.reviewed_at = datetime.utcnow()
            job.status = JobStatus.skipped
        else:
            raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    return {"status": "ok", "action": body.action}


# ── Memory / Correction Rules ─────────────────────────────────────────────────

@app.get("/api/memory")
async def get_all_rules():
    """Return all correction rules for all agents."""
    from src.memory.memory_store import get_all_rules
    return get_all_rules()


@app.post("/api/memory")
async def create_rule(body: RuleIn):
    """Create a new correction rule."""
    from src.memory.memory_store import add_rule
    agents = {"analyzer", "cover_letter", "executor", "sourcer"}
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
    """Update fields on an existing rule."""
    from src.memory.memory_store import update_rule
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    rule = update_rule(rule_id, **updates)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@app.delete("/api/memory/{rule_id}")
async def delete_rule(rule_id: str):
    """Delete a correction rule."""
    from src.memory.memory_store import delete_rule
    if not delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted"}


# ── Serve dashboard SPA ───────────────────────────────────────────────────────

_dashboard_dist = os.path.join(os.path.dirname(__file__), "..", "..", "dashboard", "dist")
if os.path.isdir(_dashboard_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dashboard_dist, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(os.path.join(_dashboard_dist, "index.html"))
