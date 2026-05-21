from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from types import SimpleNamespace

from pypdf import PdfWriter

import app.ingestion.parsers.pdf as pdf_module
from app.ingestion.parsers.docx import DocxParser
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import PdfParser


def test_markdown_parser_extracts_text_and_title():
    parser = MarkdownParser()
    result = parser.parse(b"# Handbook\n\nRemote work is allowed.", {"filename": "handbook.md"})

    assert result.title == "Handbook"
    assert "Remote work is allowed." in result.text


def test_html_parser_extracts_title_and_text():
    parser = HtmlParser()
    result = parser.parse(
        b"<html><head><title>Policies</title></head><body><h1>Remote Work</h1><p>Allowed.</p></body></html>",
        {"filename": "policies.html"},
    )

    assert result.title == "Policies"
    assert "Remote Work" in result.text
    assert "Allowed." in result.text


def test_docx_parser_extracts_paragraphs():
    parser = DocxParser()
    raw_bytes = _build_minimal_docx("Remote work is allowed.")
    result = parser.parse(raw_bytes, {"filename": "policy.docx"})

    assert result.title.startswith("Remote work")
    assert "Remote work is allowed." in result.text


def test_pdf_parser_extracts_metadata_from_blank_pdf():
    parser = PdfParser()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)

    result = parser.parse(buffer.getvalue(), {"filename": "policy.pdf"})

    assert result.detected_source_type == "pdf"
    assert result.metadata["page_count"] == 1


def test_pdf_parser_preserves_later_page_section_structure_for_fixture():
    parser = PdfParser()
    fixture = Path("tests/fixtures/documents/complex_eval_report.pdf")

    result = parser.parse(fixture.read_bytes(), {"filename": fixture.name})

    headings = [block.text for block in result.blocks if block.block_type == "heading"]
    assert "3. Customer Support and Satisfaction" in headings
    assert "4. Workforce Readiness and Training" in headings
    assert "6. Risk, Compliance, and Governance" in headings

    customer_block = next(
        block for block in result.blocks if block.block_type == "paragraph" and "6,842 inbound requests" in block.text
    )
    training_block = next(
        block for block in result.blocks if block.block_type == "paragraph" and "Mandatory training completion reached 97 percent" in block.text
    )

    assert customer_block.section_path == ["3. Customer Support and Satisfaction"]
    assert training_block.section_path == ["4. Workforce Readiness and Training"]


def test_pdf_parser_detects_abstract_table_equation_algorithm_and_figure(monkeypatch):
    class FakeReader:
        def __init__(self, *_args, **_kwargs):
            self.metadata = SimpleNamespace(title="Technical Paper")
            self.pages = [
                SimpleNamespace(
                    extract_text=lambda: "\n".join(
                        [
                            "BDPP-IoT",
                            "Danish Ali",
                            "Pakistan",
                            "Abstract—This paper proposes a privacy-preserving framework.",
                            "I. INTRODUCTION",
                            "TABLE I Comparison of Models",
                            "Metric Value Accuracy 98.4",
                            "F = m * a (12)",
                            "where F represents applied force.",
                            "Algorithm 2 Secure Access Validation",
                            "Step 1 Validate token",
                            "Fig. 2 Architecture Overview",
                        ]
                    )
                )
            ]

    monkeypatch.setattr(pdf_module, "PdfReader", FakeReader)

    parser = PdfParser()
    result = parser.parse(b"fake-pdf", {"filename": "paper.pdf"})

    heading_texts = [block.text for block in result.blocks if block.block_type == "heading"]
    assert "Danish Ali" not in heading_texts
    assert "Pakistan" not in heading_texts
    assert "Abstract" in heading_texts
    assert "I. INTRODUCTION" in heading_texts

    block_types = [block.block_type for block in result.blocks]
    assert "table_caption" in block_types
    assert "table_row" in block_types
    assert "equation" in block_types
    assert "equation_explanation" in block_types
    assert "algorithm" in block_types
    assert "figure_caption" in block_types

    table_caption = next(block for block in result.blocks if block.block_type == "table_caption")
    table_row = next(block for block in result.blocks if block.block_type == "table_row")
    equation = next(block for block in result.blocks if block.block_type == "equation")
    figure = next(block for block in result.blocks if block.block_type == "figure_caption")

    assert table_caption.metadata["content_kind"] == "table_caption"
    assert table_row.metadata["table_id"] == table_caption.metadata["table_id"]
    assert equation.metadata["equation_label"] == "12"
    assert figure.metadata["caption_label"].lower().startswith("fig.")


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
