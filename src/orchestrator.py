"""
LangGraph Orchestrator — Stateful pipeline graph for the full application workflow.

Nodes:
  source → analyze → execute → (loop)

Cover letter handling is no longer part of the automated pipeline —
when the analyzer detects a CL is needed, it creates a pending_cl_upload
record and notifies the user via the dashboard.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TypedDict, Annotated
from operator import add

from langgraph.graph import StateGraph, END

from src.agents.sourcer import run_sourcer
from src.agents.analyzer import run_analyzer
from src.agents.executor import run_executor

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Pipeline State
# ─────────────────────────────────────────────
class PipelineState(TypedDict):
    run_count: int
    new_jobs_found: int
    jobs_analyzed: int
    jobs_queued: int
    applications_submitted: int
    errors: Annotated[list[str], add]


# ─────────────────────────────────────────────
# Graph Nodes
# ─────────────────────────────────────────────
async def node_source(state: PipelineState) -> PipelineState:
    logger.info("=== [PIPELINE] Stage: SOURCE ===")
    try:
        new_jobs = await run_sourcer()
    except Exception as e:
        logger.error(f"[pipeline] sourcer failed: {e}")
        new_jobs = 0
        state["errors"].append(f"sourcer: {e}")
    return {**state, "new_jobs_found": new_jobs}


async def node_analyze(state: PipelineState) -> PipelineState:
    logger.info("=== [PIPELINE] Stage: ANALYZE ===")
    try:
        analyzed, queued = await run_analyzer()
    except Exception as e:
        logger.error(f"[pipeline] analyzer failed: {e}")
        analyzed, queued = 0, 0
        state["errors"].append(f"analyzer: {e}")
    return {**state, "jobs_analyzed": analyzed, "jobs_queued": queued}


async def node_execute(state: PipelineState) -> PipelineState:
    logger.info("=== [PIPELINE] Stage: EXECUTE ===")
    try:
        submitted = await run_executor()
    except Exception as e:
        logger.error(f"[pipeline] executor failed: {e}")
        submitted = 0
        state["errors"].append(f"executor: {e}")
    return {**state, "applications_submitted": submitted, "run_count": state["run_count"] + 1}


# ─────────────────────────────────────────────
# Build the graph
# ─────────────────────────────────────────────
def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("source", node_source)
    graph.add_node("analyze", node_analyze)
    graph.add_node("execute", node_execute)

    graph.set_entry_point("source")
    graph.add_edge("source", "analyze")
    graph.add_edge("analyze", "execute")
    graph.add_edge("execute", END)

    return graph.compile()


pipeline = build_pipeline()


async def run_pipeline_once() -> PipelineState:
    """Run one full pipeline cycle."""
    initial_state: PipelineState = {
        "run_count": 0,
        "new_jobs_found": 0,
        "jobs_analyzed": 0,
        "jobs_queued": 0,
        "applications_submitted": 0,
        "errors": [],
    }
    result = await pipeline.ainvoke(initial_state)
    logger.info(
        f"[pipeline] Run complete — "
        f"new={result['new_jobs_found']} analyzed={result['jobs_analyzed']} "
        f"submitted={result['applications_submitted']}"
    )
    return result
