from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.llm.prompts import build_messages, build_planning_messages, build_verification_messages


COMPLEX_QUERY_CLASSES = {"summary", "compare", "why", "conclusion"}


@dataclass(slots=True)
class GroundedAnswerResult:
    answer: str
    provider: str
    model_name: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    prompt_family: str
    planning: dict[str, Any] | None
    verification: dict[str, Any] | None
    verification_used: bool
    verification_outcome: str | None
    completion_count: int


async def answer_grounded_question(
    *,
    model_router: Any,
    question: str,
    source_blocks: list[str],
    profile: str,
    query_class: str,
    retrieval_metadata: dict[str, Any] | None = None,
) -> GroundedAnswerResult:
    retrieval_metadata = retrieval_metadata or {}
    planning: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    verification_outcome: str | None = None
    prompt_family = "precision"
    completions: list[Any] = []

    if query_class in COMPLEX_QUERY_CLASSES and source_blocks:
        plan_completion = await model_router.complete_chat(
            build_planning_messages(question, source_blocks, query_class=query_class),
            profile,
        )
        completions.append(plan_completion)
        planning = _parse_planning_response(
            plan_completion.answer,
            source_blocks=source_blocks,
            query_class=query_class,
        )
        prompt_family = "synthesis"

    answer_completion = await model_router.complete_chat(
        build_messages(question, source_blocks, prompt_family=prompt_family, plan=planning),
        profile,
    )
    completions.append(answer_completion)
    final_answer = answer_completion.answer

    should_verify = bool(
        source_blocks and (
            query_class in COMPLEX_QUERY_CLASSES
            or retrieval_metadata.get("candidate_counts", {}).get("selected", 0) <= 1
        )
    )
    if should_verify:
        verify_completion = await model_router.complete_chat(
            build_verification_messages(
                question,
                final_answer,
                source_blocks,
                query_class=query_class,
            ),
            profile,
        )
        completions.append(verify_completion)
        verification = _parse_verification_response(verify_completion.answer)
        if verification.get("supported") is False and verification.get("revised_answer"):
            final_answer = str(verification["revised_answer"]).strip()
            verification_outcome = "revised"
        elif verification.get("supported") is False:
            verification_outcome = "unsupported"
        else:
            verification_outcome = "passed"

    final_completion = completions[-1] if verification_outcome == "revised" and len(completions) > 1 else answer_completion
    total_input_tokens = sum(max(0, int(getattr(item, "input_tokens", 0) or 0)) for item in completions)
    total_output_tokens = sum(max(0, int(getattr(item, "output_tokens", 0) or 0)) for item in completions)
    total_cost = sum(float(getattr(item, "estimated_cost_usd", 0.0) or 0.0) for item in completions)

    return GroundedAnswerResult(
        answer=final_answer,
        provider=getattr(final_completion, "provider", answer_completion.provider),
        model_name=getattr(final_completion, "model_name", answer_completion.model_name),
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        estimated_cost_usd=total_cost,
        prompt_family=prompt_family,
        planning=planning,
        verification=verification,
        verification_used=should_verify,
        verification_outcome=verification_outcome,
        completion_count=len(completions),
    )


def _parse_planning_response(answer: str, *, source_blocks: list[str], query_class: str) -> dict[str, Any]:
    payload = _extract_json_payload(answer)
    if isinstance(payload, dict):
        return {
            "question_type": payload.get("question_type", query_class),
            "primary_source_ids": _normalize_int_list(payload.get("primary_source_ids")),
            "supporting_source_ids": _normalize_int_list(payload.get("supporting_source_ids")),
            "supported_claims": _normalize_str_list(payload.get("supported_claims")),
            "uncertainty": _normalize_str_list(payload.get("uncertainty")),
            "answer_focus": str(payload.get("answer_focus", "") or ""),
        }
    default_supporting = [index for index in range(2, min(len(source_blocks), 3) + 1)]
    return {
        "question_type": query_class,
        "primary_source_ids": [1] if source_blocks else [],
        "supporting_source_ids": default_supporting,
        "supported_claims": [],
        "uncertainty": [],
        "answer_focus": "",
    }


def _parse_verification_response(answer: str) -> dict[str, Any]:
    payload = _extract_json_payload(answer)
    if isinstance(payload, dict):
        return {
            "supported": bool(payload.get("supported", True)),
            "issues": _normalize_str_list(payload.get("issues")),
            "revised_answer": str(payload.get("revised_answer", "") or "").strip(),
        }
    return {"supported": True, "issues": [], "revised_answer": ""}


def _extract_json_payload(answer: str) -> Any:
    text = answer.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _normalize_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    normalized: list[int] = []
    for item in value:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
