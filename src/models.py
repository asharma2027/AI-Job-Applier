"""
SQLAlchemy async models for the job application pipeline.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Text, Float, Boolean, Integer, Enum as SAEnum,
    ForeignKey, DateTime, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    new = "new"
    analyzing = "analyzing"
    analyzed = "analyzed"
    skipped = "skipped"        # below relevance threshold
    drafting_cl = "drafting_cl"              # legacy — kept for DB compat
    pending_cl_upload = "pending_cl_upload"  # waiting for user to upload cover letter
    awaiting_review = "awaiting_review"      # legacy — kept for DB compat
    queued = "queued"                        # ready for application
    filling = "filling"        # browser agent actively filling the form
    filled = "filled"          # form filled & saved — awaiting manual Submit click
    submitting = "submitting"  # browser agent clicking the final submit button
    applying = "applying"      # legacy alias kept for backward compat
    applied = "applied"
    failed = "failed"


class CoverLetterStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ApplicationStatus(str, enum.Enum):
    queued = "queued"
    in_progress = "in_progress"
    filled = "filled"          # form complete, submit not yet clicked
    submitted = "submitted"
    paused = "paused"          # legacy
    failed = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(256))
    description: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(128), nullable=False)  # handshake, linkedin, etc.
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), default=JobStatus.new, index=True)

    # Analysis results
    resume_type: Mapped[Optional[str]] = mapped_column(String(128))   # e.g. "finance", "consulting"
    cover_letter_required: Mapped[Optional[bool]] = mapped_column(Boolean)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)
    key_requirements: Mapped[Optional[list]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    cover_letter: Mapped[Optional["CoverLetter"]] = relationship(back_populates="job", uselist=False)
    application: Mapped[Optional["Application"]] = relationship(back_populates="job", uselist=False)


class CoverLetter(Base):
    __tablename__ = "cover_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, nullable=False)

    # The full draft (merged template + AI-generated sections)
    draft_content: Mapped[str] = mapped_column(Text, nullable=False)
    # Final content after user edits (same as draft if not edited)
    approved_content: Mapped[Optional[str]] = mapped_column(Text)

    # The copy-paste workflow: assembled prompt for user to feed into any LLM
    prompt_content: Mapped[Optional[str]] = mapped_column(Text)

    # Which sections were modified and what the AI generated for each
    # Format: {"section_name": {"original_boundary": "...", "generated": "..."}}
    modified_sections: Mapped[Optional[dict]] = mapped_column(JSON)

    status: Mapped[CoverLetterStatus] = mapped_column(
        SAEnum(CoverLetterStatus), default=CoverLetterStatus.pending, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    job: Mapped["Job"] = relationship(back_populates="cover_letter")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus), default=ApplicationStatus.queued, index=True
    )

    # Execution details
    screenshot_paths: Mapped[Optional[list]] = mapped_column(JSON)  # list of paths per page
    confirmation_text: Mapped[Optional[str]] = mapped_column(Text)
    error_log: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    job: Mapped["Job"] = relationship(back_populates="application")
