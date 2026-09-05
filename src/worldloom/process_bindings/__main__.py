"""Installed CLI: python -m worldloom.process_bindings --all --out compiled."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..corpus import write_json
from .compiler import compile_company, default_company, load_catalogue, resource
from .models import CompanySpec
from .storage import summary, verify_export, write_compilation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile authored industry process structure; report evidence and binding gaps.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--industry")
    mode.add_argument("--spec", type=Path)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--catalogue", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Fail on unresolved core streams, ambiguous ownership or unknown system bindings.")
    parser.add_argument("--max-instances", type=int, default=100_000)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            compiled = verify_export(args.verify, catalogue=load_catalogue(args.catalogue))
            print(json.dumps({"verified":True,"digest":compiled.digest},sort_keys=True))
            return 0
        if args.out is None:
            parser.error("--out is required when compiling")
        if args.out.exists():
            raise ValueError(f"refusing to overwrite {args.out}")
        cat = load_catalogue(args.catalogue)
        if args.all:
            specs = [default_company(industry) for industry in sorted(resource("defaults.json")["DEFAULT_ORGS"])]
        elif args.spec:
            specs = [CompanySpec.model_validate_json(args.spec.read_text(encoding="utf-8"))]
        else:
            specs = [default_company(args.industry)]
        # Validate and budget every company before creating the output tree.
        compiled_all = [compile_company(spec,catalogue=cat,core_only=args.core_only,
                        strict=args.strict,max_instances=args.max_instances) for spec in specs]
        args.out.mkdir(parents=True, exist_ok=False)
        summaries: list[dict[str, Any]] = []
        for compiled in compiled_all:
            # Filenames derive from stable ordinals, never company names
            # which can contain path separators in a customer's supplied spec.
            name = f"company-{len(summaries):03d}"
            write_compilation(compiled,args.out/name)
            item = {**summary(compiled),"directory":name}
            summaries.append(item)
            print(json.dumps(item,sort_keys=True))
        write_json(args.out/"coverage.json",{"summary":summaries})
        write_json(args.out/"sources.json",resource("bindings-provenance.json"))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error":"process_catalogue_refused","message":str(error)},sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
