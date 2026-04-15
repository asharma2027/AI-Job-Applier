"""
src/config package — Settings with Google AI + multi-model support.
"""
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

logger = logging.getLogger(__name__)


def _wrap_with_usage_tracking(llm, model_name: str):
    """Monkey-patch ainvoke to record usage stats transparently."""
    from src.usage import record_usage

    original_ainvoke = llm.ainvoke

    async def tracked_ainvoke(*args, **kwargs):
        try:
            result = await original_ainvoke(*args, **kwargs)
            input_tokens = 0
            output_tokens = 0
            um = getattr(result, "usage_metadata", None)
            if um:
                input_tokens = um.get("input_tokens", 0)
                output_tokens = um.get("output_tokens", 0)
            elif hasattr(result, "response_metadata"):
                meta = result.response_metadata or {}
                um2 = meta.get("usage_metadata", meta.get("token_usage", {}))
                input_tokens = um2.get("input_tokens", um2.get("prompt_tokens", 0))
                output_tokens = um2.get("output_tokens", um2.get("completion_tokens", 0))
            record_usage(model_name, input_tokens, output_tokens)
            return result
        except Exception:
            record_usage(model_name, 0, 0, error=True)
            raise

    llm.ainvoke = tracked_ainvoke
    return llm


class Settings(BaseSettings):
    # Google AI Studio (primary — Paid Tier 1)
    google_api_key: str = ""
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"

    # Optional fallback provider
    openai_api_key: str = ""

    # Model selection (best-in-class per task, April 2026)
    llm_provider: str = "google"
    # Fast: Gemini 3 Flash — 3× faster than Pro, leads SWE-bench coding (78%), cheapest Google model.
    # Used for: scraping, form-filling, quick analysis, boilerplate generation.
    llm_model_fast: str = "gemini-3-flash"
    # Quality: Gemini 3.1 Pro — deepest Google reasoning, 2M context, best for complex multi-step tasks.
    # Used for: JD analysis, resume category routing, long-context document understanding.
    llm_model_quality: str = "gemini-3.1-pro"
    # Analyzer: Grok 4.20 Multi-Agent — 4-agent internal debate, 65% lower hallucination rate,
    # 2M context. Best for high-stakes structured extraction (JD parsing, fit scoring).
    llm_model_analyzer: str = "grok-4.20-multi-agent-0309"
    # Critic: Grok 4.1 Fast Reasoning — fast reasoning at $0.20/$0.50 per 1M tokens.
    # Ideal for self-refine passes: verify, critique, and tighten generated content cheaply.
    llm_model_critic: str = "grok-4-1-fast-reasoning"
    # Browser Fast: Gemini 3 Flash — low latency, handles multimodal page content well.
    llm_model_browser_fast: str = "gemini-3-flash"
    # Browser Quality: Gemini 2.5 Flash — battle-tested with browser-use library for complex automation.
    llm_model_browser_quality: str = "gemini-2.5-flash"

    # Credentials
    handshake_email: str = ""
    handshake_password: str = ""
    uchicago_cnet_id: str = ""
    uchicago_password: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""

    # Stealth / Anti-detection
    stealth_tier: str = "camoufox"       # camoufox | patchright | none
    stealth_proxy: str = ""              # optional proxy URL (residential recommended)
    stealth_headless: bool = False       # visible browser so you can watch & verify each step

    # Cover letter examples (for matching)
    cover_letter_examples_dir: Path = Path("./src/templates")

    # Local model for CL selection (runs on Ollama)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"

    # Behavior
    auto_submit: bool = False
    dry_run: bool = False
    scrape_interval_minutes: int = 60
    min_relevance_score: float = 0.5
    max_pending_submissions: int = 2  # max jobs that can be in 'filled' state at once

    # Dashboard
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    secret_key: str = "change-me"

    # Database
    database_url: str = "sqlite+aiosqlite:///./job_applier.db"

    # Paths
    resumes_dir: Path = Path("./src/resumes")
    records_dir: Path = Path("./records")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_llm_fast(self):
        """Return a fast LangChain LLM (Flash) for direct ainvoke usage in analysis/generation."""
        return self._make_langchain_llm(self.llm_model_fast)

    def get_llm_quality(self):
        """Return a quality LangChain LLM (Pro) for direct ainvoke usage in analysis/generation."""
        return self._make_langchain_llm(self.llm_model_quality)

    def get_browser_use_llm_fast(self):
        """Return a fast browser-use native LLM (Flash) for browser-use Agent tasks."""
        return self._make_browser_use_llm(self.llm_model_browser_fast or self.llm_model_fast)

    def get_browser_use_llm_quality(self):
        """Return a quality browser-use native LLM (Pro) for browser-use Agent tasks."""
        return self._make_browser_use_llm(self.llm_model_browser_quality or self.llm_model_quality)

    def get_llm_for_task(self, task: str):
        """Task-aware LLM routing with conservative fallbacks."""
        task = (task or "").strip().lower()
        if task == "analyzer":
            model = self.llm_model_analyzer or self.llm_model_quality
        elif task == "critic":
            model = self.llm_model_critic or self.llm_model_fast
        else:
            model = self.llm_model_quality
        return self._make_langchain_llm(model)

    def get_browser_use_llm_for_task(self, task: str, quality: bool = False):
        """Task-aware browser-use routing (kept stable on providers browser-use supports well)."""
        task = (task or "").strip().lower()
        if quality:
            model = self.llm_model_browser_quality or self.llm_model_quality
        else:
            model = self.llm_model_browser_fast or self.llm_model_fast
        if task not in {"sourcer", "executor"}:
            model = self.llm_model_browser_fast or self.llm_model_fast
        return self._make_browser_use_llm(model)

    def _provider_for_model(self, model: str) -> tuple[str, bool]:
        """Infer provider from model name when explicit; otherwise use llm_provider."""
        m = (model or "").lower()
        if m.startswith("grok-"):
            return "xai", True
        if m.startswith("gemini-"):
            return "google", True
        if m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
            return "openai", True
        return (self.llm_provider or "google").lower(), False

    def _fallback_provider(self) -> str | None:
        if self.google_api_key:
            return "google"
        if self.openai_api_key:
            return "openai"
        if self.xai_api_key:
            return "xai"
        return None

    def _make_langchain_llm(self, model: str):
        """Return a LangChain chat model for direct ainvoke(string/messages) calls."""
        provider, inferred = self._provider_for_model(model)
        if provider == "google" and self.google_api_key:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model=model,
                google_api_key=self.google_api_key,
                temperature=0.3,
            )
        elif provider == "openai" and self.openai_api_key:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=model, api_key=self.openai_api_key)
        elif provider == "xai" and self.xai_api_key:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model=model, api_key=self.xai_api_key, base_url=self.xai_base_url)
        else:
            if inferred:
                raise ValueError(
                    f"Model '{model}' requires provider '{provider}', but its API key is not configured."
                )
            fallback = self._fallback_provider()
            if not fallback:
                raise ValueError(
                    "No LLM API key configured. Set at least one of GOOGLE_API_KEY, XAI_API_KEY, or OPENAI_API_KEY in .env"
                )
            logger.warning(
                "[config] Requested provider '%s' unavailable for model '%s'. Falling back to '%s'.",
                provider,
                model,
                fallback,
            )
            if fallback == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI
                llm = ChatGoogleGenerativeAI(
                    model=model,
                    google_api_key=self.google_api_key,
                    temperature=0.3,
                )
            elif fallback == "openai":
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(model=model, api_key=self.openai_api_key)
            else:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(model=model, api_key=self.xai_api_key, base_url=self.xai_base_url)
        return _wrap_with_usage_tracking(llm, model)

    def _make_browser_use_llm(self, model: str):
        """Return a browser-use native BaseChatModel for browser-use Agent tasks (0.12+)."""
        provider, inferred = self._provider_for_model(model)
        if provider == "xai":
            # browser-use native adapters vary by release; keep browser automation on stable providers.
            fallback_model = self.llm_model_browser_fast or self.llm_model_fast
            if model != fallback_model:
                logger.warning(
                    "[config] Grok model '%s' requested for browser-use; using '%s' to keep browser agent stable.",
                    model,
                    fallback_model,
                )
            model = fallback_model
            provider, inferred = self._provider_for_model(model)
        if provider == "google" and self.google_api_key:
            from browser_use.llm.google.chat import ChatGoogle
            llm = ChatGoogle(model=model, api_key=self.google_api_key or None)
        elif provider == "openai" and self.openai_api_key:
            from browser_use.llm.openai.chat import ChatOpenAI
            llm = ChatOpenAI(model=model, api_key=self.openai_api_key)
        else:
            if inferred:
                raise ValueError(
                    f"Browser-use model '{model}' requires provider '{provider}', but its API key is not configured."
                )
            fallback = self._fallback_provider()
            if fallback == "xai":
                fallback = (
                    "google"
                    if self.google_api_key
                    else "openai"
                    if self.openai_api_key
                    else None
                )
            if not fallback:
                raise ValueError(
                    "No browser-use compatible API key configured. Set GOOGLE_API_KEY or OPENAI_API_KEY in .env"
                )
            logger.warning(
                "[config] Browser-use provider '%s' unavailable for model '%s'. Falling back to '%s'.",
                provider,
                model,
                fallback,
            )
            if fallback == "google":
                from browser_use.llm.google.chat import ChatGoogle
                llm = ChatGoogle(model=model, api_key=self.google_api_key or None)
            else:
                from browser_use.llm.openai.chat import ChatOpenAI
                llm = ChatOpenAI(model=model, api_key=self.openai_api_key)
        return _wrap_with_usage_tracking(llm, model)

    def get_resume_path(self, category: str) -> Path:
        """Return path to resume PDF for a given category."""
        return self.resumes_dir / f"{category.lower()}.pdf"

    def list_resume_categories(self) -> list[str]:
        """Return all available resume categories based on PDFs in resumes_dir."""
        if not self.resumes_dir.exists():
            return []
        return [p.stem.lower() for p in self.resumes_dir.glob("*.pdf")]

    def list_cover_letter_examples(self) -> list[Path]:
        """Return paths to all example cover letter PDFs."""
        d = self.cover_letter_examples_dir
        if not d.exists():
            return []
        return sorted(d.glob("*.pdf"))


settings = Settings()

import os
def update_env_file(updates: dict):
    """Update the .env file iteratively to preserve comments and update memory settings."""
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    for k, v in updates.items():
        key = k.upper()
        found = False
        for i, line in enumerate(lines):
            line_str = line.strip()
            if line_str.startswith(key + "=") or line_str.startswith(f"#{key}=") or line_str.startswith(f"# {key}="):
                lines[i] = f"{key}={v}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={v}\n")
            
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    # Update in-memory settings
    for k, v in updates.items():
        if hasattr(settings, k):
            if k in ('auto_submit', 'dry_run', 'stealth_headless'):
                v = str(v).lower() in ('true', '1', 't', 'y', 'yes')
            elif k in ['scrape_interval_minutes', 'dashboard_port', 'max_pending_submissions']:
                v = int(v)
            elif k == 'min_relevance_score':
                v = float(v)
            setattr(settings, k, v)

__all__ = ["Settings", "settings", "update_env_file"]