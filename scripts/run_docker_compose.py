from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve_compose_command() -> list[str]:
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run(
            [docker, "compose", "version"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return [docker, "compose"]

    docker_compose = shutil.which("docker-compose") or shutil.which("docker-compose.exe")
    if docker_compose:
        return [docker_compose]

    raise RuntimeError("Docker Compose was not found. Install `docker compose` or `docker-compose`.")


def main() -> int:
    command = [*resolve_compose_command(), *sys.argv[1:]]
    result = subprocess.run(command, cwd=ROOT, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
