from pathlib import Path

from app.storage.db.session import _workspace_bootstrap_applied_migrations


def test_workspace_bootstrap_keeps_0011_pending_when_evaluation_runs_missing():
    migration_files = [
        Path("0006_workspace_schema_cutover.sql"),
        Path("0010_audio_documents.sql"),
        Path("0011_workspace_evaluation_runs.sql"),
    ]

    applied = _workspace_bootstrap_applied_migrations(
        migration_files,
        has_evaluation_runs=False,
    )

    assert "0010_audio_documents.sql" in applied
    assert "0011_workspace_evaluation_runs.sql" not in applied


def test_workspace_bootstrap_marks_0011_applied_when_table_exists():
    migration_files = [
        Path("0006_workspace_schema_cutover.sql"),
        Path("0010_audio_documents.sql"),
        Path("0011_workspace_evaluation_runs.sql"),
    ]

    applied = _workspace_bootstrap_applied_migrations(
        migration_files,
        has_evaluation_runs=True,
    )

    assert "0011_workspace_evaluation_runs.sql" in applied
