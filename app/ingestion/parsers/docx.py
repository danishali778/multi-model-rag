from __future__ import annotations

from io import BytesIO
from typing import Any, Callable

from app.domain.entities.rag import ExtractedDocument
from app.domain.errors import BadRequestError
from app.ingestion.parsers.base import BaseParser
from app.ingestion.parsers.structured_markup import StructuredMarkupNormalizer

_HtmlConversionResult = str | tuple[str, list[str]]

try:
    import mammoth
except ModuleNotFoundError:  # pragma: no cover - exercised through injected converter in tests
    mammoth = None


class DocxParser(BaseParser):
    source_type = "docx"

    def __init__(
        self,
        *,
        html_converter: Callable[[bytes], _HtmlConversionResult] | None = None,
    ) -> None:
        self._html_converter = html_converter or _convert_docx_to_html

    def parse(self, raw_bytes: bytes, metadata: dict) -> ExtractedDocument:
        conversion = self._html_converter(raw_bytes)
        warnings: list[str] = []
        if isinstance(conversion, tuple):
            html, warnings = conversion
        else:
            html = conversion

        normalizer = StructuredMarkupNormalizer(self, parser_backend="mammoth")
        document = normalizer.parse_html(
            html=html,
            metadata=metadata,
            title_override=None,
            extra_warnings=warnings,
        )
        paragraph_count = len([block for block in document.blocks if block.block_type in {"paragraph", "list_item"}])
        document.metadata["paragraph_count"] = paragraph_count
        return document


def _convert_docx_to_html(raw_bytes: bytes) -> tuple[str, list[str]]:
    if mammoth is None:
        raise BadRequestError("DOCX parsing requires the 'mammoth' package to be installed.")
    result = mammoth.convert_to_html(BytesIO(raw_bytes))
    warnings = [str(message.message) for message in getattr(result, "messages", []) if getattr(message, "message", None)]
    return str(result.value), warnings
