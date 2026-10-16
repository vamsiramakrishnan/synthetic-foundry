"""A harness command that replays recorded replies instead of calling a model.

W4's round trip needs a coding harness once: Foundry asks it to write the
documents' prose and to re-read some of them. ``harness-recording.json``
holds the replies a real run got (Claude, 2026-10-16), keyed by the SHA-256 of
the request, so the round-trip test runs offline, free and the same every
time. A request with no recording fails loudly: the world or the requests
changed, and the recording has to be made again with a live harness.

A reader request names the harness that reads (``reader_id`` is a hash of the
harness command, and its ``id`` hashes that in), so those two fields are left
out of the key: the replay is a different command from the one recorded.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RECORDING = Path(__file__).with_name("harness-recording.json")


def key(request: dict) -> str:
    """The SHA-256 of *request*, without the reading harness's identity."""
    inner = request.get("request")
    if isinstance(inner, dict) and "reader_id" in inner:
        request = {**request, "request": {k: v for k, v in inner.items()
                                          if k not in {"id", "reader_id"}}}
    return hashlib.sha256(json.dumps(request, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    request = json.load(sys.stdin)
    request_key = key(request)
    replies = json.loads(RECORDING.read_text(encoding="utf-8"))["replies"]
    if request_key not in replies:
        print(f"no recorded reply for request {request_key[:12]}; re-record with a live harness",
              file=sys.stderr)
        return 1
    print(json.dumps(replies[request_key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
