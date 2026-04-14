"""
Persistent Correction Memory — the "Engram for API-based pipelines" approach.

Stores typed correction rules per agent in a local memory.json file.
Rules are injected into every prompt as numbered few-shot constraints,
and a self-refine critic validates outputs against them before accepting.

Rule schema:
{
  "id": "uuid",
  "agent": "analyzer" | "cover_letter" | "executor",
  "category": "string",
  "description": "What went wrong / what to always do",
  "example_bad": "Optional example of the mistake",
  "correction": "What the correct behavior should be",
  "severity": "low" | "medium" | "high",
  "enabled": true,
  "created_at": "iso8601",
  "times_triggered": 0
}
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

AgentType = Literal["analyzer", "cover_letter", "executor", "sourcer"]

MEMORY_FILE = Path("./memory.json")

_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if MEMORY_FILE.exists():
        try:
            _cache = json.loads(MEMORY_FILE.read_text())
            return _cache
        except Exception:
            pass
    _cache = {"analyzer": [], "cover_letter": [], "executor": [], "sourcer": []}
    return _cache


def _save(data: dict) -> None:
    global _cache
    _cache = data
    MEMORY_FILE.write_text(json.dumps(data, indent=2, default=str))


def get_rules(agent: AgentType) -> list[dict]:
    """Return enabled rules for a given agent."""
    data = _load()
    return [r for r in data.get(agent, []) if r.get("enabled", True)]


def get_all_rules() -> dict:
    """Return all rules for all agents."""
    return _load()


def add_rule(
    agent: AgentType,
    description: str,
    correction: str,
    example_bad: str = "",
    severity: Literal["low", "medium", "high"] = "medium",
    category: str = "General",
) -> dict:
    """Add a new correction rule. Returns the created rule."""
    data = _load()
    rule = {
        "id": str(uuid.uuid4()),
        "agent": agent,
        "category": category,
        "description": description,
        "example_bad": example_bad,
        "correction": correction,
        "severity": severity,
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(),
        "times_triggered": 0,
    }
    data.setdefault(agent, []).append(rule)
    _save(data)
    logger.info(f"[memory] New rule added for '{agent}': {description[:60]}")

    return rule


def update_rule(rule_id: str, **kwargs) -> Optional[dict]:
    """Update fields on an existing rule by ID."""
    data = _load()
    for agent_rules in data.values():
        for rule in agent_rules:
            if rule.get("id") == rule_id:
                rule.update({k: v for k, v in kwargs.items() if k != "id"})
                _save(data)
                return rule
    return None


def delete_rule(rule_id: str) -> bool:
    """Delete a rule by ID. Returns True if found and deleted."""
    data = _load()
    for agent, agent_rules in data.items():
        for i, rule in enumerate(agent_rules):
            if rule.get("id") == rule_id:
                data[agent].pop(i)
                _save(data)
                logger.info(f"[memory] Rule {rule_id} deleted")
                return True
    return False


def increment_triggered(rule_id: str) -> None:
    """Increment the times_triggered counter for a rule."""
    data = _load()
    for agent_rules in data.values():
        for rule in agent_rules:
            if rule.get("id") == rule_id:
                rule["times_triggered"] = rule.get("times_triggered", 0) + 1
                _save(data)
                return


def build_rules_block(agent: AgentType) -> str:
    """
    Build a formatted block of active rules to inject into a prompt.
    Uses token-dense XML formatting to minimize context overhead.
    Returns empty string if no rules exist.
    """
    rules = get_rules(agent)
    if not rules:
        return ""

    from collections import defaultdict
    categories = defaultdict(list)
    for r in rules:
        categories[r.get("category", "General")].append(r)

    lines = ["<rules>"]
    for cat, cat_rules in categories.items():
        lines.append(f"  <{cat}>")
        for r in cat_rules:
            sev = {"high": "CRIT", "medium": "IMPT", "low": "NOTE"}.get(r.get("severity", "medium"), "IMPT")
            b_bad = f" NOT:{r['example_bad']}" if r.get("example_bad") else ""
            lines.append(f"    [{sev}] {r['description']} -> {r['correction']}{b_bad}")
        lines.append(f"  </{cat}>")
    lines.append("</rules>\n")
    return "\n".join(lines)


async def condense_rules(agent: AgentType) -> None:
    """
    Compresses and deduplicates the active rules for an agent using an LLM.
    Reduces memory bloat and context overhead while preserving semantic rules.
    """
    data = _load()
    rules = [r for r in data.get(agent, []) if r.get("enabled", True)]
    if len(rules) < 6:
        return

    try:
        from src.config import settings

        llm = settings.get_llm_fast()

        prompt = f"""You are a Memory Optimizer. Semantically compress this list of rules down to a highly distilled set without losing ANY critical constraints.
Rules to condense:
{json.dumps(rules, indent=2)}

Task:
1. Merge duplicate or similar concepts into single rules.
2. Keep text extremely concise and token-dense.
3. Return ONLY a valid JSON array of objects with keys: "category" (string), "description" (string), "correction" (string), "severity" ("low", "medium", "high").
No markdown tags around the JSON.
"""
        result = await llm.ainvoke(prompt)
        content = result.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()

        optimized = json.loads(content)
        
        new_rules = []
        for opt in optimized:
            new_rules.append({
                "id": str(uuid.uuid4()),
                "agent": agent,
                "category": opt.get("category", "General"),
                "description": opt.get("description", ""),
                "example_bad": "",
                "correction": opt.get("correction", ""),
                "severity": opt.get("severity", "medium"),
                "enabled": True,
                "created_at": datetime.utcnow().isoformat(),
                "times_triggered": 0,
            })

        # Double check reload to prevent overwriting new rules added during LLM call
        current_data = _load()
        current_data[agent] = new_rules
        _save(current_data)
        logger.info(f"[memory] Distilled {len(rules)} rules down to {len(new_rules)} for '{agent}'.")

    except Exception as e:
        logger.error(f"[memory] Rule condensation failed: {e}")

