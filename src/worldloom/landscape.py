"""What an estate is *called*, per engine — so a bank can have one.

``generators/estate.py`` grows the only technology landscape this tool has: a
layered DAG with placed chokepoints, which is what makes blast radius, "who gets
paged", and "what does nothing route around" answerable questions. Until now it
could only be grown for a grocer, and `cli.py` refused ``--estate`` for every
other vertical rather than mis-serve it. That refusal was right about the
problem and wrong about the fix. The estate's *construction* — five layers, an
edge only ever pointing at a strictly lower depth, a chokepoint given a private
backing store — is engine physics and has nothing to do with retail. Only the
**words** were retail's: ``click-collect-api``, ``markdown-optimiser``,
``Range Studio``. A bank with those names is worse than a bank with no estate,
which is exactly what the refusal said; a bank with ``rwa-capital-engine`` and
``collateral-revaluation-feed`` is neither.

So this module is the vocabulary, extracted from the generator and made
authorable, and the generator keeps the physics.

**Why a module of its own, rather than more of ``profiles.py``.** That module's
charter ("shapes a world has that are not ranges") would admit a landscape
without complaint, and the contract here is deliberately identical to
``Seasonality``'s: a named default lifted verbatim from the literal it replaces,
a short registry of presets that are unlike each other, unknown names refused,
and byte-identity when defaulted. The reason to split is proportion, not
principle. Three verticals of pools is some four hundred names — more than the
whole of ``profiles.py`` — and folding them in would bury the one thing an
author goes to that module for, the trading year, under an estate catalogue.
``parameters.py`` and ``profiles.py`` already split on exactly this axis (a
range is not a shape); a vocabulary is a third thing again, and the three read
better as three files than as one long one.

**What is deliberately *not* opened, and why.** ``estate.DEPTH`` stays in the
generator. It looks like naming — five strings — but the names are the
generator's own coordinate system rather than anything a reader ever sees: no
fact, artifact, renderer or validator prints "platform", and ``Service`` carries
no layer at all (giving it one is the thin-waist contamination build-order §7
forbids). The generator reasons about those names structurally — it builds
bottom-up in a fixed order, derives ``criticality_tier`` from the layer, and
places the gate at ``DEPTH[layer] > DEPTH["platform"]``. A vocabulary free to
rename "platform" would have to move the chokepoint rule, the tier map and the
build order with it, which is the construction the estate exists to guarantee.
So the layers are fixed and a ``Landscape`` is validated *against* them: a
vocabulary that forgets a layer or invents one is refused here rather than
producing an estate with a silently empty tier.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The layers a landscape must name a pool for, in no particular order — the
#: build order is the generator's. ``system`` is absent because systems are not
#: drawn from a name pool: they are name/purpose/system-of-record triples, which
#: is a different shape and is carried separately.
GENERATIVE: tuple[str, ...] = ("edge", "domain", "platform", "data")

#: Every layer a size profile must give a count for, including ``system``.
SIZED: tuple[str, ...] = (*GENERATIVE, "system")


@dataclass(frozen=True)
class Landscape:
    """The words one engine's technology estate is built out of.

    Everything here is naming and counting. Nothing here can change the shape of
    the graph — that is ``generators/estate.py``'s, and the whole point of the
    split is that a pack authoring an insurer's vocabulary cannot accidentally
    author a cyclic estate.
    """

    services: Mapping[str, tuple[str, ...]]
    """Service-name pool per generative layer. Drawn in order, not sampled, so
    the first *n* names of a pool are what a profile of size *n* mints — which
    makes a pool's order an authoring decision and not an implementation
    detail. It is also what puts the chokepoints at the head of the platform
    pool, where an author can see which two services the estate will gate on."""

    systems: tuple[tuple[str, str, str], ...]
    """Systems of record: ``(name, purpose, what it is the record for)``. The
    tail of this tuple becomes the chokepoints' private backing stores, so the
    last entries should be the ones it is plausible nothing else queries
    directly."""

    purpose: Mapping[str, str]
    """One purpose sentence per generative layer, with ``{name}`` in it. Terse
    for the reason the engine's are terse: a real service catalogue is terse,
    and a paragraph per node would put hundreds of sentences of unreviewed
    prose into a corpus whose whole claim is that its prose is checked."""

    profiles: Mapping[str, Mapping[str, int]]
    """Size profiles: how many nodes per layer. Deliberately not derived from
    the archetype's headcount — see ``generators/estate.PROFILES`` on why a
    ratio claiming otherwise would be a fabricated benchmark."""

    chokepoints: int = 2
    """How many platform services are single-provider gates."""

    about: str = ""
    source: str = ""
    """Where the vocabulary came from, when a pack supplies one. Same boundary
    as everywhere else in this project: a sector's typical system estate is a
    prior and is welcome; one identifiable company's service catalogue is that
    company's data wearing a costume."""

    def __post_init__(self) -> None:
        for layer in GENERATIVE:
            pool = self.services.get(layer)
            if not pool:
                raise ValueError(
                    f"the {layer!r} layer has no service names; a landscape must"
                    f" name a pool for each of {list(GENERATIVE)}"
                )
            if any(not name.strip() for name in pool):
                raise ValueError(f"the {layer!r} pool contains a blank service name")
            template = self.purpose.get(layer)
            if not template or "{name}" not in template:
                raise ValueError(
                    f"the {layer!r} layer needs a purpose sentence containing"
                    " '{name}' — the generator formats the service's own name into it"
                )
        extra = sorted(set(self.services) - set(GENERATIVE))
        if extra:
            raise ValueError(
                f"{extra} are not layers a landscape names services for; the"
                f" layering is the generator's construction, not vocabulary"
            )

        # Across the whole landscape, not per layer. Two nodes sharing a name is
        # not a duplicate id — the graph is still well formed — but every
        # document that quotes one becomes ambiguous about which it meant, and
        # `worldloom topology` prints a name beside a blast radius.
        names = [name for layer in GENERATIVE for name in self.services[layer]]
        if len(set(names)) != len(names):
            repeated = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"service name(s) {repeated} appear in more than one layer")

        if not self.systems:
            raise ValueError("a landscape needs at least one system of record")
        for entry in self.systems:
            if len(entry) != 3 or not all(str(part).strip() for part in entry):
                raise ValueError(
                    f"a system is (name, purpose, system-of-record); got {entry!r}"
                )
        system_names = [name for name, _, _ in self.systems]
        if len(set(system_names)) != len(system_names):
            raise ValueError("two systems share a name")
        records = [record for _, _, record in self.systems]
        if len(set(records)) != len(records):
            raise ValueError(
                "two systems claim to be the system of record for the same thing,"
                " which is the one property a system of record has"
            )

        if self.chokepoints < 1:
            raise ValueError(
                "an estate needs at least one chokepoint. `compose.review` refuses"
                " a model-authored estate in which nothing is a single point of"
                " failure, and generating one the other path would reject is not a"
                " defensible asymmetry"
            )

        if not self.profiles:
            raise ValueError("a landscape needs at least one size profile")
        for size, counts in self.profiles.items():
            missing = [layer for layer in SIZED if layer not in counts]
            if missing:
                raise ValueError(f"profile {size!r} gives no count for {missing}")
            unknown = sorted(set(counts) - set(SIZED))
            if unknown:
                raise ValueError(f"profile {size!r} counts {unknown}, which are not layers")
            for layer, count in counts.items():
                if count < 0:
                    raise ValueError(f"profile {size!r} asks for {count} {layer} nodes")
            # Refused rather than truncated. The generator takes
            # `min(count, len(pool))`, so a profile asking for more than the
            # vocabulary holds quietly builds a smaller estate than it says it
            # does — `--estate large` returning a medium one, with nothing
            # anywhere to say so.
            for layer in GENERATIVE:
                if counts[layer] > len(self.services[layer]):
                    raise ValueError(
                        f"profile {size!r} wants {counts[layer]} {layer} services but"
                        f" the pool holds {len(self.services[layer])}"
                    )
            if counts["system"] > len(self.systems):
                raise ValueError(
                    f"profile {size!r} wants {counts['system']} systems but the"
                    f" landscape names {len(self.systems)}"
                )
            # The two conditions under which the generator places no chokepoint
            # at all. Both are silent there: the estate builds, validates, and
            # is simply a landscape in which nothing gates anything — the exact
            # shape this whole module exists to keep producible.
            if counts["system"] <= self.chokepoints:
                raise ValueError(
                    f"profile {size!r} mints {counts['system']} system(s), which"
                    f" cannot back {self.chokepoints} chokepoint(s) *and* leave one"
                    " shared. A chokepoint is a chokepoint because it has a store"
                    " only it may reach; with none reserved it gates nothing"
                )
            if counts["platform"] < self.chokepoints:
                raise ValueError(
                    f"profile {size!r} mints {counts['platform']} platform"
                    f" service(s) but {self.chokepoints} of them are meant to be"
                    " chokepoints"
                )

    def profile(self, size: str) -> Mapping[str, int]:
        """The counts for a named size. Unknown sizes are refused."""
        try:
            return self.profiles[size]
        except KeyError:
            raise ValueError(
                f"unknown estate profile {size!r}; expected one of {sorted(self.profiles)}"
            ) from None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "services": {layer: list(self.services[layer]) for layer in GENERATIVE},
            "systems": [list(entry) for entry in self.systems],
            "purpose": {layer: self.purpose[layer] for layer in GENERATIVE},
            "profiles": {
                size: {layer: counts[layer] for layer in SIZED}
                for size, counts in sorted(self.profiles.items())
            },
            "chokepoints": self.chokepoints,
        }
        if self.about:
            payload["about"] = self.about
        if self.source:
            payload["source"] = self.source
        return payload


#: Shared by all three shipped vocabularies, and that is a decision rather than
#: laziness. The profile is a statement about how big *the landscape* is, and
#: ``--estate medium`` has to mean the same size of landscape whichever engine
#: is running or the flag stops being comparable across corpora. What differs
#: between a grocer and a bank is which words fill it, which is the rest of this
#: module. A pack that genuinely needs a different shape writes its own
#: ``profiles`` — the field is on the type precisely so it can.
_SIZES: dict[str, dict[str, int]] = {
    "small":  {"edge": 3, "domain": 5, "platform": 3, "data": 3, "system": 3},
    "medium": {"edge": 8, "domain": 14, "platform": 6, "data": 8, "system": 6},
    "large":  {"edge": 18, "domain": 34, "platform": 10, "data": 18, "system": 12},
}

#: One purpose sentence per layer, shared for the same reason ``_SIZES`` is:
#: what the sentence says is what the *layer* means, and the layer means the
#: same thing in a bank as in a grocer. The industry is in the name it formats.
_PURPOSE: dict[str, str] = {
    "edge": "Customer- or colleague-facing surface: {name}",
    "domain": "Business capability service: {name}",
    "platform": "Shared platform capability used across the estate: {name}",
    "data": "Data pipeline publishing to downstream consumers: {name}",
}


# ---------------------------------------------------------------------------
# Retail — the engine's own, extracted verbatim
# ---------------------------------------------------------------------------

#: What ``generators/estate.py`` had hardcoded, moved here unchanged. Left first
#: and named for what it actually is, so that an author choosing a vocabulary is
#: choosing rather than inheriting — ``profiles.RETAIL_CHRISTMAS``'s rule.
RETAIL = Landscape(
    services={
        "edge": (
            "storefront-web", "store-colleague-app", "self-checkout-client", "kiosk-ui",
            "customer-account-portal", "click-collect-api", "delivery-tracking-web",
            "loyalty-app", "supplier-portal", "returns-desk-ui", "gift-card-web",
            "price-check-terminal", "warehouse-handheld", "driver-app", "call-centre-console",
            "franchise-portal", "b2b-ordering-api", "in-store-signage",
        ),
        "domain": (
            "pricing-engine", "promotions-engine", "basket-service", "order-orchestrator",
            "fulfilment-router", "stock-availability", "replenishment-planner",
            "range-planning", "supplier-onboarding", "payments-gateway", "refunds-service",
            "loyalty-points", "delivery-slotting", "returns-processing", "invoice-matching",
            "purchase-order-service", "markdown-optimiser", "space-planning",
            "labour-scheduling", "shrinkage-analytics", "customer-profile",
            "recommendation-service", "search-ranking", "tax-calculation",
            "credit-check-service", "fraud-screening", "warranty-registration",
            "subscription-billing", "gift-card-ledger", "carbon-reporting",
            "allergen-lookup", "recipe-service", "store-locator", "wait-time-estimator",
        ),
        "platform": (
            "identity-provider", "config-service", "event-bus", "feature-flags",
            "notification-gateway", "audit-log", "secrets-broker", "api-gateway",
            "job-scheduler", "observability-collector",
        ),
        "data": (
            "sales-feed", "stock-movement-feed", "supplier-master-feed", "price-change-feed",
            "customer-consent-feed", "warehouse-stock-extract", "pos-transaction-stream",
            "forecast-publisher", "colleague-roster-extract", "gl-journal-extract",
            "margin-cube-builder", "basket-analytics-pipeline", "waste-reporting-extract",
            "supplier-invoice-feed", "range-change-feed", "loyalty-event-stream",
            "delivery-telemetry-feed", "store-footfall-feed",
        ),
    },
    systems=(
        ("Workforce Central", "Rostering, time and attendance for the store estate", "colleague_roster"),
        ("Vendor Exchange", "Supplier master, contracts and trading terms", "supplier_master"),
        ("Warehouse Control", "Distribution centre stock and pick management", "warehouse_stock"),
        ("Transport Desk", "Route planning and delivery execution", "delivery_plan"),
        ("People Hub", "Employee records, payroll input and org structure", "employee_record"),
        ("Contact Centre Suite", "Customer contacts, cases and escalations", "customer_case"),
        ("Range Studio", "Assortment and space planning of record", "range_plan"),
        ("Treasury Desk", "Cash, banking and settlement positions", "settlement"),
        ("Property Register", "Leases, sites and store fit-out records", "site_lease"),
        ("Learning Exchange", "Colleague training records and compliance sign-off", "training_record"),
        ("Loyalty Core", "Member records, points balances and redemptions", "loyalty_member"),
        ("Insurance Register", "Group insurance programme and claims register", "insurance_claim"),
    ),
    purpose=_PURPOSE,
    profiles=_SIZES,
    about="Omnichannel retail: stores, a storefront, a supply chain and a"
          " loyalty programme. The engine's own, and what every estate built"
          " before this module existed was made of.",
)


# ---------------------------------------------------------------------------
# Banking
# ---------------------------------------------------------------------------

#: A deposit-taking bank's landscape, extending the world ``banking_org`` and
#: ``generators/regulatory.py`` already name rather than inventing a parallel
#: one. Those modules mint five systems (core banking, the collateral register,
#: the risk platform, the regulatory portal, market data) and four services
#: (``collateral-valuation-sync``, ``rwa-capital-engine``, ``lcr-daily-calculator``,
#: ``regulatory-filing-gateway``), and the capital-return episode's causality
#: runs through them. Nothing here repeats any of those names: the estate grows
#: *around* the episode, and a second ``rwa-capital-engine`` would make the
#: corpus ambiguous about which one the incident broke.
#:
#: The two chokepoints are the head of the platform pool. Identity is the
#: obvious one and every estate has it; entitlements is the banking-specific
#: one, and it is a genuine single provider rather than a convenient
#: chokepoint — segregation of duties and four-eyes approval are worth nothing
#: if a second service can answer "may this person do this".
BANKING = Landscape(
    services={
        "edge": (
            "internet-banking-web", "mobile-banking-app", "broker-origination-portal",
            "branch-teller-console", "business-banking-portal",
            "relationship-manager-desktop", "atm-network-gateway",
            "card-servicing-portal", "loan-application-web", "customer-onboarding-app",
            "collections-workbench", "treasury-dealer-desktop",
            "prudential-reporting-console", "audit-evidence-portal",
            "credit-committee-workspace", "disputes-intake-web",
            "merchant-services-portal", "customer-consent-centre",
        ),
        "domain": (
            "credit-decision-engine", "limits-and-exposure-service",
            "payments-clearing-service", "direct-entry-processor",
            "card-authorisation-service", "interest-accrual-service",
            "fee-and-charge-engine", "arrears-management-service",
            "provisioning-engine", "capital-attribution-service",
            "liquidity-forecasting-service", "funds-transfer-pricing",
            "counterparty-reference-service", "kyc-screening-service",
            "sanctions-screening-service", "fraud-detection-service",
            "transaction-monitoring-service", "hardship-assessment-service",
            "mortgage-servicing-engine", "deposit-pricing-service",
            "product-terms-service", "statement-generation-service",
            "customer-consent-service", "broker-commission-engine",
            "valuation-panel-router", "security-registration-service",
            "settlement-instruction-service", "nostro-reconciliation-service",
            "general-ledger-posting-service", "tax-withholding-service",
            "regulatory-rule-engine", "stress-testing-engine",
            "model-execution-service", "collateral-eligibility-service",
        ),
        "platform": (
            "identity-provider", "entitlements-service", "event-bus",
            "batch-scheduler", "api-gateway", "audit-log", "secrets-broker",
            "notification-gateway", "reference-data-service",
            "observability-collector",
        ),
        "data": (
            "general-ledger-extract", "exposure-position-feed",
            "collateral-revaluation-feed", "arrears-ageing-extract",
            "deposit-balance-feed", "cash-flow-ladder-builder",
            "fx-rate-distribution", "credit-rating-feed", "loan-tape-extract",
            "counterparty-master-feed", "transaction-history-stream",
            "regulatory-return-staging", "capital-datamart-builder",
            "provision-model-inputs", "hardship-flag-feed", "customer-master-feed",
            "branch-activity-extract", "broker-settlement-feed",
        ),
    },
    systems=(
        ("Origination Desk", "Loan origination and credit decisioning of record", "loan_applications"),
        ("Counterparty Register", "Counterparty master, groups and legal entity structure", "counterparty_master"),
        ("Payments Hub", "Clearing, settlement and direct entry execution", "payment_instructions"),
        ("Card Services Platform", "Card issuing, authorisation and disputes", "card_transactions"),
        ("Deposit Book", "Retail and business deposit accounts and their pricing", "deposit_accounts"),
        ("Arrears Workbench", "Collections, hardship and recovery case management", "arrears_cases"),
        ("Treasury Management System", "Wholesale funding, hedging and nostro positions", "funding_positions"),
        ("Branch Register", "Branch and ATM sites, leases and opening hours", "branch_site"),
        ("Complaints Register", "Complaints, remediation and external dispute resolution", "complaint_case"),
        ("Colleague Register", "Employee records, delegations and approval authorities", "employee_record"),
        # The last two back the chokepoints, and both are stores a bank really
        # does gate: the model inventory decides which model version may be run
        # at all, and the financial crime suite's alerts are not something the
        # rest of the estate is allowed to browse.
        ("Model Inventory", "Model register, validation status and approved versions", "model_inventory"),
        ("Financial Crime Suite", "KYC, sanctions and transaction monitoring alerts", "financial_crime_alerts"),
    ),
    purpose=_PURPOSE,
    profiles=_SIZES,
    about="A deposit-taking bank: origination, collateral, payments, a"
          " regulatory filing path and the risk data behind a capital return."
          " Extends the systems and services `banking_org` already mints for"
          " the quarterly capital-return episode.",
)


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

#: A general insurer's landscape. Insurance is the vertical the estate was
#: furthest out of reach of: ``insurance_org.generate`` returns ``services=()``,
#: so a reserving corpus has had *no* technology graph at all — every question
#: about blast radius or what gates the valuation was unanswerable, not merely
#: thin. The five systems it does mint (policy admin, claims, actuarial, the
#: general ledger, the reinsurance register) are the ones ``reserving.py`` names
#: by role handle, and this vocabulary extends around them without repeating
#: any of them.
#:
#: The chokepoints differ from banking's second, and deliberately. An insurer's
#: single point of failure is the document vault: a policy schedule, a claim
#: file, an assessor's report and the correspondence trail are the same object
#: to every part of the business, and there is exactly one of it. That is a
#: sharper claim about this industry than "identity, then entitlements" would
#: have been, and it is the kind of thing the estate exists to let a reader
#: discover from the graph rather than be told.
INSURANCE = Landscape(
    services={
        "edge": (
            "broker-quote-portal", "policy-self-service-web", "claims-lodgement-app",
            "underwriter-workbench", "assessor-mobile-app", "policyholder-portal",
            "adviser-portal", "contact-centre-console", "claims-case-console",
            "actuarial-review-workspace", "reinsurance-broker-portal",
            "repairer-network-portal", "complaints-intake-web",
            "policy-document-viewer", "quote-comparison-api", "premium-payment-web",
            "solvency-reporting-console", "board-reporting-workspace",
        ),
        "domain": (
            "premium-rating-engine", "underwriting-rules-engine",
            "policy-issuance-service", "endorsement-service", "renewal-engine",
            "cancellation-service", "claims-triage-service",
            "claims-assessment-service", "case-reserve-service",
            "claims-payment-service", "recovery-and-subrogation",
            "salvage-disposal-service", "reserving-engine",
            "ibnr-projection-service", "development-pattern-service",
            "reinsurance-cession-engine", "treaty-allocation-service",
            "facultative-placement-service", "catastrophe-modelling-service",
            "exposure-accumulation-service", "premium-collection-service",
            "commission-settlement-service", "policy-document-generator",
            "fraud-indicator-service", "customer-identity-matching",
            "complaints-management-service", "hardship-assessment-service",
            "reinstatement-service", "excess-calculation-service",
            "repairer-allocation-service", "claim-cost-estimation",
            "solvency-capital-engine", "premium-liability-service",
            "reserve-journal-posting-service",
        ),
        "platform": (
            "identity-provider", "document-store", "event-bus", "entitlements-service",
            "batch-scheduler", "api-gateway", "audit-log", "notification-gateway",
            "reference-data-service", "observability-collector",
        ),
        "data": (
            "policy-in-force-extract", "premium-earning-feed",
            "claims-transaction-feed", "case-movement-stream", "paid-loss-extract",
            "incurred-loss-extract", "development-triangle-builder",
            "reinsurance-recovery-feed", "exposure-snapshot-extract",
            "large-loss-notification-feed", "actuarial-datamart-builder",
            "reserve-journal-extract", "broker-remittance-feed",
            "catastrophe-event-feed", "repairer-cost-feed",
            "complaint-outcome-extract", "solvency-position-feed",
            "policyholder-consent-feed",
        ),
    },
    systems=(
        ("Broker Register", "Intermediary master, appointments and commission terms", "broker_master"),
        ("Repairer Network", "Approved repairers, panels and service level records", "repairer_network"),
        ("Complaints Register", "Complaints, remediation and external dispute resolution", "complaint_case"),
        ("Exposure Store", "Geospatial exposure and accumulation of record", "exposure_aggregate"),
        ("Product Library", "Product wordings, endorsements and version history", "product_wording"),
        ("Payments Bureau", "Premium collection and claim settlement disbursement", "settlement"),
        ("Colleague Register", "Employee records, delegated authorities and licensing", "employee_record"),
        ("Catastrophe Model Suite", "Peril models, event sets and licensed hazard data", "catastrophe_event"),
        ("Regulatory Returns Store", "Prudential and conduct returns as lodged", "lodged_return"),
        ("Accreditation Register", "Adviser and assessor training and accreditation records", "training_record"),
        # The chokepoints' private stores, in the order the generator reserves
        # them: the document vault backs the document store, and the
        # underwriting authority register backs identity's entitlement lookup.
        ("Underwriting Authority Register", "Binding authorities, referral limits and sign-off", "underwriting_authority"),
        ("Document Vault", "Policy schedules, claim files and correspondence of record", "policy_document"),
    ),
    purpose=_PURPOSE,
    profiles=_SIZES,
    about="A general insurer: policy administration, claims, actuarial"
          " reserving, reinsurance and the document trail all four run on."
          " Extends the systems `insurance_org` mints for the quarterly"
          " reserving episode, which ships with no services at all.",
)


#: Named vocabularies a pack or an engine may pick by name. Deliberately few and
#: deliberately unlike each other, ``profiles.PROFILES``'s rule: a long list of
#: near-identical catalogues would be a menu rather than a decision.
LANDSCAPES: dict[str, Landscape] = {
    "retail": RETAIL,
    "banking": BANKING,
    "insurance": INSURANCE,
}

#: What an un-overridden build uses, and what every estate built before this
#: module existed was made of.
DEFAULT = RETAIL


def named(name: str) -> Landscape:
    """A vocabulary by name. Unknown names are refused, never defaulted.

    Refused for the reason every other override surface in this project refuses
    them: a pack asking for ``bankng`` that silently got the retailer's would
    build a bank running a ``click-collect-api`` and give the author no way
    whatsoever to notice — which is the exact failure the CLI's blanket refusal
    of ``--estate`` was protecting against, and it would be perverse to
    reintroduce it here while lifting it there.
    """
    try:
        return LANDSCAPES[name]
    except KeyError:
        raise KeyError(
            f"unknown estate vocabulary {name!r}; known: {sorted(LANDSCAPES)}."
            " A pack may also supply pools of its own."
        ) from None


def from_document(payload: Mapping[str, Any] | str) -> Landscape:
    """A vocabulary from a pack or a recipe: a name, or pools of its own."""
    if isinstance(payload, str):
        return named(payload)
    try:
        services = {
            layer: tuple(str(name) for name in payload["services"][layer])
            for layer in payload.get("services", {})
        }
        systems = tuple(
            (str(entry[0]), str(entry[1]), str(entry[2])) for entry in payload["systems"]
        )
        profiles = {
            str(size): {str(layer): int(count) for layer, count in counts.items()}
            for size, counts in payload["profiles"].items()
        }
        purpose = {str(layer): str(text) for layer, text in payload["purpose"].items()}
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"a landscape needs services, systems, purpose and profiles: {exc}") from exc
    return Landscape(
        services=services, systems=systems, purpose=purpose, profiles=profiles,
        chokepoints=int(payload.get("chokepoints", 2)),
        about=str(payload.get("about", "")), source=str(payload.get("source", "")),
    )


def publish() -> dict[str, Any]:
    """Every named vocabulary as data. An author cannot choose what they cannot see."""
    return {name: value.as_dict() for name, value in sorted(LANDSCAPES.items())}


def register(name: str, landscape: Landscape) -> None:
    """Register an estate vocabulary for a vertical.

    Called by domain modules (procurement, future verticals) to add their own
    estate vocabularies to the global registry. Redefinition is refused — every
    name may appear only once. A vocabulary is named only once per vertical, so
    a name collision is a wiring error rather than a legitimate override.

    Raised rather than silently absorbed if a name is already known, because a
    duplicate in the registration chain is a wiring error: either the module was
    imported twice, or two domains collided on the same name. Neither is
    silent-and-plausible.
    """
    if name in LANDSCAPES:
        raise KeyError(
            f"landscape {name!r} is already registered. Each landscape name may"
            f" appear only once; a collision is a wiring error in one of the"
            f" modules calling register."
        )
    LANDSCAPES[name] = landscape


__all__ = [
    "BANKING", "DEFAULT", "GENERATIVE", "INSURANCE", "LANDSCAPES", "RETAIL",
    "SIZED", "Landscape", "from_document", "named", "publish", "register",
]
