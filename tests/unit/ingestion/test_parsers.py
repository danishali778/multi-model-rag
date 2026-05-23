from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile
import asyncio

from app.ingestion.audio.parser import AudioParser
from app.ingestion.parsers.docx import DocxParser
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import (
    DoclingNormalizedItem,
    DoclingParseResult,
    PdfParser,
    _DoclingAdapter,
)
from app.llm.providers.base import TranscriptionResult


def test_markdown_parser_extracts_text_and_title():
    parser = MarkdownParser()
    result = parser.parse(
        b"# Handbook\n\n## Eligibility\n\nTable 1 - Regional Attendance\n\n| Team | Days |\n| --- | --- |\n| Support | 3 |\n\n- Request approval\n\n```yaml\nmode: hybrid\n```",
        {"filename": "handbook.md"},
    )

    assert result.title == "Handbook"
    subsection = next(block for block in result.blocks if block.block_type == "heading" and block.text == "Eligibility")
    table_caption = next(block for block in result.blocks if block.block_type == "table_caption")
    table_row = next(block for block in result.blocks if block.block_type == "table_row")
    list_item = next(block for block in result.blocks if block.block_type == "list_item")
    code_block = next(block for block in result.blocks if block.metadata.get("content_kind") == "code_block")

    assert subsection.section_path == ["Handbook", "Eligibility"]
    assert table_caption.metadata["table_parse_status"] == "row_backed"
    assert table_row.metadata["table_id"] == table_caption.metadata["table_id"]
    assert "Team: Support" in table_row.text
    assert list_item.metadata["list_depth"] == 0
    assert code_block.metadata["code_language"] == "yaml"


def test_html_parser_extracts_title_and_text():
    parser = HtmlParser()
    result = parser.parse(
        (
            b"<html><head><title>Policies</title></head><body><h1>Remote Work</h1><h2>Eligibility</h2>"
            b"<p>Allowed.</p><p>Table 2 - Coverage</p><table><tr><th>Team</th><th>Days</th></tr><tr><td>Field</td><td>2</td></tr></table>"
            b"<figure><img src='chart.png'/><figcaption>Figure 1 Architecture Overview</figcaption></figure></body></html>"
        ),
        {"filename": "policies.html"},
    )

    assert result.title == "Policies"
    eligibility = next(block for block in result.blocks if block.block_type == "heading" and block.text == "Eligibility")
    table_caption = next(block for block in result.blocks if block.block_type == "table_caption")
    table_row = next(block for block in result.blocks if block.block_type == "table_row")
    figure = next(block for block in result.blocks if block.block_type == "figure_caption")

    assert eligibility.section_path == ["Remote Work", "Eligibility"]
    assert "Team: Field" in table_row.text
    assert table_row.metadata["table_id"] == table_caption.metadata["table_id"]
    assert figure.metadata["caption_label"].lower().startswith("figure")


def test_docx_parser_extracts_paragraphs():
    parser = DocxParser(
        html_converter=lambda _raw_bytes: (
            "<html><body><h1>Operations Manual</h1><h2>Runbook</h2><p>Restart the worker gracefully.</p>"
            "<p>Table 3 - Ownership</p><table><tr><th>Team</th><th>Owner</th></tr><tr><td>Platform</td><td>SRE</td></tr></table></body></html>"
        )
    )
    raw_bytes = _build_minimal_docx("Remote work is allowed.")
    result = parser.parse(raw_bytes, {"filename": "policy.docx"})

    assert result.title == "Operations Manual"
    runbook = next(block for block in result.blocks if block.block_type == "heading" and block.text == "Runbook")
    table_caption = next(block for block in result.blocks if block.block_type == "table_caption")
    table_row = next(block for block in result.blocks if block.block_type == "table_row")

    assert runbook.section_path == ["Operations Manual", "Runbook"]
    assert result.metadata["parser_backend"] == "mammoth"
    assert table_row.metadata["table_id"] == table_caption.metadata["table_id"]
    assert "Team: Platform" in table_row.text


def test_audio_parser_emits_timestamped_transcript_segments():
    async def _transcribe_audio(**kwargs):
        return TranscriptionResult(
            transcript="Welcome everyone. Deployment starts now.",
            model_name="gpt-4o-mini-transcribe",
            provider="openai",
            input_duration_ms=4600,
            language="en",
            segments=[
                {"text": "Welcome everyone.", "start": 0.0, "end": 1.8},
                {"text": "Deployment starts now.", "start": 1.9, "end": 4.6},
            ],
        )

    parser = AudioParser(model_router=SimpleNamespace(transcribe_audio=_transcribe_audio))
    result = asyncio.run(
        parser.parse_async(
            b"audio-bytes",
            {"filename": "briefing.wav", "_content_type": "audio/wav", "title": "Daily Briefing"},
        )
    )

    heading = next(block for block in result.blocks if block.block_type == "heading")
    segments = [block for block in result.blocks if block.metadata.get("content_kind") == "audio_transcript_segment"]

    assert result.title == "Daily Briefing"
    assert heading.text == "Audio Transcript"
    assert len(segments) == 2
    assert segments[0].metadata["start_ms"] == 0
    assert segments[0].metadata["end_ms"] == 1800
    assert result.metadata["transcription_provider"] == "openai"
    assert result.metadata["segment_count"] == 2


def test_audio_parser_warns_when_provider_returns_no_segments():
    async def _transcribe_audio(**kwargs):
        return TranscriptionResult(
            transcript="Single segment fallback.",
            model_name="gpt-4o-mini-transcribe",
            provider="openai",
            input_duration_ms=1200,
            segments=[],
        )

    parser = AudioParser(model_router=SimpleNamespace(transcribe_audio=_transcribe_audio))
    result = asyncio.run(
        parser.parse_async(
            b"audio-bytes",
            {"filename": "briefing.mp3", "_content_type": "audio/mpeg"},
        )
    )

    segments = [block for block in result.blocks if block.metadata.get("content_kind") == "audio_transcript_segment"]
    assert len(segments) == 1
    assert segments[0].metadata["start_ms"] == 0
    assert segments[0].metadata["end_ms"] == 1200
    assert any("single fallback transcript segment" in warning.lower() for warning in result.warnings)


def test_pdf_parser_maps_docling_parse_result_to_blocks_and_metadata():
    items = [
        DoclingNormalizedItem(kind="heading", text="Abstract", page_number=1, heading_level=1),
        DoclingNormalizedItem(
            kind="paragraph",
            text="This paper proposes a privacy-preserving framework.",
            page_number=1,
        ),
        DoclingNormalizedItem(kind="heading", text="I. INTRODUCTION", page_number=2, heading_level=1),
        DoclingNormalizedItem(kind="paragraph", text="IoT systems face data privacy risks.", page_number=2),
    ]
    parser = PdfParser(
        adapter=_FakeAdapter(
            DoclingParseResult(title="Technical Paper", page_count=2, items=items, warnings=["parser-note"])
        )
    )

    result = parser.parse(b"fake-pdf", {"filename": "paper.pdf"})

    assert result.detected_source_type == "pdf"
    assert result.metadata["page_count"] == 2
    assert result.metadata["parser_backend"] == "docling"
    assert result.title == "Technical Paper"
    assert result.warnings == ["parser-note"]

    headings = [block.text for block in result.blocks if block.block_type == "heading"]
    assert headings == ["Abstract", "I. INTRODUCTION"]

    intro_block = next(block for block in result.blocks if "IoT systems face" in block.text)
    assert intro_block.section_path == ["I. INTRODUCTION"]
    assert all(block.text != "Technical Paper" for block in result.blocks if block.block_type == "heading")


def test_pdf_parser_preserves_nested_section_paths_from_docling_items():
    items = [
        DoclingNormalizedItem(kind="heading", text="I. INTRODUCTION", page_number=1, heading_level=1),
        DoclingNormalizedItem(kind="heading", text="A. Device Layer", page_number=1, heading_level=2),
        DoclingNormalizedItem(kind="paragraph", text="Sensors collect raw telemetry.", page_number=1),
    ]
    parser = PdfParser(adapter=_FakeAdapter(DoclingParseResult(title=None, page_count=1, items=items)))

    result = parser.parse(b"fake-pdf", {"filename": "device-layer.pdf"})

    block = next(block for block in result.blocks if block.block_type == "paragraph")
    assert block.section_path == ["I. INTRODUCTION", "A. Device Layer"]
    assert result.title == "I. INTRODUCTION"


def test_pdf_parser_keeps_front_matter_outside_active_heading_sections():
    items = [
        DoclingNormalizedItem(kind="heading", text="Abstract", page_number=1, heading_level=1),
        DoclingNormalizedItem(
            kind="paragraph",
            text="Danish Ali Department of Artificial Intelligence",
            page_number=1,
            metadata={"content_kind": "front_matter", "exclude_from_chunking": True, "exclude_from_retrieval": True},
        ),
        DoclingNormalizedItem(kind="paragraph", text="This paper proposes a secure framework.", page_number=1),
    ]
    parser = PdfParser(adapter=_FakeAdapter(DoclingParseResult(title="Technical Paper", page_count=1, items=items)))

    result = parser.parse(b"fake-pdf", {"filename": "paper.pdf"})

    front_matter = next(block for block in result.blocks if "Danish Ali" in block.text)
    abstract_body = next(block for block in result.blocks if "secure framework" in block.text)

    assert front_matter.section_path == []
    assert front_matter.parent_block_id is None
    assert abstract_body.section_path == ["Abstract"]


def test_docling_adapter_normalizes_front_matter_tables_equations_algorithms_and_figures():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title=None,
        pages=[1],
        items=[
            _FakeItem(label="title", text="BDPP-IoT"),
            _FakeItem(label="author", text="Danish Ali", prov=[{"page_no": 1}]),
            _FakeItem(
                label="paragraph",
                text="Abstract - This paper proposes a privacy-preserving framework.",
                prov=[{"page_no": 1}],
            ),
            _FakeItem(label="paragraph", text="Index Terms - IoT, Blockchain", prov=[{"page_no": 1}]),
            _FakeItem(label="heading", text="I. INTRODUCTION", prov=[{"page_no": 1}]),
            _FakeItem(
                label="table",
                caption="TABLE I Comparison of Models",
                data=[
                    ["Metric", "Value"],
                    ["Accuracy", "98.4"],
                    ["MAE", "11.2"],
                ],
                prov=[{"page_no": 1}],
            ),
            _FakeItem(label="equation", text="F = m * a (12)", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="where F represents applied force.", prov=[{"page_no": 1}]),
            _FakeItem(label="algorithm", text="Algorithm 2 Secure Access Validation", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="Step 1 Validate token", prov=[{"page_no": 1}]),
            _FakeItem(label="figure", caption="Fig. 2 Architecture Overview", prov=[{"page_no": 1}]),
            _FakeItem(label="reference", text="[17] Blockchain access control", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)

    assert result.title == "BDPP-IoT"
    assert result.page_count == 1

    heading_items = [item.text for item in result.items if item.kind == "heading"]
    assert "Abstract" in heading_items
    assert "I. INTRODUCTION" in heading_items
    assert "Danish Ali" not in heading_items

    front_matter = next(item for item in result.items if item.text == "Danish Ali")
    assert front_matter.kind == "paragraph"
    assert front_matter.metadata["content_kind"] == "front_matter"
    assert front_matter.metadata["exclude_from_chunking"] is True
    assert front_matter.metadata["exclude_from_retrieval"] is True

    index_terms = next(item for item in result.items if item.text.startswith("Index Terms"))
    assert index_terms.metadata["content_kind"] == "front_matter"

    table_caption = next(item for item in result.items if item.kind == "table_caption")
    table_rows = [item for item in result.items if item.kind == "table_row"]
    equation = next(item for item in result.items if item.kind == "equation")
    equation_explanation = next(item for item in result.items if item.kind == "equation_explanation")
    algorithm_items = [item for item in result.items if item.kind == "algorithm"]
    figure = next(item for item in result.items if item.kind == "figure_caption")
    reference = next(item for item in result.items if item.text.startswith("[17]"))

    assert table_caption.metadata["caption_label"].lower().startswith("table")
    assert table_caption.metadata["table_parse_status"] == "row_backed"
    assert len(table_rows) == 2
    assert all(row.metadata["table_id"] == table_caption.metadata["table_id"] for row in table_rows)
    assert "Metric: Accuracy" in table_rows[0].text
    assert equation.metadata["equation_label"] == "12"
    assert equation_explanation.metadata["equation_id"] == equation.metadata["equation_id"]
    assert len(algorithm_items) == 2
    assert algorithm_items[1].metadata["algorithm_id"] == algorithm_items[0].metadata["algorithm_id"]
    assert figure.metadata["caption_label"].lower().startswith("fig.")
    assert reference.kind == "paragraph"


def test_docling_adapter_warns_when_table_has_caption_without_rows():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        pages=[1],
        items=[
            _FakeItem(label="table", caption="TABLE II Sparse Table", data=[], prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)

    assert any("had no recoverable table rows" in warning for warning in result.warnings)
    caption = next(item for item in result.items if item.kind == "table_caption")
    assert caption.metadata["table_parse_status"] == "caption_only"
    assert all(item.kind != "table_row" for item in result.items)


def test_docling_adapter_reconciles_row_only_tables_to_nearest_caption_group():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="BDPP-IoT",
        pages=[1],
        items=[
            _FakeItem(label="title", text="BDPP-IoT"),
            _FakeItem(label="heading", text="I. INTRODUCTION", prov=[{"page_no": 1}]),
            _FakeItem(label="table", caption="TABLE I Comparison of Models", data=[], prov=[{"page_no": 1}]),
            _FakeItem(
                label="table",
                data=[
                    ["Metric", "Value"],
                    ["Accuracy", "98.4"],
                    ["MAE", "11.2"],
                ],
                prov=[{"page_no": 1}],
            ),
        ],
    )

    result = adapter._normalize_document(fake_document)

    table_caption = next(item for item in result.items if item.kind == "table_caption")
    table_rows = [item for item in result.items if item.kind == "table_row"]

    assert table_caption.metadata["table_parse_status"] == "row_backed"
    assert len(table_rows) == 2
    assert all(row.metadata["table_id"] == table_caption.metadata["table_id"] for row in table_rows)
    assert all(row.metadata["caption_label"] == table_caption.metadata["caption_label"] for row in table_rows)


def test_docling_adapter_keeps_lettered_subsections_nested_once_body_has_started():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="BDPP-IoT",
        pages=[1],
        items=[
            _FakeItem(label="title", text="BDPP-IoT"),
            _FakeItem(label="heading", text="I. INTRODUCTION", prov=[{"page_no": 1}]),
            _FakeItem(label="heading", text="A. Device Layer", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="Sensors collect telemetry.", prov=[{"page_no": 1}]),
            _FakeItem(label="heading", text="REFERENCES", prov=[{"page_no": 2}]),
            _FakeItem(label="paragraph", text="[17] Blockchain access control", prov=[{"page_no": 2}]),
        ],
    )

    parser = PdfParser(adapter=_FakeAdapter(adapter._normalize_document(fake_document)))
    result = parser.parse(b"fake-pdf", {"filename": "paper.pdf"})

    device_layer = next(block for block in result.blocks if block.block_type == "heading" and block.text == "A. Device Layer")
    reference_entry = next(block for block in result.blocks if block.text.startswith("[17]"))

    assert device_layer.section_path == ["I. INTRODUCTION", "A. Device Layer"]
    assert reference_entry.block_type == "paragraph"


def test_docling_adapter_promotes_decimal_subsections_after_body_start():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="RAG Test Document",
        pages=[1],
        items=[
            _FakeItem(label="title", text="RAG Test Document"),
            _FakeItem(label="heading", text="1. Introduction to Supervised Learning", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="1.1 The Empirical Risk Minimisation Framework", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="1.1.1 Empirical Risk Bounds", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)
    promoted = [item for item in result.items if item.kind == "heading" and item.text.startswith("1.1")]

    assert [item.heading_level for item in promoted] == [2, 3]
    assert all(item.metadata["normalization_promoted_decimal_subsection"] is True for item in promoted)
    assert result.stats["decimal_subsection_heading_count"] == 2


def test_docling_adapter_suppresses_repeated_page_banner_lines():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="RAG Test Document: Foundations of Machine Learning",
        pages=[1, 2],
        items=[
            _FakeItem(label="title", text="RAG Test Document: Foundations of Machine Learning"),
            _FakeItem(label="heading", text="1. Introduction to Supervised Learning", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="Foundations of Machine Learning", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="A Technical Reference for RAG Pipeline Evaluation", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="Research Division · Version 2.4 · May 2026", prov=[{"page_no": 1}]),
            _FakeItem(label="paragraph", text="Supervised learning uses labeled examples.", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)

    assert all("Technical Reference" not in item.text for item in result.items)
    assert all("Research Division" not in item.text for item in result.items)
    assert result.stats["page_artifact_suppressed_count"] == 3


def test_docling_adapter_merges_adjacent_equation_fragments():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Math Notes",
        pages=[1],
        items=[
            _FakeItem(label="heading", text="1. Intro", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text="cos(q) = (u · v) / (||u|| ||v||", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text=") = Σ u_i v_i / (Σ u_i^2 · Σ v_i^2)", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)
    equations = [item for item in result.items if item.kind == "equation"]

    assert len(equations) == 1
    assert "Σ u_i v_i" in equations[0].text
    assert equations[0].metadata["merged_equation_fragments"] == 1
    assert result.stats["merged_equation_fragment_count"] == 1


def test_docling_adapter_attaches_closing_equation_tail_to_prior_incomplete_equation():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Math Notes",
        pages=[1],
        items=[
            _FakeItem(label="heading", text="1. Intro", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text="MSE = (1/N) Σ (y_i - ŷ_i", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text=") 2", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)
    equations = [item for item in result.items if item.kind == "equation"]

    assert len(equations) == 1
    assert equations[0].text.endswith(") 2")
    assert equations[0].metadata["merged_equation_fragments"] == 1
    assert result.stats["merged_equation_fragment_count"] == 1
    assert result.stats["equation_fragment_orphan_count"] == 0


def test_docling_adapter_does_not_attach_orphan_across_table_boundary():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Math Notes",
        pages=[1],
        items=[
            _FakeItem(label="heading", text="1. Intro", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text="MSE = (1/N) Σ (y_i - ŷ_i", prov=[{"page_no": 1}]),
            _FakeItem(label="table", caption="Table 1 - Example", data=[["Dataset", "Score"], ["MNIST", "99.7%"]], prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text=") 2", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)
    equations = [item for item in result.items if item.kind == "equation"]

    assert len(equations) == 2
    assert equations[0].text == "MSE = (1/N) Σ (y_i - ŷ_i"
    assert equations[1].text == ") 2"
    assert equations[1].metadata["equation_fragment_orphan"] is True
    assert result.stats["merged_equation_fragment_count"] == 0
    assert result.stats["equation_fragment_orphan_count"] == 1


def test_docling_adapter_does_not_skip_nearest_complete_equation_for_older_incomplete_one():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Math Notes",
        pages=[1],
        items=[
            _FakeItem(label="heading", text="1. Intro", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text="MSE = (1/N) Σ (y_i - ŷ_i", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text="L Ridge = MSE + λ ||w||²", prov=[{"page_no": 1}]),
            _FakeItem(label="equation", text=") 2", prov=[{"page_no": 1}]),
        ],
    )

    result = adapter._normalize_document(fake_document)
    equations = [item for item in result.items if item.kind == "equation"]

    assert len(equations) == 3
    assert equations[0].text == "MSE = (1/N) Σ (y_i - ŷ_i"
    assert equations[1].text == "L Ridge = MSE + λ ||w||²"
    assert equations[2].text == ") 2"
    assert equations[2].metadata["equation_fragment_orphan"] is True
    assert result.stats["merged_equation_fragment_count"] == 0
    assert result.stats["equation_fragment_orphan_count"] == 1


def test_docling_adapter_keeps_weak_inline_math_as_paragraph():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Notes",
        pages=[1],
        items=[
            _FakeItem(label="heading", text="1. Intro", prov=[{"page_no": 1}]),
            _FakeItem(
                label="paragraph",
                text="The loss term L(y_hat, y) is optimized during training.",
                prov=[{"page_no": 1}],
            ),
        ],
    )

    result = adapter._normalize_document(fake_document)

    assert all(item.kind != "equation" for item in result.items)


def test_docling_adapter_reuses_headers_for_multi_page_table_continuations():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Benchmarks",
        pages=[1, 2],
        items=[
            _FakeItem(
                label="table",
                caption="Table 1 - Common Supervised Learning Benchmark Datasets",
                data=[
                    ["Dataset", "Domain", "Samples"],
                    ["MNIST", "Vision", "70,000"],
                ],
                prov=[{"page_no": 1}],
            ),
            _FakeItem(
                label="table",
                data=[
                    ["Boston Housing", "Tabular", "506"],
                ],
                prov=[{"page_no": 2}],
            ),
        ],
    )

    result = adapter._normalize_document(fake_document)
    continuation_row = next(item for item in result.items if "Boston Housing" in item.text)

    assert continuation_row.text.startswith("Dataset: Boston Housing")
    assert continuation_row.metadata["reused_table_headers"] is True
    assert result.stats["multi_page_table_header_reuse_count"] == 1


def test_docling_adapter_reuses_known_headers_when_continuation_headers_are_positional():
    adapter = _DoclingAdapter()
    fake_document = _FakeDocument(
        title="Benchmarks",
        pages=[1, 2],
        items=[
            _FakeItem(
                label="table",
                caption="Table 1 - Common Supervised Learning Benchmark Datasets",
                data=[
                    ["Dataset", "Domain", "Samples"],
                    ["MNIST", "Vision", "70,000"],
                ],
                prov=[{"page_no": 1}],
            ),
            _FakeItem(
                label="table",
                data=[
                    {"0": "Boston Housing", "1": "Tabular", "2": "506"},
                ],
                prov=[{"page_no": 2}],
            ),
        ],
    )

    result = adapter._normalize_document(fake_document)
    continuation_row = next(item for item in result.items if "Boston Housing" in item.text)

    assert continuation_row.text == "Dataset: Boston Housing | Domain: Tabular | Samples: 506"
    assert continuation_row.metadata["reused_table_headers"] is True
    assert result.stats["multi_page_table_header_reuse_count"] == 1


class _FakeAdapter:
    def __init__(self, result: DoclingParseResult) -> None:
        self._result = result

    def convert_pdf(self, _raw_bytes: bytes) -> DoclingParseResult:
        return self._result


class _FakeDocument:
    def __init__(self, items, title=None, pages=None):
        self._items = items
        self.title = title
        self.pages = pages or []

    def iterate_items(self):
        return iter(self._items)


class _FakeItem(SimpleNamespace):
    pass


def _build_minimal_docx(text: str) -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
      <Default Extension="xml" ContentType="application/xml"/>
      <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    </Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
    </Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()
