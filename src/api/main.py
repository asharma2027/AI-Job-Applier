"""
FastAPI backend for the job application review dashboard.
"""
from __future__ import annotations

import logging
from datetime import datetime
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

app = FastAPI(title="Job Applier Dashboard", version="0.1.0")

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


# ─────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────
class JobOut(BaseModel):
    id: int
    title: str
    company: str
    location: Optional[str]
    url: str
    source: str
    status: str
    resume_type: Optional[str]
    cover_letter_required: Optional[bool]
    relevance_score: Optional[float]
    key_requirements: Optional[list]
    created_at: datetime

    class Config:
        from_attributes = True


class CoverLetterOut(BaseModel):
    id: int
    job_id: int
    job_title: str
    job_company: str
    draft_content: str
    approved_content: Optional[str]
    status: str
    modified_sections: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True


class ApproveRequest(BaseModel):
    content: str  # final approved content (may be edited by user)
    action: str   # "approve" | "reject"


class StatsOut(BaseModel):
    total_sourced: int
    total_analyzed: int
    pending_review: int
    total_queued: int
    total_applied: int
    total_failed: int
    total_skipped: int


# ─────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────
@app.get("/api/stats", response_model=StatsOut)
async def get_stats():
    async with get_db() as db:
        def count(status):
            return func.count(Job.id).filter(Job.status == status)

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


# ─────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────
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
        jobs = result.scalars().all()
    return jobs


@app.get("/api/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: int):
    async with get_db() as db:
        job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ─────────────────────────────────────────────
# Cover Letter Review Queue
# ─────────────────────────────────────────────
@app.get("/api/queue", response_model=list[CoverLetterOut])
async def list_queue():
    """Return all pending cover letters for review."""
    async with get_db() as db:
        result = await db.execute(
            select(CoverLetter, Job)
            .join(Job, CoverLetter.job_id == Job.id)
            .where(CoverLetter.status == CoverLetterStatus.pending)
            .order_by(Job.relevance_score.desc())
        )
        rows = result.all()

    out = []
    for cl, job in rows:
        out.append(CoverLetterOut(
            id=cl.id,
            job_id=cl.job_id,
            job_title=job.title,
            job_company=job.company,
            draft_content=cl.draft_content,
            approved_content=cl.approved_content,
            status=cl.status,
            modified_sections=cl.modified_sections,
            created_at=cl.created_at,
        ))
    return out


@app.get("/api/queue/{cl_id}", response_model=CoverLetterOut)
async def get_queue_item(cl_id: int):
    async with get_db() as db:
        cl = await db.get(CoverLetter, cl_id)
        if not cl:
            raise HTTPException(status_code=404, detail="Cover letter not found")
        job = await db.get(Job, cl.job_id)
    return CoverLetterOut(
        id=cl.id,
        job_id=cl.job_id,
        job_title=job.title,
        job_company=job.company,
        draft_content=cl.draft_content,
        approved_content=cl.approved_content,
        status=cl.status,
        modified_sections=cl.modified_sections,
        created_at=cl.created_at,
    )


@app.put("/api/queue/{cl_id}")
async def review_cover_letter(cl_id: int, body: ApproveRequest):
    """Approve or reject a cover letter. Updates job status accordingly."""
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


# ─────────────────────────────────────────────
# Serve dashboard SPA (if built)
# ─────────────────────────────────────────────
import os
_dashboard_dist = os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist")
if os.path.isdir(_dashboard_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dashboard_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index = os.path.join(_dashboard_dist, "index.html")
        return FileResponse(index)
