from __future__ import annotations

import sys

from generate_local_supabase_env import main


if __name__ == "__main__":
    print(
        "scripts/generate_local_env.py is deprecated; use scripts/generate_local_supabase_env.py instead.",
        file=sys.stderr,
    )
    raise SystemExit(main())
