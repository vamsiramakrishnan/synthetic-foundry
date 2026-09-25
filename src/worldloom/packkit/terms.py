"""Colloquial terms: ``{{term:site}}`` in any template, filled by the industry.

One term is stored once, lower-case and singular (``site: branch``); the
capitalised and plural forms a sentence needs are derived, so a pack never
has to spell ``Site``, ``sites`` and ``Sites`` separately and cannot make
them disagree:

- ``{{term:site}}`` → ``branch``
- ``{{term:Site}}`` → ``Branch`` (first letter of the term capitalised)
- ``{{term:SITE}}`` → ``BRANCH``
- ``{{term:sites}}`` → ``branches`` (derived when ``sites`` is not itself a term)

A pack may still state an irregular plural as its own term
(``person: patient``, ``persons: patients``); a stated term always wins over a
derived one.
"""

from __future__ import annotations

from collections.abc import Mapping

from .models import TERM


def plural(word: str) -> str:
    """English plural of the last word of *word*; enough for nouns a pack names."""
    head, _, last = word.rpartition(" ")
    lower = last.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        out = last + "es"
    elif lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        out = last[:-1] + "ies"
    else:
        out = last + "s"
    return f"{head} {out}" if head else out


def base_key(token: str, terms: Mapping[str, str] | set[str]) -> str | None:
    """The stored term a token refers to, or ``None`` when it names none."""
    lower = token.lower()
    if lower in terms:
        return lower
    if lower.endswith("s"):
        for candidate in (lower[:-1], lower[:-2], lower[:-3] + "y"):
            if candidate in terms and plural(candidate) == lower:
                return candidate
        # A plural of a stated term whose own plural is irregular in English
        # but regular by the rule above (``sites`` → ``site``).
        if lower[:-1] in terms:
            return lower[:-1]
    return None


def term(token: str, terms: Mapping[str, str]) -> str:
    """The word *token* stands for, in the case and number the token asks for."""
    lower = token.lower()
    if lower in terms:
        word = terms[lower]
    else:
        key = base_key(token, terms)
        if key is None:
            raise KeyError(f"no term {token!r}; the industry defines {', '.join(sorted(terms))}")
        word = plural(terms[key])
    if token.isupper() and len(token) > 1:
        return word.upper()
    if token[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def fill_terms(template: str, terms: Mapping[str, str]) -> str:
    """*template* with every ``{{term:…}}`` token replaced; other text untouched."""
    if "{{term:" not in template:
        return template
    return TERM.sub(lambda match: term(match.group(1), terms), template)


__all__ = ["base_key", "fill_terms", "plural", "term"]
