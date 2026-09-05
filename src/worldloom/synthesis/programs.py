"""Small, inspectable business mechanisms, not company-name substitutions.

These are declared assumptions, not fitted customer distributions. Retail has
physical stock, lead times, latent demand and lost sales. Banking has a loan
balance, interest, missed payments, and arrears. Both use integer units.
"""

from __future__ import annotations

from .models import (
    Column,
    Constraint,
    Expr,
    Parameter,
    Program,
    Relation,
    Table,
    expr,
    lag,
    literal,
    param,
    ref,
    uniform,
)


def _column(name: str, expression: Expr, *, unit: str | None = None,
            minimum: int | None = 0, intervenable: bool = False) -> Column:
    return Column(name=name, expression=expression, unit=unit,
                  minimum=minimum, intervenable=intervenable)


def retail(*, stores: int = 8, products: int = 12, ticks: int = 30) -> Program:
    """A store-product daily inventory process with two-tick order lead time.

    Demand is latent; sales are censored by stock. Replenishment uses inventory
    position (on hand plus outstanding orders), not today's sales alone.
    """
    r = ref
    return Program(
        namespace="retail_operations", ticks=ticks,
        parameters=(
            Parameter(name="target_stock", value=55, minimum=5, maximum=200, mutable=True),
            Parameter(name="initial_stock", value=30, minimum=0, maximum=200, mutable=True),
            Parameter(name="promotion_pct", value=25, minimum=0, maximum=100, mutable=True),
        ),
        tables=(
            Table(name="store", count=stores, columns=(
                _column("demand_scale", uniform(75, 125, stream="store_scale", scope="entity"), unit="percent"),
                _column("region", expr("mod", r("_entity"), literal(4))),
            )),
            Table(name="product", count=products, columns=(
                _column("base_demand", uniform(5, 16, stream="product_demand", scope="entity"), unit="units"),
                _column("price", uniform(150, 2500, stream="price", scope="entity"), unit="minor_currency"),
                _column("cost", expr("div", expr("mul", r("price"), literal(65)), literal(100)), unit="minor_currency"),
            )),
            Table(name="inventory", count=stores * products, temporal=True,
                  relations=(Relation(name="store", table="store", stride=products),
                             Relation(name="product", table="product")),
                  columns=(
                      _column("opening", lag("closing", param("initial_stock")), unit="units"),
                      _column("receipts", lag("order", 0, steps=2), unit="units"),
                      _column("pipeline", lag("order", 0), unit="units"),
                      _column("market", uniform(80, 120, stream="market", scope="tick"), unit="index"),
                      _column("noise", uniform(75, 125, stream="demand_noise"), unit="index"),
                      _column("promotion", expr("if", expr("eq", expr("mod", r("_tick"), literal(7)), literal(5)),
                                                param("promotion_pct"), literal(0)), unit="percent", intervenable=True),
                      _column("demand", expr("div", expr("mul", r("product.base_demand"), r("store.demand_scale"),
                                                          r("market"), r("noise"), expr("add", literal(100), r("promotion"))),
                                                 literal(100_000_000)), unit="units", intervenable=True),
                      _column("available", expr("add", r("opening"), r("receipts")), unit="units"),
                      _column("sold", expr("min", r("demand"), r("available")), unit="units"),
                      _column("lost", expr("sub", r("demand"), r("sold")), unit="units"),
                      _column("closing", expr("sub", r("available"), r("sold")), unit="units"),
                      _column("order", expr("max", literal(0), expr("sub", param("target_stock"),
                                                                    expr("add", r("closing"), r("pipeline")))), unit="units"),
                      _column("revenue", expr("mul", r("sold"), r("product.price")), unit="minor_currency"),
                      _column("cost", expr("mul", r("sold"), r("product.cost")), unit="minor_currency"),
                      _column("margin", expr("sub", r("revenue"), r("cost")), unit="minor_currency"),
                  ), constraints=(
                      Constraint(name="stock_conservation", predicate=expr("eq", expr("add", r("opening"), r("receipts")), expr("add", r("sold"), r("closing")))),
                      Constraint(name="demand_conservation", predicate=expr("eq", r("demand"), expr("add", r("sold"), r("lost")))),
                      Constraint(name="no_oversell", predicate=expr("le", r("sold"), r("available"))),
                  )),
        ),
    )


def banking(*, borrowers: int = 64, ticks: int = 12) -> Program:
    """Monthly servicing. A missed payment adds arrears, not extra principal.

    Interest is capitalized, cash first clears accumulated due amounts, and
    payments cannot exceed the amount actually owed. No regulatory claims.
    """
    r = ref
    return Program(
        namespace="loan_servicing", ticks=ticks,
        parameters=(
            Parameter(name="monthly_rate_bps", value=50, minimum=0, maximum=200, mutable=True),
            Parameter(name="payment_pct", value=5, minimum=1, maximum=30, mutable=True),
            Parameter(name="income_shock_pct", value=0, minimum=0, maximum=60, mutable=True),
        ),
        tables=(
            Table(name="borrower", count=borrowers, columns=(
                _column("principal", uniform(100_000, 2_000_000, stream="principal", scope="entity"), unit="minor_currency"),
                _column("capacity_pct", uniform(2, 9, stream="capacity", scope="entity"), unit="percent"),
                _column("risk_band", uniform(0, 3, stream="risk", scope="entity")),
            )),
            Table(name="loan", count=borrowers, temporal=True,
                  relations=(Relation(name="borrower", table="borrower"),),
                  columns=(
                      _column("opening", lag("closing", r("borrower.principal")), unit="minor_currency"),
                      _column("interest", expr("div", expr("mul", r("opening"), param("monthly_rate_bps")), literal(10_000)), unit="minor_currency"),
                      _column("owed", expr("add", r("opening"), r("interest")), unit="minor_currency"),
                      _column("prior_arrears", lag("arrears", 0), unit="minor_currency"),
                      _column("scheduled", expr("min", r("owed"), expr("div", expr("mul", r("borrower.principal"), param("payment_pct")), literal(100))), unit="minor_currency"),
                      _column("due", expr("min", r("owed"), expr("add", r("scheduled"), r("prior_arrears"))), unit="minor_currency"),
                      _column("income_noise", uniform(70, 130, stream="income_noise"), unit="index"),
                      _column("capacity", expr("div", expr("mul", r("borrower.principal"), r("borrower.capacity_pct"), r("income_noise"), expr("sub", literal(100), param("income_shock_pct"))), literal(1_000_000)), unit="minor_currency", intervenable=True),
                      _column("paid", expr("min", r("due"), r("capacity")), unit="minor_currency"),
                      _column("closing", expr("sub", r("owed"), r("paid")), unit="minor_currency"),
                      _column("arrears", expr("sub", r("due"), r("paid")), unit="minor_currency"),
                      _column("missed_periods", expr("if", expr("lt", literal(0), r("arrears")),
                                                     expr("add", lag("missed_periods", 0), literal(1)), literal(0))),
                  ), constraints=(
                      Constraint(name="balance_conservation", predicate=expr("eq", expr("add", r("opening"), r("interest")), expr("add", r("paid"), r("closing")))),
                      Constraint(name="arrears_within_balance", predicate=expr("le", r("arrears"), r("closing"))),
                  )),
        ),
    )
