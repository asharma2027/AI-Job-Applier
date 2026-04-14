"""
Self-Refine critic — validates LLM outputs against active memory rules
before accepting them (based on Madaan et al. 2023 Self-Refine paper).

For this app:
- Run a fast task-routed critic pass after each agent output
- If a rule violation is detected → one automatic retry with the violation
  explained in the prompt
- If retry still fails → mark for manual review
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def critic_pass(
    agent: str,
    output: str,
    context: str,
    rules_block: str,
) -> tuple[bool, Optional[str]]:
    """
    Run a self-refine critic on an LLM output.

    Returns:
        (passed: bool, violation_description: str | None)
    """
    if not rules_block.strip():
        return True, None  # No rules to check against

    try:
        from src.config import settings

        llm = settings.get_llm_for_task("critic")

        prompt = f"""You are a strict quality critic for an AI pipeline.

Context of what the AI was asked to do:
{context}

Active rules the AI must follow:
{rules_block}

AI output to evaluate:
{output}

Task: Check if the AI output violates ANY of the rules above.
Respond with ONLY one of:
- "PASS" if no rules are violated
- "VIOLATION: <brief description of which rule was violated and how>"

Your response:"""

        result = await llm.ainvoke(prompt)
        response = result.content.strip()

        if response.upper().startswith("PASS"):
            return True, None
        elif response.upper().startswith("VIOLATION"):
            violation = response[len("VIOLATION:"):].strip()
            logger.warning(f"[self_refine] Rule violation in {agent}: {violation[:80]}")
            return False, violation
        else:
            # Ambiguous response — pass through to avoid blocking
            return True, None

    except Exception as e:
        logger.warning(f"[self_refine] Critic pass failed (skipping): {e}")
        return True, None  # Fail open — don't block on critic errors


async def refine_with_feedback(
    original_prompt: str,
    original_output: str,
    violation: str,
    llm_invoke_fn,
) -> str:
    """
    Retry the LLM call with the violation explained.
    Returns the refined output.
    """
    retry_prompt = f"""{original_prompt}

---
⚠️ SELF-CORRECTION REQUIRED:
Your previous response violated a rule: {violation}

Please redo your response, strictly correcting this issue. 
Previous response that was rejected:
{original_output}

Corrected response:"""

    try:
        result = await llm_invoke_fn(retry_prompt)
        return result.content.strip() if hasattr(result, "content") else str(result)
    except Exception as e:
        logger.error(f"[self_refine] Retry failed: {e}")
        return original_output  # Fall back to original
