from __future__ import annotations

import argparse

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Usage export is not available in this B2C backend.",
    )
    parser.parse_known_args()
    raise SystemExit("Usage export is intentionally unsupported in this B2C backend.")


if __name__ == "__main__":
    main()
