from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from run_supabase_cli import resolve_supabase_command, supabase_environment
from runtime_env import (
    compose_local_supabase_overrides,
    host_local_supabase_overrides,
    parse_env_lines,
    read_env_file,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"compose", "host"}:
        print("usage: python scripts/generate_local_supabase_env.py <compose|host> <output-path>")
        return 2

    mode = sys.argv[1]
    output_path = Path(sys.argv[2]).resolve()
    template_name = ".env.compose.local-supabase.example" if mode == "compose" else ".env.host.local-supabase.example"
    template_path = ROOT / template_name

    result = subprocess.run(
        [*resolve_supabase_command(), "status", "-o", "env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=supabase_environment(),
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout)
        return result.returncode

    template_values = read_env_file(template_path)
    root_env_values = read_env_file(ROOT / ".env")
    supabase_values = parse_env_lines(result.stdout)
    overrides = (
        compose_local_supabase_overrides(supabase_values)
        if mode == "compose"
        else host_local_supabase_overrides(supabase_values)
    )

    merged = {**template_values, **root_env_values, **overrides}
    lines = [f"{key}={value}" for key, value in merged.items()]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
