from scripts.export_container_requirements import resolve_requirements


def test_core_requirements_exclude_worker_only_docling_dependency():
    requirements = resolve_requirements("core")

    assert "docling>=2.0.0" not in requirements
    assert "fastapi>=0.115.0" in requirements
    assert "celery[redis]>=5.4.0" in requirements


def test_ingestion_requirements_include_docling_only_group():
    requirements = resolve_requirements("ingestion")

    assert requirements == ["docling>=2.0.0"]


def test_worker_requirements_include_core_and_ingestion_dependencies():
    requirements = resolve_requirements("worker")

    assert "fastapi>=0.115.0" in requirements
    assert "docling>=2.0.0" in requirements
