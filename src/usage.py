"""
LLM Usage Tracking — monitors multi-provider API consumption against plan limits.

Persists daily stats to usage.json. Provides gauge data for the dashboard header
and detailed breakdowns for the Usage page.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_FILE = Path("./usage.json")

PLANS = {
    "free": {
        "label": "Google AI Free Tier",
        "daily_limits": {
            "gemini-2.5-flash": {"requests": 500},
            "gemini-2.5-pro": {"requests": 25},
        },
        "pricing": {},
    },
    "pay_as_you_go": {
        "label": "LLM Pay-as-you-go",
        "daily_limits": {},
        "pricing": {
            "gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
            "gemini-2.5-pro": {"input_per_1m": 1.25, "output_per_1m": 10.00},
            "grok-4.20-0309-reasoning": {"input_per_1m": 2.00, "output_per_1m": 6.00},
            "grok-4.20-0309-non-reasoning": {"input_per_1m": 2.00, "output_per_1m": 6.00},
            "grok-4.20-multi-agent-0309": {"input_per_1m": 2.00, "output_per_1m": 6.00},
            "grok-4-1-fast-reasoning": {"input_per_1m": 0.20, "output_per_1m": 0.50},
            "grok-4-1-fast-non-reasoning": {"input_per_1m": 0.20, "output_per_1m": 0.50},
        },
    },
}


def _load() -> dict:
    if USAGE_FILE.exists():
        try:
            return json.loads(USAGE_FILE.read_text())
        except Exception:
            pass
    return {"plan_type": "free", "custom_limits": {}, "monthly_budget_usd": 0, "daily": {}}


def _save(data: dict) -> None:
    USAGE_FILE.write_text(json.dumps(data, indent=2, default=str))


def _today() -> str:
    return date.today().isoformat()


def record_usage(model: str, input_tokens: int = 0, output_tokens: int = 0, error: bool = False):
    """Record a single LLM API call."""
    data = _load()
    today = _today()
    daily = data.setdefault("daily", {})
    day = daily.setdefault(today, {})
    entry = day.setdefault(model, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0})
    entry["requests"] += 1
    entry["input_tokens"] += input_tokens
    entry["output_tokens"] += output_tokens
    if error:
        entry["errors"] += 1
    _save(data)


def _compute_cost(stats: dict, pricing_entry: dict) -> float:
    cost = (stats.get("input_tokens", 0) / 1_000_000) * pricing_entry.get("input_per_1m", 0)
    cost += (stats.get("output_tokens", 0) / 1_000_000) * pricing_entry.get("output_per_1m", 0)
    return cost


def get_usage_summary() -> dict:
    """Full usage summary for the Usage page."""
    data = _load()
    plan_type = data.get("plan_type", "free")
    plan = PLANS.get(plan_type, PLANS["free"])
    today = _today()
    today_usage = data.get("daily", {}).get(today, {})
    current_month = today[:7]

    monthly_usage: dict[str, dict] = {}
    for day_key, day_data in data.get("daily", {}).items():
        if day_key.startswith(current_month):
            for model, stats in day_data.items():
                if model not in monthly_usage:
                    monthly_usage[model] = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0}
                for k in ("requests", "input_tokens", "output_tokens", "errors"):
                    monthly_usage[model][k] += stats.get(k, 0)

    monthly_cost = 0.0
    pricing = plan.get("pricing", {})
    for model, stats in monthly_usage.items():
        if model in pricing:
            monthly_cost += _compute_cost(stats, pricing[model])

    daily_limits = data.get("custom_limits") or plan.get("daily_limits", {})
    models_today: dict = {}
    for model_key in sorted(set(list(today_usage.keys()) + list(daily_limits.keys()))):
        usage = today_usage.get(model_key, {"requests": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0})
        limits = daily_limits.get(model_key, {})
        models_today[model_key] = {"usage": usage, "limits": limits}

    all_days = sorted(data.get("daily", {}).items())
    daily_history = {}
    for day_key, day_data in all_days[-30:]:
        total_req = sum(m.get("requests", 0) for m in day_data.values())
        total_in = sum(m.get("input_tokens", 0) for m in day_data.values())
        total_out = sum(m.get("output_tokens", 0) for m in day_data.values())
        daily_history[day_key] = {"requests": total_req, "input_tokens": total_in, "output_tokens": total_out}

    budget = data.get("monthly_budget_usd") or plan.get("monthly_budget_usd", 0)

    days_in_month = 30
    days_elapsed = int(today.split("-")[2])
    projected_cost = (monthly_cost / max(days_elapsed, 1)) * days_in_month if monthly_cost > 0 else 0

    return {
        "plan_type": plan_type,
        "plan_label": plan.get("label", plan_type),
        "today": today,
        "today_usage": models_today,
        "monthly_usage": monthly_usage,
        "monthly_cost_usd": round(monthly_cost, 4),
        "projected_monthly_cost_usd": round(projected_cost, 2),
        "monthly_budget_usd": budget,
        "daily_history": daily_history,
        "available_plans": {k: v["label"] for k, v in PLANS.items()},
    }


def get_gauge_data() -> dict:
    """Compact data for the always-visible usage gauge."""
    data = _load()
    plan_type = data.get("plan_type", "free")
    plan = PLANS.get(plan_type, PLANS["free"])
    today = _today()
    today_usage = data.get("daily", {}).get(today, {})
    daily_limits = data.get("custom_limits") or plan.get("daily_limits", {})

    total_requests = sum(m.get("requests", 0) for m in today_usage.values())
    total_limit = sum(l.get("requests", 0) for l in daily_limits.values())

    models = {}
    for model_key in sorted(set(list(today_usage.keys()) + list(daily_limits.keys()))):
        usage = today_usage.get(model_key, {})
        limits = daily_limits.get(model_key, {})
        req = usage.get("requests", 0)
        req_limit = limits.get("requests", 0)
        models[model_key] = {
            "requests": req,
            "limit": req_limit,
            "pct": round(req / req_limit * 100, 1) if req_limit > 0 else 0,
        }

    monthly_cost = 0.0
    if plan_type == "pay_as_you_go":
        current_month = today[:7]
        pricing = plan.get("pricing", {})
        for day_key, day_data in data.get("daily", {}).items():
            if day_key.startswith(current_month):
                for model, stats in day_data.items():
                    if model in pricing:
                        monthly_cost += _compute_cost(stats, pricing[model])

    budget = data.get("monthly_budget_usd") or 0

    return {
        "plan_type": plan_type,
        "total_requests_today": total_requests,
        "total_limit_today": total_limit,
        "pct_used": round(total_requests / total_limit * 100, 1) if total_limit > 0 else 0,
        "models": models,
        "monthly_cost_usd": round(monthly_cost, 4),
        "monthly_budget_usd": budget,
    }


def update_plan(plan_type: str = None, custom_limits: dict = None, monthly_budget_usd: float = None) -> dict:
    """Update plan configuration."""
    data = _load()
    if plan_type is not None:
        data["plan_type"] = plan_type
    if custom_limits is not None:
        data["custom_limits"] = custom_limits
    if monthly_budget_usd is not None:
        data["monthly_budget_usd"] = monthly_budget_usd
    _save(data)
    return get_usage_summary()
