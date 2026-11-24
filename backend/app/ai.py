"""Server-grounded assistant: model output is a plan, not renderable prose."""

import time

from fastapi import HTTPException
from pydantic import ValidationError

from . import provider
from .config import settings
from .preferences import deterministic_plan, relaxation, resolve
from .schemas import AssistantResult, Search
from .services import inventory
from .tools import execute_read, proposal

CLARIFY = {
    "budget": "What maximum price should I use?",
    "body": "Which single body type should I use?",
    "seats": "What minimum seat count is required?",
    "preference": "Please review your required constraints.",
    "action": "Choose a specific action and review its exact proposal.",
    "question": "Please specify vehicles, a policy question, or an action to review.",
}


async def run(db, cid, message, preferences, history, version, trace_id):
    started = time.perf_counter()
    trace = {
        "request_id": trace_id,
        "model": None,
        "model_calls": 0,
        "retry_count": 0,
        "usage": None,
        "cost_usd": None,
        "tools": [],
    }
    if settings.ai_mode == "deterministic":
        plan = deterministic_plan(message)
    else:
        # End any read transaction before network inference. No row locks span inference.
        db.rollback()
        plan, meta = await provider.plan(message, preferences, history)
        trace.update(meta)
    try:
        if plan.intent == "clarify" and plan.updates:
            raise ValueError("Ambiguous plans cannot change constraints")
        for edit in plan.updates:
            if (
                settings.ai_mode != "deterministic"
                and edit.op != "retain"
                and (not edit.evidence or edit.evidence not in message)
            ):
                raise ValueError("Update lacks current-message evidence")
        resolved = resolve(preferences, plan.updates).model_dump()
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            422, "Invalid or contradictory preference updates; no change saved"
        ) from exc
    proposals = []
    if settings.ai_mode != "deterministic" and relaxation(preferences, resolved):
        proposals.append(
            proposal(
                db,
                cid,
                "preferences",
                {
                    "expected_version": version + 1,
                    "operations": [op.model_dump() for op in plan.updates],
                },
            )
        )
        resolved = Search.model_validate(preferences).model_dump()
    # Only server-recognized exact greetings skip SQL lookup. Model intent cannot bypass lookup.
    pure_greeting = (
        message.lower().strip() in {"hi", "hello", "hey", "good morning", "thanks", "thank you"}
        and plan.intent == "greeting"
        and not plan.tools
        and not plan.updates
    )
    inventory_started = time.perf_counter()
    if plan.intent == "greeting" and not pure_greeting:
        plan.intent = "inventory"
    rows = [] if pure_greeting else inventory(db, Search.model_validate(resolved))
    if not pure_greeting:
        trace["tools"].append(
            {
                "name": "search_inventory",
                "duration_ms": round((time.perf_counter() - inventory_started) * 1000, 3),
                "source": "sql",
            }
        )
    if any(vid not in {r["id"] for r in rows} for vid in plan.vehicle_refs):
        trace["rejected_vehicle_refs"] = True  # Never expose arbitrary nominated IDs.
    citations = []
    tool_results = []
    comparison = []
    available_slots = []
    for call in plan.tools:
        t = time.perf_counter()
        try:
            result = execute_read(db, cid, call, resolved, message)
        except (ValidationError, KeyError) as exc:
            raise HTTPException(422, "Invalid tool arguments") from exc
        trace["tools"].append(
            {"name": call.name, "duration_ms": round((time.perf_counter() - t) * 1000, 3)}
        )
        if call.name == "compare_vehicles":
            comparison = result
        if call.name == "appointment_availability":
            available_slots.append({"vehicle_id": call.arguments["vehicle_id"], "slots": result})
        if call.name == "retrieve_policy":
            citations.extend(result)
        elif call.name.endswith("_proposal"):
            proposals.append(result)
        else:
            tool_results.append({"name": call.name, "result": result})
    if pure_greeting:
        reply = "Hello! I can help you explore vehicles, review synthetic policies, and prepare actions for confirmation."
    elif plan.intent == "clarify":
        reply = CLARIFY[plan.clarification or "question"]
    elif plan.intent == "policy":
        reply = (
            "These are excerpts from the synthetic policy corpus."
            if citations
            else "I do not have sufficient policy evidence to answer. Please ask staff."
        )
    elif plan.intent == "action":
        reply = (
            "Review the exact proposed action below. Nothing has been committed."
            if proposals
            else "No action has been performed. Choose an action to review."
        )
    else:
        reply = (
            "Available matches are listed below."
            if rows
            else "No vehicles meet all required constraints. No limits were relaxed."
        )
    if proposals and any(p["kind"] == "preferences" for p in proposals):
        reply += " A constraint change needs your explicit confirmation; current results keep your saved limits."
    trace["tool_results"] = tool_results
    trace["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    # All strings that make factual claims above are server-authored or database fields.
    return AssistantResult(
        comparison=comparison,
        availability=available_slots,
        reply=reply,
        mode=settings.ai_mode,
        intent=plan.intent,
        vehicles=rows if plan.intent not in {"policy", "clarify", "greeting", "action"} else [],
        citations=citations,
        proposals=proposals,
        preferences=resolved,
        version=version + 1,
        trace=trace,
    )
