"""Apply narrow source edits; refuse changed anchors rather than guessing."""
from __future__ import annotations

import subprocess
from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if text.count(old) != 1:
        raise ValueError(f"{path}: expected one source anchor")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


subprocess.run(["git", "apply", "--recount", ".github/close-contracts/00-temporal-model.patch"], check=True)
replace("src/worldloom/collections.py", "from collections.abc import Callable, Iterable, Iterator, Sequence\n", "from collections.abc import Callable, Iterable, Iterator, Sequence\nfrom datetime import datetime\n")
replace("src/worldloom/collections.py", '''class FactCollection(Collection):
    """Facts, with temporal and authority helpers."""
''', '''class FactCollection(Collection):
    """Facts, with temporal and authority helpers."""

    def view(self, observer: str, *, valid_at: datetime, tx_at: datetime) -> FactCollection:
        """The same bitemporal read boundary used by predicates and narration."""
        from .epistemics import ledger_from_facts

        return FactCollection(ledger_from_facts(self).view(
            observer, valid_at=valid_at, tx_at=tx_at,
        ))

    def known_by(self, observer: str, *, tx_at: datetime) -> FactCollection:
        """Active records accessible to this observer at transaction time."""
        return self.filter(lambda fact: fact.visible_to(observer) and fact.known_at(tx_at))
''')
replace("src/worldloom/narrative/claims.py", "fact.valid_from > request.temporal_cutoff", "(fact.valid_from > request.temporal_cutoff or fact.recorded_at > request.temporal_cutoff)")
replace("src/worldloom/narrative/claims.py", 'f"{fact_id} only becomes valid at {fact.valid_from.isoformat()},"', 'f"{fact_id} is valid from {fact.valid_from.isoformat()} and recorded at {fact.recorded_at.isoformat()},"')
replace("src/worldloom/narrative/compiler.py", "    cutoff = manifest.created_at if manifest else None\n", '''    cutoff = manifest.created_at if manifest else None

    # Keep legacy request bytes stable. Explicit observer/transaction metadata
    # narrows new requests before a writer sees them; historic evidence remains
    # citable, but a backdated correction cannot arrive before its record time.
    allowed = [fact_id for fact_id in allowed
               if facts[fact_id].visible_to(author.id)
               and (facts[fact_id].tx_from is None or cutoff is None
                    or facts[fact_id].recorded_at <= cutoff)]
''')
replace("src/worldloom/narrative/compiler.py", "    comparators = _comparators(allowed, facts, cutoff)\n", '''    comparators = {
        key: value for key, value in _comparators(allowed, facts, cutoff).items()
        if facts[value].visible_to(author.id)
        and (cutoff is None or facts[value].recorded_at <= cutoff)
    }
''')
replace("CHANGELOG.md", "## Unreleased\n", '''## Unreleased

### Generation — canonical bitemporal views

- Add opt-in observer, source and transaction-time fields to canonical facts.
  Unset fields retain legacy serialized bytes. Explicit latent channels do not
  leak into employee views; late corrections cannot enter earlier narration.
- Historical predicates and bounded joins share a frozen query context.
  Missing fields are distinct from null; booleans are not numeric witnesses.
  Unsupported historical construction refuses rather than inventing state.
''')
