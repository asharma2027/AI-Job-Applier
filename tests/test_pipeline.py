"""
Basic pipeline integration test.
Seeds a mock job, runs the analysis prompt parsing, tests DB operations.
"""
import asyncio
import pytest
from src.database import init_db, get_db
from src.models import Job, JobStatus


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True, scope="module")
async def setup_db(tmp_path_factory):
    """Initialize a test database."""
    import os
    db_path = tmp_path_factory.mktemp("data") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    # Re-import after env change
    from importlib import reload
    import src.config as cfg
    import src.database as db_mod
    reload(cfg)
    reload(db_mod)
    await db_mod.init_db()


@pytest.mark.asyncio
async def test_create_and_retrieve_job():
    """Test that a job can be created and retrieved from the DB."""
    from src.database import get_db
    from src.models import Job, JobStatus

    async with get_db() as db:
        job = Job(
            url="https://example.com/job/123",
            title="Software Engineering Intern",
            company="Test Corp",
            source="test",
            status=JobStatus.new,
        )
        db.add(job)

    from sqlalchemy import select
    async with get_db() as db:
        result = await db.execute(select(Job).where(Job.url == "https://example.com/job/123"))
        retrieved = result.scalar_one_or_none()
        assert retrieved is not None
        assert retrieved.title == "Software Engineering Intern"
        assert retrieved.status == JobStatus.new


@pytest.mark.asyncio
async def test_cover_letter_user_prompt_building():
    """Test that the user-facing prompt builder produces a valid prompt."""
    from src.agents.cover_letter import build_user_prompt

    prompt = build_user_prompt(
        job_title="Software Engineering Intern",
        job_company="Test Corp",
        job_description="We are looking for an intern with Python and SQL skills.",
        cover_letter_text="Dear Hiring Manager, I am writing to express my interest...",
    )
    assert "Software Engineering Intern" in prompt
    assert "Test Corp" in prompt
    assert "Python" in prompt
    assert "cover letter to modify" in prompt
    assert "Dear Hiring Manager" in prompt


@pytest.mark.asyncio
async def test_pdf_text_extraction():
    """Test that PDF text extraction works on example files."""
    from src.agents.cover_letter import extract_pdf_text
    from pathlib import Path

    pdf_path = Path("src/templates/financecoverletter.pdf")
    if pdf_path.exists():
        text = extract_pdf_text(pdf_path)
        assert len(text) > 100
        assert "Arjun" in text


@pytest.mark.asyncio
async def test_api_endpoints():
    """Test that FastAPI endpoints return expected shapes."""
    from httpx import AsyncClient, ASGITransport
    from src.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_sourced" in data

        r = await client.get("/api/jobs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

        r = await client.get("/api/queue")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
