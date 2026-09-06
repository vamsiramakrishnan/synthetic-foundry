"""Installed-package CLI: python -m worldloom.process_planning --all --out DIR."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import (
    CompanyProcessSpec,
    compile_company,
    default_company,
    export_compilations,
    load_catalogue,
    replay_plan,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compile authored process factors; does not claim executed/calibrated evaluations.")
    parser.add_argument("--catalogue", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path)
    source.add_argument("--all", action="store_true")
    source.add_argument("--industry")
    source.add_argument("--replay", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--max-instances", type=int, default=100_000)
    args = parser.parse_args(argv)
    try:
        if args.replay is not None:
            if args.catalogue is not None or args.seed is not None or args.core_only:
                raise ValueError("replay uses its pinned catalogue, seed and stream selection")
            plan = replay_plan(args.replay, strict=args.strict, max_instances=args.max_instances)
            export_compilations([plan], args.out)
            print(json.dumps(plan.summary, sort_keys=True))
            return
        cat = load_catalogue(args.catalogue)
        if args.spec is not None:
            specs = [CompanyProcessSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))]
            if args.seed is not None:
                specs = [s.model_copy(update={"seed": args.seed}) for s in specs]
        else:
            industries = sorted(cat.industry_overlays) if args.all else [args.industry]
            specs = [default_company(ind, seed=8128 if args.seed is None else args.seed) for ind in industries]
        plans = [compile_company(s, cat, core_only=args.core_only, strict=args.strict, max_instances=args.max_instances) for s in specs]
        export_compilations(plans, args.out)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"process catalogue: {error}\n")
    for plan in plans:
        print(json.dumps(plan.summary, sort_keys=True))


if __name__ == "__main__":
    main()
