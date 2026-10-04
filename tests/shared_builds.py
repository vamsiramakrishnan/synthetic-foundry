"""Cached builds more than one test module asks for with identical arguments.

`build_cache` keys an entry on the source of the module that defines its
builder, so a builder written inline in a test module is shared only within
that module. The builders here are defined once, so every module asking for
the same projection reads the same entry.

Use these only where the result is an *input* to what a test checks. A test
whose claim is about the derivation itself being repeatable (``project`` twice
is equal, ``rederive`` twice is equal) calls ``industry.project`` directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import build_cache


def industry_project(industry_name: str, company: str, *, lobs: Sequence[str] | None = None) -> Any:
    """``industry.project(industry_name, company, lobs=lobs)``, derived once per source tree.

    A catalogue projection derives the industry's whole programme (one to
    fifteen CPU-seconds an industry) and the resulting `ProjectSpec` pickles
    to a few hundred kilobytes, so reading it back is effectively free.
    """
    from worldloom import industry

    chosen = None if lobs is None else tuple(lobs)
    recipe = {"industry": industry_name, "company": company, "lobs": None if chosen is None else list(chosen)}
    return build_cache.cached_value(
        "industry-project", recipe, lambda: industry.project(industry_name, company, lobs=chosen),
    )


def programme_summary(industry_name: str) -> Any:
    """``industry.programme(industry_name).summary``, derived once per source tree.

    The whole `Programme` pickles to tens of megabytes (logistics: 80MB) and
    takes seconds to read back; its summary is small. Callers that only read
    the summary share this entry; one that needs the programme itself derives it.
    """
    from worldloom import industry

    return build_cache.cached_value(
        "industry-programme-summary", {"industry": industry_name},
        lambda: industry.programme(industry_name).summary,
    )
