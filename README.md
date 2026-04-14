# Job Applier Agent 🤖

An autonomous background agent that sources internship listings, analyzes them, routes the right resume, and auto-fills & submits applications across any ATS. When a cover letter is required, you are notified and given a ready-to-copy prompt (with the best-matching sample selected by a local LLM).

## Quick Start

### 1. Setup
```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium

# Copy and fill in your config
cp .env.example .env
# → Edit .env with your API keys and credentials
```

### 2. Add Your Resumes
Drop your resume PDFs into `src/resumes/`. Name them by category:
```
src/resumes/
  finance.pdf
  consulting.pdf
  tech.pdf
  general.pdf
  # Add any new category — it's automatic!
```

### 3. Set Up Your Profile
Edit `src/config/profile.yaml` with your personal information (name, email, education, etc.). This is what the agent uses to fill out forms.

### 4. Upload Cover Letter Samples
Drop your existing cover letter PDFs into `src/templates/`. When a job requires a cover letter, a local LLM (Qwen3 8B via Ollama) picks the most relevant sample and includes it in a prompt for you to modify using any AI.

**Ollama setup** (one-time):
```bash
# Install Ollama: https://ollama.com
ollama pull qwen3:8b
```

### 5. Run
```bash
# Run everything (pipeline + dashboard)
python -m src.main

# Dashboard only
python -m src.main --api-only

# Run pipeline once and exit
python -m src.main --run-once
```

Open the dashboard at **http://localhost:8000**

---

## Architecture

```
Scheduler (APScheduler)
       │
   ┌───▼────┐     ┌──────────┐     ┌──────────┐
   │Sourcer │────►│Analyzer  │────►│Executor  │
   │        │     │          │     │          │
   │Crawl4AI│     │Grok/     │     │browser-  │
   │browser-│     │Gemini    │     │use +     │
   │use     │     │Structured│     │Playwright│
   └────────┘     └────┬─────┘     └──────────┘
                       │
                  ┌────▼────────┐
                  │CL Required? │
                  │Qwen3 8B     │──► Pending Uploads
                  │(local)      │    (you upload CL)
                  └─────────────┘
```

## Key Config (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | — | Recommended for browser-use automation tasks |
| `XAI_API_KEY` | — | Enables Grok models for analyzer/cover-letter/critic tasks |
| `OPENAI_API_KEY` | — | Optional fallback provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama URL for local CL matching |
| `OLLAMA_MODEL` | `qwen3:8b` | Local model for cover letter sample selection |
| `AUTO_SUBMIT` | `true` | Auto-click submit vs. stop before submit |
| `MIN_RELEVANCE_SCORE` | `0.5` | Skip jobs below this score (0–1) |
| `SCRAPE_INTERVAL_MINUTES` | `60` | How often to run the pipeline |
| `HANDSHAKE_EMAIL/PASSWORD` | — | For authenticated Handshake sessions |

## Adding Resume Categories

Just drop a new PDF in `src/resumes/`. E.g., `src/resumes/marketing.pdf` — the analyzer will automatically include `marketing` as an option.

## Cover Letter Workflow

When the analyzer detects a job requires a cover letter, it:
1. Runs **Qwen3 8B** (locally via Ollama) to pick the best-matching sample from your uploaded PDFs
2. Generates a ready-to-copy prompt with the job description and selected sample
3. Sends you a desktop notification + audio alert
4. The job appears in **Pending Uploads** in the dashboard — copy the prompt, generate the CL externally, upload it to the application, and mark as done

## Tech Stack

| Component | Technology |
|---|---|
| Orchestration | LangGraph (stateful agent graph) |
| Browser AI | browser-use + Playwright |
| Scraping | Crawl4AI |
| LLM | Hybrid routing (Grok + Gemini + optional OpenAI) |
| Local LLM | Qwen3 8B via Ollama (cover letter matching) |
| Backend | FastAPI |
| Dashboard | React 19 + Vite |
| Database | SQLite + SQLAlchemy async |
| Scheduler | APScheduler |
