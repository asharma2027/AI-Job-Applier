"""
Persistent Correction Memory — the "Engram for API-based pipelines" approach.

Stores typed correction rules per agent in a local memory.json file.
Rules are injected into every prompt as numbered few-shot constraints,
and a self-refine critic validates outputs against them before accepting.

Rule schema:
{
  "id": "uuid",
  "agent": "analyzer" | "cover_letter" | "executor",
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
) -> dict:
    """Add a new correction rule. Returns the created rule."""
    data = _load()
    rule = {
        "id": str(uuid.uuid4()),
        "agent": agent,
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
    Returns empty string if no rules exist.
    """
    rules = get_rules(agent)
    if not rules:
        return ""

    lines = ["\n## IMPORTANT: Learned Corrections (apply these strictly)\n"]
    for i, rule in enumerate(rules, 1):
        severity_tag = {"high": "🔴 CRITICAL", "medium": "🟡 IMPORTANT", "low": "🔵 NOTE"}.get(
            rule.get("severity", "medium"), "🟡 IMPORTANT"
        )
        lines.append(f"{i}. {severity_tag}: {rule['description']}")
        if rule.get("example_bad"):
            lines.append(f"   ❌ Do NOT do: {rule['example_bad']}")
        lines.append(f"   ✅ Instead: {rule['correction']}")
    return "\n".join(lines) + "\n"
