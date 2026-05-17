from __future__ import annotations

import json
from pathlib import Path

from app.domain.entities.rag import EvaluationDatasetItem


class GoldenDatasetRepository:
    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> list[EvaluationDatasetItem]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [EvaluationDatasetItem(**item) for item in raw]
