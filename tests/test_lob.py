"""The LOB authoring cascade: open → roles → responsibilities → resolve.

Deliberately *not* a re-test of the lints other suites already own —
`test_properties.py` proves `lint_roles` accepts every well-formed tree and
refuses every cycle, `test_factkinds.py` proves `lint_responsibilities`
refuses a kind nothing generates, and `test_process.py` owns bindings,
participation, install and describe. What none of them touch is the session
protocol itself: that `open` starts an empty session, that `next_stage` asks
the stages in order and never out of it, that `accept` refuses with findings
and commits nothing on refusal, and that `resolve` only fires once every
stage is settled. Plus the two seed-level refusals (`lint_seed`) and the one
`lint_roles` finding the property tests can never reach — their generated
trees are always rooted at `ceo`, so the non-`ceo`-root refusal ran nowhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import lob

SEED = lob.LobSeed(
    name="treasury", title="Treasury", purpose="Manages the group's cash.",
    engine="retail",
)

ROLES = [
    lob.RoleSpec(key="ceo", title="Chief Executive", function="Executive"),
    lob.RoleSpec(
        key="treasurer", title="Group Treasurer", function="Finance",
        reports_to="ceo",
    ),
]

#: A kind the registry really generates — resolved, not invented, so this
#: test keeps passing when the registry grows.
KIND = "financial.revenue.actual"

RESPONSIBILITIES = [
    lob.Responsibility(role_key="treasurer", fact_kinds=[KIND]),
]


def _accepted_session() -> lob.Session:
    session = lob.open(SEED)
    session = lob.accept(session, lob.Answer(stage="roles", roles=ROLES))
    return lob.accept(
        session, lob.Answer(stage="responsibilities", responsibilities=RESPONSIBILITIES)
    )


# -- seeds --------------------------------------------------------------------


def test_load_seed_reads_all_three_source_shapes(tmp_path: Path) -> None:
    data = SEED.model_dump()
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert lob.load_seed(data) == SEED
    assert lob.load_seed(json.dumps(data)) == SEED
    assert lob.load_seed(path) == SEED


def test_lint_seed_accepts_a_clean_seed() -> None:
    assert lob.lint_seed(SEED) == []


def test_lint_seed_refuses_an_unregistered_engine() -> None:
    """The finding must name the impostor *and* the real choices — a refusal a
    reviser can act on, per the protocol."""
    findings = lob.lint_seed(SEED.model_copy(update={"engine": "alchemy"}))
    assert len(findings) == 1
    assert "'alchemy'" in findings[0]
    assert "retail" in findings[0], "the finding should list the registered domains"


# -- the cascade, in order ----------------------------------------------------


def test_open_starts_with_the_roles_stage() -> None:
    session = lob.open(SEED)
    assert session.roles == {}
    assert session.responsibilities == ()
    assert lob.next_stage(session).stage == "roles"


def test_stages_arrive_in_order_and_end_at_resolve() -> None:
    session = lob.open(SEED)
    session = lob.accept(session, lob.Answer(stage="roles", roles=ROLES))
    assert lob.next_stage(session).stage == "responsibilities"
    # The later brief carries what the earlier stage accepted — the protocol's
    # "context rides every brief": an answer may not rely on anything outside it.
    assert "treasurer" in lob.next_stage(session).context["roles"]
    session = lob.accept(
        session, lob.Answer(stage="responsibilities", responsibilities=RESPONSIBILITIES)
    )
    assert lob.next_stage(session).stage == "resolve"


def test_accept_returns_a_new_session_and_mutates_nothing() -> None:
    """A refusal is judged against unchanged state — which requires acceptance
    itself to replace the session rather than edit it."""
    opened = lob.open(SEED)
    accepted = lob.accept(opened, lob.Answer(stage="roles", roles=ROLES))
    assert opened.roles == {}
    assert set(accepted.roles) == {"ceo", "treasurer"}


def test_a_non_ceo_root_is_refused() -> None:
    """The one `lint_roles` finding `test_properties.py`'s trees never reach:
    its generators always root at `ceo`, so the convention check ran nowhere."""
    crowned = [
        lob.RoleSpec(key="king", title="The King", function="Executive"),
        lob.RoleSpec(
            key="treasurer", title="Group Treasurer", function="Finance",
            reports_to="king",
        ),
    ]
    with pytest.raises(ValueError, match="should be 'ceo', not 'king'"):
        lob.accept(lob.open(SEED), lob.Answer(stage="roles", roles=crowned))


def test_an_unknown_fact_kind_is_refused_at_accept() -> None:
    """`lint_responsibilities`' registry check, proven to actually gate the
    cascade — a lint nothing calls on the accept path would refuse nobody."""
    session = lob.accept(lob.open(SEED), lob.Answer(stage="roles", roles=ROLES))
    bogus = [lob.Responsibility(role_key="treasurer", fact_kinds=["financial.vibes"])]
    with pytest.raises(ValueError, match=r"'financial\.vibes' is not in the fact-kind registry"):
        lob.accept(session, lob.Answer(stage="responsibilities", responsibilities=bogus))
    # Nothing committed on refusal: the session still awaits the stage.
    assert session.responsibilities == ()


def test_an_unknown_stage_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="unknown stage: 'vibes'"):
        lob.accept(lob.open(SEED), lob.Answer(stage="vibes"))


def test_resolve_refuses_a_session_with_unsettled_stages() -> None:
    session = lob.accept(lob.open(SEED), lob.Answer(stage="roles", roles=ROLES))
    with pytest.raises(ValueError, match="not all stages have been accepted"):
        lob.resolve(session)


def test_resolve_produces_the_lob_the_session_accepted() -> None:
    resolved = lob.resolve(_accepted_session(), artifact_filings=["capital_return"])
    assert resolved.name == "treasury"
    assert resolved.engine == "retail"
    assert [r.key for r in resolved.roles] == ["ceo", "treasurer"]
    assert resolved.responsibilities == RESPONSIBILITIES
    assert resolved.artifact_filings == ["capital_return"]
    # The resolved spec is the replayable record, so it must satisfy the
    # composed lint the packs run — resolve accepting what lint_lob refuses
    # would let a session author what a pack could not carry.
    assert lob.lint_lob(resolved) == []


def test_the_resolved_role_table_matches_the_generators_shape() -> None:
    table = _accepted_session().to_role_table()
    # `roles.Role` spells the reporting edge `manager` where the authored
    # `RoleSpec` says `reports_to` — `to_role_table` is exactly that renaming.
    assert [(r.key, r.manager) for r in table] == [("ceo", None), ("treasurer", "ceo")]
