from __future__ import annotations

import json
from typing import Any


def build_messages(
    question: str,
    source_blocks: list[str],
    *,
    prompt_family: str = "precision",
    plan: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    context = "\n\n".join(source_blocks)
    plan_block = ""
    if plan:
        plan_block = f"\n\nReasoning Plan:\n{json.dumps(plan, ensure_ascii=True)}"

    if prompt_family == "synthesis":
        system = (
            "You are a grounded enterprise RAG assistant. "
            "Synthesize only from the provided context. "
            "Prefer the document's own framing over generic interpretation. "
            "If evidence is partial, separate confirmed facts from uncertainty. "
            "Cite factual claims using the provided source identifiers."
        )
        user = (
            f"Question:\n{question}\n\n"
            f"Context:\n{context}{plan_block}\n\n"
            "Write a concise but complete grounded answer. "
            "For summary, why, compare, and conclusion questions, stay at the same abstraction level as the question. "
            "Use inline citations like [source:1]."
        )
    else:
        system = (
            "You are a grounded enterprise RAG assistant. "
            "Answer using only the provided context. "
            "If the answer is directly supported, answer plainly and do not hedge unnecessarily. "
            "If the context is insufficient, say so clearly. "
            "Cite factual claims using the provided source identifiers."
        )
        user = (
            f"Question:\n{question}\n\n"
            f"Context:\n{context}{plan_block}\n\n"
            "Return a concise direct answer with inline citations like [source:1]."
        )

    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_planning_messages(question: str, source_blocks: list[str], *, query_class: str) -> list[dict[str, str]]:
    context = "\n\n".join(source_blocks)
    system = (
        "You are a grounded reasoning planner for a RAG assistant. "
        "Read the question and provided sources, then return strict JSON only. "
        "Do not answer the question directly."
    )
    user = (
        f"Question:\n{question}\n\n"
        f"Query Class: {query_class}\n\n"
        f"Context:\n{context}\n\n"
        "Return JSON with keys: "
        "question_type, primary_source_ids, supporting_source_ids, supported_claims, uncertainty, answer_focus."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_verification_messages(
    question: str,
    draft_answer: str,
    source_blocks: list[str],
    *,
    query_class: str,
) -> list[dict[str, str]]:
    context = "\n\n".join(source_blocks)
    system = (
        "You are a grounded answer verifier. "
        "Check whether the draft answer is fully supported by the provided context. "
        "Return strict JSON only."
    )
    user = (
        f"Question:\n{question}\n\n"
        f"Query Class: {query_class}\n\n"
        f"Draft Answer:\n{draft_answer}\n\n"
        f"Context:\n{context}\n\n"
        "Return JSON with keys: supported, issues, revised_answer."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
