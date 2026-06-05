from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NPM_CACHE = ROOT / ".tmp" / "npm-cache"
SUPABASE_HOME = ROOT / ".tmp" / "supabase-home"


def cached_supabase_binary() -> str | None:
    local_app_data = Path.home() / "AppData" / "Local" / "npm-cache" / "_npx"
    if not local_app_data.exists():
        return None

    matches = sorted(local_app_data.glob("*/node_modules/@supabase/cli-*/bin/supabase.exe"))
    if matches:
        return str(matches[-1])
    return None


def resolve_supabase_command() -> list[str]:
    if shutil.which("supabase"):
        return ["supabase"]
    cached_binary = cached_supabase_binary()
    if cached_binary:
        return [cached_binary]
    if shutil.which("npx.cmd"):
        return ["npx.cmd", "--yes", "--cache", str(NPM_CACHE), "supabase@latest"]
    if shutil.which("npx"):
        return ["npx", "--yes", "--cache", str(NPM_CACHE), "supabase@latest"]
    raise RuntimeError("Supabase CLI was not found. Install `supabase` or make `npx` available.")


def supabase_environment() -> dict[str, str]:
    env = dict(os.environ)
    home = str(SUPABASE_HOME)
    env["HOME"] = home
    env["USERPROFILE"] = home
    env["SUPABASE_DISABLE_TELEMETRY"] = "1"
    return env


def main() -> int:
    command = [*resolve_supabase_command(), *sys.argv[1:]]
    NPM_CACHE.mkdir(parents=True, exist_ok=True)
    SUPABASE_HOME.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, cwd=ROOT, check=False, env=supabase_environment())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
