from __future__ import annotations

import sys
from pathlib import Path

from runtime_env import (
    parse_env_lines,
    validate_local_supabase_compose_env,
    validate_local_supabase_host_env,
    validate_remote_compose_env,
)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python scripts/validate_runtime_env.py <env-path> <remote-compose|local-supabase-compose|local-supabase-host>")
        return 2

    env_path = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    if not env_path.exists():
        print(f"env file not found: {env_path}")
        return 1

    values = parse_env_lines(env_path.read_text(encoding="utf-8"))
    if mode == "remote-compose":
        errors = validate_remote_compose_env(values)
    elif mode == "local-supabase-compose":
        errors = validate_local_supabase_compose_env(values)
    elif mode == "local-supabase-host":
        errors = validate_local_supabase_host_env(values)
    else:
        print(f"unsupported validation mode: {mode}")
        return 2

    if errors:
        for error in errors:
            print(error)
        return 1

    print({"env_path": str(env_path), "mode": mode, "status": "ok"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
