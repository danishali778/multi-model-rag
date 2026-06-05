from __future__ import annotations

import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python scripts/wait_for_http.py <url> <timeout-seconds>")
        return 2

    url = sys.argv[1]
    timeout_seconds = int(sys.argv[2])
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if 200 <= response.status < 300:
                    print(f"ready: {url}")
                    return 0
        except URLError:
            pass
        time.sleep(2)

    print(f"timed out waiting for {url}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
