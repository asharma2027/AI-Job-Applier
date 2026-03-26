"""
Cover Letter Agent — prompt assembly mode (zero token spend).

Instead of calling an LLM to generate the cover letter, this agent:
1. Reads the template with <<<SECTION>>> markers
2. Analyzes the job description
3. Assembles a rich, complete prompt with all context
4. Stores it so the user can copy → paste into Gemini/Claude → paste result back

The "paste back" path parses the response and applies sections to the template.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from src.memory.memory_store import build_rules_block, get_rules
from src.config import settings

logger = logging.getLogger(__name__)

# ── Section parsing ─────────────────────────────────────────────────────────

SECTION_PATTERN = re.compile(
    r"<<<SECTION:\s*(?P<name>[^>]+)>>>\s*(?P<content>.*?)\s*<<<END_SECTION>>>",
    re.DOTALL | re.IGNORECASE,
)


def parse_sections(template: str) -> dict[str, str]:
    """Extract all <<SECTION>> boundaries from a template."""
    return {
        m.group("name").strip(): m.group("content").strip()
        for m in SECTION_PATTERN.finditer(template)
    }


def apply_generated_sections(template: str, generated: dict[str, str]) -> str:
    """
    Replace <<<SECTION>>> blocks in template with generated content.
    Removes the markers — output is clean prose.
    """
    def replacer(m: re.Match) -> str:
        name = m.group("name").strip()
        return generated.get(name, m.group("content").strip())

    result = SECTION_PATTERN.sub(replacer, template)
    return result.strip()


# ── Prompt assembly ──────────────────────────────────────────────────────────

def build_cover_letter_prompt(
    job_title: str,
    job_company: str,
    job_description: str,
    key_requirements: list[str],
    resume_type: str,
    template: str,
    user_profile: Optional[dict] = None,
) -> str:
    """
    Assemble a comprehensive prompt for the user to paste into any LLM.
    This contains all the context needed to generate a great cover letter.
    """
    sections = parse_sections(template)
    section_names = list(sections.keys())

    # Memory rules for cover_letter agent
    rules_block = build_rules_block("cover_letter")

    profile_block = ""
    if user_profile:
        profile_block = f"""
## My Background
- **Name:** {user_profile.get('name', '[Your Name]')}
- **Email:** {user_profile.get('email', '[Your Email]')}
- **Education:** {user_profile.get('education', {}).get('degree', '')} from {user_profile.get('education', {}).get('school', '')}
- **GPA:** {user_profile.get('education', {}).get('gpa', '')}
- **Resume Category:** {resume_type}
- **Relevant Experience:** {', '.join(user_profile.get('experience', [])[:3])}
- **Skills:** {', '.join(user_profile.get('skills', [])[:10])}
"""

    requirements_block = ""
    if key_requirements:
        requirements_block = "\n## Key Requirements Identified\n" + "\n".join(
            f"- {r}" for r in key_requirements[:8]
        )

    section_instructions = "\n".join([
        f"- **{name}**: Rewrite this section to align with the job. Keep it natural and specific."
        for name in section_names
    ])

    prompt = f"""# Cover Letter Generation Task

## Job Details
- **Position:** {job_title}
- **Company:** {job_company}

## Full Job Description
{job_description}
{requirements_block}
{profile_block}
{rules_block}

---

## Your Task

Below is my cover letter template. It has special markers like `<<<SECTION: name>>>` and `<<<END_SECTION>>>` around sections I want you to rewrite.

**YOU MUST:**
1. Rewrite ONLY the content between `<<<SECTION: name>>>` and `<<<END_SECTION>>>` markers
2. Keep the exact markers in your response so I can parse your output
3. Do NOT change any text outside the markers
4. Keep language natural, specific to this company, and non-generic
5. Each rewritten section should be 2-5 sentences

**Sections to rewrite:**
{section_instructions}

## Template (return this entire block with sections rewritten):

{template}

---
Return ONLY the complete template text above with the section contents replaced. Do not add any commentary before or after.
"""
    return prompt.strip()


# ── Paste-back parsing ───────────────────────────────────────────────────────

def apply_pasted_response(template: str, pasted_response: str) -> tuple[str, dict[str, str]]:
    """
    Parse the user's pasted LLM response and apply section replacements to the template.

    Returns:
        (merged_draft: str, changed_sections: dict)
    """
    # Try to extract sections from the pasted response
    generated = {
        m.group("name").strip(): m.group("content").strip()
        for m in SECTION_PATTERN.finditer(pasted_response)
    }

    if not generated:
        # If no markers found, treat the entire pasted text as the cover letter
        logger.warning("[cover_letter] No section markers found in pasted response — using as-is")
        return pasted_response.strip(), {}

    merged = apply_generated_sections(template, generated)
    return merged, generated


# ── Main entry point ─────────────────────────────────────────────────────────

async def prepare_cover_letter_prompt(job: dict, profile: Optional[dict] = None) -> str:
    """
    Called by the orchestrator. Builds and returns the cover-letter prompt.
    No LLM call is made here.
    """
    template_path = settings.cover_letter_template
    if template_path.exists():
        template = template_path.read_text()
    else:
        template = _default_template()

    return build_cover_letter_prompt(
        job_title=job.get("title", ""),
        job_company=job.get("company", ""),
        job_description=job.get("description", ""),
        key_requirements=job.get("key_requirements") or [],
        resume_type=job.get("resume_type", "general"),
        template=template,
        user_profile=profile,
    )


def _default_template() -> str:
    return """Dear Hiring Team,

<<<SECTION: opening>>>
I am writing to express my strong interest in this position.
<<<END_SECTION>>>

<<<SECTION: why_company>>>
I am particularly drawn to your company's mission and the work your team does.
<<<END_SECTION>>>

<<<SECTION: relevant_experience>>>
Through my academic and professional experiences, I have developed skills directly relevant to this role.
<<<END_SECTION>>>

<<<SECTION: closing>>>
I would welcome the opportunity to discuss how my background aligns with your needs. Thank you for your consideration.
<<<END_SECTION>>>

Sincerely,
[Your Name]
"""
