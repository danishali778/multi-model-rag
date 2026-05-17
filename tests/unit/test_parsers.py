from io import BytesIO
from zipfile import ZipFile

from pypdf import PdfWriter

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
    assert "Remote Work Allowed." in result.text


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
