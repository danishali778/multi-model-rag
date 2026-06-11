from __future__ import annotations

import os
from pathlib import Path

from watchfiles import PythonFilter, run_process


WATCH_PATHS = [
    Path("/app/app"),
    Path("/app/scripts"),
]

CELERY_COMMAND = [
    "celery",
    "-A",
    "app.workers.tasks.celery_app",
    "worker",
    f"--loglevel={os.environ.get('CELERY_LOG_LEVEL', 'INFO')}",
    f"--concurrency={os.environ.get('CELERY_WORKER_CONCURRENCY', '2')}",
]


def run_worker() -> None:
    os.execvp(CELERY_COMMAND[0], CELERY_COMMAND)


def main() -> int:
    watch_paths = [path for path in WATCH_PATHS if path.exists()]
    if not watch_paths:
        raise RuntimeError("No worker dev watch paths were found inside the container.")

    run_process(
        *watch_paths,
        target=run_worker,
        watch_filter=PythonFilter(),
        debounce=1200,
        step=100,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
