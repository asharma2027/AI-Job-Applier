# Job Applier Agent 🤖

An autonomous background agent that sources internship listings, analyzes them, routes the right resume, drafts cover letters for your review, and auto-fills & submits applications across any ATS.

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

### 4. Customize Your Cover Letter Template
Edit `src/templates/cover_letter_template.md`. Use `<<<SECTION: name>>>` / `<<<END_SECTION>>>` markers to define which sections the AI will rewrite for each job:

```
<<<SECTION: opening_paragraph>>>
I am writing to express my interest in [Job Title] at [Company]...
<<<END_SECTION>>>
```

Everything **outside** the markers stays exactly as-is. Add, remove, or rename sections freely.

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
   ┌───▼────┐     ┌──────────┐     ┌────────────┐     ┌──────────┐
   │Sourcer │────►│Analyzer  │────►│Cover Letter│────►│Executor  │
   │        │     │          │     │Agent       │     │          │
   │Crawl4AI│     │GPT-4o    │     │GPT-4o      │     │browser-  │
   │browser-│     │Structured│     │Section-    │     │use +     │
   │use     │     │Output    │     │aware       │     │Playwright│
   └────────┘     └──────────┘     └─────┬──────┘     └──────────┘
                                         │
                                    Review Queue
                                    (FastAPI + React)
                                    You approve/edit
```

## Key Config (`.env`)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Required. GPT-4o for all AI tasks |
| `AUTO_SUBMIT` | `true` | Auto-click submit vs. stop before submit |
| `MIN_RELEVANCE_SCORE` | `0.5` | Skip jobs below this score (0–1) |
| `SCRAPE_INTERVAL_MINUTES` | `60` | How often to run the pipeline |
| `HANDSHAKE_EMAIL/PASSWORD` | — | For authenticated Handshake sessions |

## Adding Resume Categories

Just drop a new PDF in `src/resumes/`. E.g., `src/resumes/marketing.pdf` — the analyzer will automatically include `marketing` as an option.

## Cover Letter Sections

Mark any text in your template with `<<<SECTION: name>>>` ... `<<<END_SECTION>>>`. The AI regenerates those sections per job; everything else is verbatim. Remove all markers and the template is used as-is with basic `{{company}}` substitution.

## Tech Stack

| Component | Technology |
|---|---|
| Orchestration | LangGraph (stateful agent graph) |
| Browser AI | browser-use + Playwright |
| Scraping | Crawl4AI |
| LLM | OpenAI GPT-4o |
| Backend | FastAPI |
| Dashboard | React 19 + Vite |
| Database | SQLite + SQLAlchemy async |
| Scheduler | APScheduler |
