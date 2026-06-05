#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "scripts/bootstrap_local_stack.sh is deprecated; use scripts/bootstrap_local_supabase_stack.sh instead." >&2
exec sh "$ROOT_DIR/scripts/bootstrap_local_supabase_stack.sh"
