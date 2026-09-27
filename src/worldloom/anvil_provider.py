"""``python -m worldloom.anvil_provider``: an Anvil state provider over Worldloom records.

The implementation is ``worldloom.connectors.anvil_provider``; this module is
the short name ``--provider-cmd`` takes.
"""

from __future__ import annotations

import sys

from .connectors.anvil_provider import main

if __name__ == "__main__":
    sys.exit(main())
