"""
src/config package — Settings with Google AI + multi-model support.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    # Google AI Studio (primary — free tier)
    google_api_key: str = ""

    # Optional fallback providers
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Model selection (Gemini 2.5 split by task)
    llm_provider: str = "google"
    llm_model_fast: str = "gemini-2.5-flash"     # scraping, analysis, critic, form-filling
    llm_model_quality: str = "gemini-2.5-pro"    # JD analysis, resume routing

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

    def get_llm_fast(self):
        """Return a fast LLM instance (Flash) for high-volume tasks."""
        return self._make_llm(self.llm_model_fast)

    def get_llm_quality(self):
        """Return a quality LLM instance (Pro) for important decisions."""
        return self._make_llm(self.llm_model_quality)

    def _make_llm(self, model: str):
        if self.llm_provider == "google" or self.google_api_key:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model,
                google_api_key=self.google_api_key,
                temperature=0.3,
            )
        elif self.openai_api_key:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=model, api_key=self.openai_api_key)
        elif self.anthropic_api_key:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model, api_key=self.anthropic_api_key)
        raise ValueError("No LLM API key configured. Set GOOGLE_API_KEY in .env")

    def get_resume_path(self, category: str) -> Path:
        """Return path to resume PDF for a given category."""
        return self.resumes_dir / f"{category.lower()}.pdf"

    def list_resume_categories(self) -> list[str]:
        """Return all available resume categories based on PDFs in resumes_dir."""
        if not self.resumes_dir.exists():
            return []
        return [p.stem.lower() for p in self.resumes_dir.glob("*.pdf")]


settings = Settings()

__all__ = ["Settings", "settings"]
