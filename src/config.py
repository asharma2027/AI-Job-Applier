from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"

    # Credentials
    handshake_email: str = ""
    handshake_password: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""

    # Behavior
    auto_submit: bool = True
    scrape_interval_minutes: int = 60
    min_relevance_score: float = 0.5

    # Dashboard
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    secret_key: str = "change-me"

    # Database
    database_url: str = "sqlite+aiosqlite:///./job_applier.db"

    # Paths
    resumes_dir: Path = Path("./src/resumes")
    cover_letter_template: Path = Path("./src/templates/cover_letter_template.md")
    records_dir: Path = Path("./records")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_resume_path(self, category: str) -> Path:
        """Return path to resume PDF for a given category."""
        return self.resumes_dir / f"{category.lower()}.pdf"

    def list_resume_categories(self) -> list[str]:
        """Return all available resume categories based on PDFs in resumes_dir."""
        if not self.resumes_dir.exists():
            return []
        return [p.stem.lower() for p in self.resumes_dir.glob("*.pdf")]


settings = Settings()
