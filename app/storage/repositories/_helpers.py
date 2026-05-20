from __future__ import annotations

from typing import Any


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def public_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if not key.startswith("_")}


def sensitivity_clause(alias: str) -> str:
    return f"""
        case {alias}.sensitivity
            when 'public' then 1
            when 'internal' then 2
            when 'confidential' then 3
            when 'restricted' then 4
            else 2
        end <=
        case %s
            when 'public' then 1
            when 'internal' then 2
            when 'confidential' then 3
            when 'restricted' then 4
            else 4
        end
    """
