from worldloom.lexicon import (
    DistributionPrior,
    EvidenceClass,
    LexiconRecord,
    canonical_index,
)


def test_surface_forms_group_under_canonical_concept() -> None:
    records = (
        LexiconRecord(
            id="onet:11-3031.02",
            type="title",
            label="Financial Managers",
            canonical="onet:11-3031.02",
            source="onet-29.3",
            license="CC BY 4.0",
        ),
        LexiconRecord(
            id="onet:11-3031.02:alt:bank-advisor",
            type="title",
            label="Bank Advisor",
            canonical="onet:11-3031.02",
            source="onet-29.3",
            license="CC BY 4.0",
        ),
    )

    grouped = canonical_index(records)

    assert tuple(row.label for row in grouped["onet:11-3031.02"]) == (
        "Financial Managers",
        "Bank Advisor",
    )


def test_distribution_prior_requires_normalized_measurements() -> None:
    prior = DistributionPrior(
        id="uci498:incident.priority",
        canonical="incident.priority",
        probabilities={"P1": 0.02, "P2": 0.03, "P3": 0.93, "P4": 0.02},
        source="uci-498",
        license="CC BY 4.0",
        evidence=EvidenceClass.MEASURED,
    )

    assert sum(prior.probabilities.values()) == 1.0
    assert prior.evidence is EvidenceClass.MEASURED
