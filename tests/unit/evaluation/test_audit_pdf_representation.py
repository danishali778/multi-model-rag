from scripts.audit_pdf_representation import (
    _is_suspicious_heading_block,
    _is_front_matter_noise,
    _is_suspicious_heading,
    build_representation_audit,
    _table_coverage_stats,
)


def test_suspicious_heading_flags_reference_style_and_all_caps_noise():
    assert _is_suspicious_heading("[17] Blockchain") is True
    assert _is_suspicious_heading("SUMMARY OFLITERATUREREVIEW") is True
    assert _is_suspicious_heading("I. INTRODUCTION") is False
    assert _is_suspicious_heading("Table XVI") is False


def test_front_matter_noise_ignores_abstract_and_introduction_sections():
    noisy = {
        "block_type": "paragraph",
        "page_number": 1,
        "section_path": [],
        "text": "BSAI / BSDS Information Security",
        "metadata": {},
    }
    abstract = {
        "block_type": "paragraph",
        "page_number": 1,
        "section_path": ["Abstract"],
        "text": "The rapid growth of Internet of Things...",
        "metadata": {},
    }
    preserved_front_matter = {
        "block_type": "paragraph",
        "page_number": 1,
        "section_path": [],
        "text": "Danish Ali Department of Artificial Intelligence",
        "metadata": {"content_kind": "front_matter", "exclude_from_chunking": True},
    }

    assert _is_front_matter_noise(noisy) is True
    assert _is_front_matter_noise(abstract) is False
    assert _is_front_matter_noise(preserved_front_matter) is False


def test_table_coverage_stats_reports_captions_without_rows():
    blocks = [
        {
            "page_number": 4,
            "section_path": ["A. Identified Gaps"],
            "text": "Table II summarizes the major gaps",
            "metadata": {"content_kind": "table_caption", "table_id": "table-2", "caption_label": "Table II"},
        },
        {
            "page_number": 5,
            "section_path": ["Results"],
            "text": "TABLE XVI",
            "metadata": {"content_kind": "table_caption", "table_id": "table-16", "caption_label": "TABLE XVI"},
        },
        {
            "page_number": 5,
            "section_path": ["Results"],
            "text": "MAE 100.27 11.21",
            "metadata": {"content_kind": "table_row", "table_id": "table-16", "caption_label": "TABLE XVI"},
        },
    ]
    chunks = [
        {
            "metadata": {"content_kind": "table_row", "structure_group_id": "table-16"},
        }
    ]

    stats = _table_coverage_stats(blocks, chunks, preview=80)

    assert stats["caption_count"] == 2
    assert stats["captions_without_rows"] == 1
    assert stats["chunk_row_count"] == 1
    assert stats["coverage_ratio"] == 0.5


def test_suspicious_heading_block_allows_nested_lettered_subsections():
    valid_subsection = {
        "text": "A. Device Layer",
        "section_path": ["I. INTRODUCTION", "A. Device Layer"],
    }
    top_level_letter = {
        "text": "A. Device Layer",
        "section_path": ["A. Device Layer"],
    }

    assert _is_suspicious_heading_block(valid_subsection) is False
    assert _is_suspicious_heading_block(top_level_letter) is False


def test_build_representation_audit_reports_front_matter_and_title_heading_flags():
    document = {
        "id": "doc-1",
        "workspace_id": "ws-1",
        "title": "BDPP-IoT",
        "source_type": "pdf",
        "status": "succeeded",
        "metadata": {"parser_diagnostics": {"page_artifact_suppressed_count": 2, "decimal_subsection_heading_count": 3}},
        "created_at": None,
    }
    blocks = [
        {
            "block_type": "paragraph",
            "page_number": 1,
            "heading_level": None,
            "section_path": [],
            "text": "Danish Ali Department of Artificial Intelligence",
            "metadata": {"content_kind": "front_matter", "exclude_from_chunking": True},
        },
        {
            "block_type": "heading",
            "page_number": 1,
            "heading_level": 1,
            "section_path": ["Abstract"],
            "text": "Abstract",
            "metadata": {},
        },
    ]
    chunks = []

    audit = build_representation_audit(document, blocks, chunks, preview=80)

    assert audit["summary"]["front_matter_block_count"] == 1
    assert audit["summary"]["excluded_from_chunking_count"] == 1
    assert audit["summary"]["front_matter_leakage_count"] == 0
    assert audit["summary"]["abstract_heading_present"] is True
    assert audit["summary"]["abstract_non_abstract_noise_count"] == 0
    assert audit["summary"]["title_emitted_as_heading"] is False
    assert audit["summary"]["page_artifact_suppressed_count"] == 2
    assert audit["summary"]["decimal_subsection_heading_count"] == 3


def test_build_representation_audit_reports_front_matter_and_abstract_leakage():
    document = {
        "id": "doc-1",
        "workspace_id": "ws-1",
        "title": "BDPP-IoT",
        "source_type": "pdf",
        "status": "succeeded",
        "metadata": {},
        "created_at": None,
    }
    blocks = [
        {
            "block_type": "heading",
            "page_number": 1,
            "heading_level": 1,
            "section_path": ["Abstract"],
            "text": "Abstract",
            "metadata": {},
        },
        {
            "block_type": "paragraph",
            "page_number": 1,
            "heading_level": None,
            "section_path": ["Abstract"],
            "text": "Danish Ali Department of Artificial Intelligence",
            "metadata": {"content_kind": "paragraph"},
        },
    ]

    audit = build_representation_audit(document, blocks, [], preview=80)

    assert audit["summary"]["front_matter_leakage_count"] == 1
    assert audit["summary"]["abstract_non_abstract_noise_count"] == 1
