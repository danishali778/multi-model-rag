from __future__ import annotations

from pathlib import Path
import sys
import tomllib


PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


def resolve_requirements(target: str) -> list[str]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = data["project"]
    optional_dependencies = project.get("optional-dependencies", {})

    if target == "core":
        return list(project["dependencies"])
    if target == "container-dev":
        return list(optional_dependencies.get("container-dev", []))
    if target == "ingestion":
        return list(optional_dependencies.get("ingestion", []))
    if target == "worker":
        return [*project["dependencies"], *optional_dependencies.get("ingestion", [])]
    raise ValueError(
        f"Unsupported target '{target}'. Expected one of: core, container-dev, ingestion, worker."
    )


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print(
            "usage: python scripts/export_container_requirements.py <core|container-dev|ingestion|worker>",
            file=sys.stderr,
        )
        return 1

    try:
        requirements = resolve_requirements(args[0])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    sys.stdout.write("\n".join(requirements))
    if requirements:
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
