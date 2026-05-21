from __future__ import annotations


def assert_error_code(body: dict, code: str) -> None:
    assert body["error"]["code"] == code


def assert_has_citation(answer: str, source_index: int = 1) -> None:
    assert f"[source:{source_index}]" in answer
