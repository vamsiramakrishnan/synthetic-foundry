from worldloom.process_catalogue import (
    APQCEvidence,
    CoverageStatus,
    compile_company,
    coverage_matrix,
    default_spec,
    industries,
    load_default,
    verify_defaults,
)


def test_uploaded_catalogue_has_expected_industry_surface() -> None:
    assert industries() == (
        "banking",
        "insurance",
        "retail",
        "consumer_products",
        "telecom",
        "utilities",
        "life_sciences",
        "logistics",
        "healthcare",
        "manufacturing",
        "public_sector",
        "technology_saas",
    )
    matrix = coverage_matrix()
    assert len(matrix) == 215
    assert {cell.status for cell in matrix} == {
        CoverageStatus.BACKBONE,
        CoverageStatus.OVERLAY,
        CoverageStatus.CORPUS_CALIBRATED,
    }


def test_reference_compiler_reproduces_supplied_defaults() -> None:
    report = verify_defaults()
    assert report == {
        "industries": 12,
        "instances": 6975,
        "eval_demands": 55800,
        "coverage_cells": 215,
        "mismatched_industries": (),
        "coverage_mismatch": False,
        "ok": True,
    }


def test_compiled_rows_keep_apqc_as_authored_hint() -> None:
    compilation = load_default("banking")
    assert compilation.rows
    assert all(row.apqc_evidence is APQCEvidence.AUTHORED_HINT for row in compilation.rows)
    assert any(row.apqc.endswith(".x") for row in compilation.rows)


def test_calibration_sources_are_joinable_from_process_rows() -> None:
    banking = load_default("banking")
    lending = banking.select(stream="apply_to_disburse")
    assert lending
    assert all("bpi-2017" in row.calibration_sources for row in lending)
    assert all(row.coverage_status is CoverageStatus.CORPUS_CALIBRATED for row in lending)

    change = banking.select(stream="change_to_deploy")
    assert change
    assert all("public-jira" in row.calibration_sources for row in change)


def test_custom_company_binding_is_deterministic_and_system_complete() -> None:
    spec = default_spec("retail").model_copy(
        update={
            "name": "retail-custom",
            "countries": ("AU",),
            "landscape": {"CRM": "Dynamics 365 Sales"},
        }
    )
    first = compile_company(spec)
    second = compile_company(spec)
    assert first == second
    assert first.summary.unbound_systems == ()
    assert {row.sor_product for row in first.select(sor_class="CRM")} == {
        "Dynamics 365 Sales"
    }


def test_demand_seeds_are_grounded_without_fabricating_template_slots() -> None:
    compilation = load_default("utilities")
    first = next(compilation.demand_seeds())
    assert first["activity_id"]
    assert first["owner_bu"]
    assert first["country"] == "AU"
    assert first["sor_product"] != "unbound"
    assert "{activity}" in first["template"]
    # Record-level values such as object/stage/threshold remain unresolved until
    # corpus materialisation; the catalogue must not invent them.
    assert "prompt" not in first
