#!/usr/bin/env python3
"""Derive a compact multilingual lexicon from ESCO's official RDF export."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any


def row_for(graph: Any, subject: Any, type_: str, *, source: str) -> dict[str, Any] | None:
    from rdflib import SKOS

    preferred = list(graph.objects(subject, SKOS.prefLabel))
    if not preferred:
        return None
    english = next((label for label in preferred if label.language == "en"), preferred[0])
    alt_labels: list[dict[str, str]] = []
    for label in [*preferred, *graph.objects(subject, SKOS.altLabel)]:
        lang = label.language or "und"
        if str(label) == str(english) and lang == (english.language or "und"):
            continue
        alt_labels.append({"lang": lang, "label": str(label)})

    isco_uri: str | None = None
    for predicate in (SKOS.broader, SKOS.exactMatch, SKOS.closeMatch, SKOS.broadMatch):
        for target in graph.objects(subject, predicate):
            if "isco" in str(target).lower():
                isco_uri = str(target)
                break
        if isco_uri:
            break

    uri = str(subject)
    concept_id = uri.rstrip("/").rsplit("/", 1)[-1]
    return {
        "id": f"esco:{concept_id}",
        "type": type_,
        "label": str(english),
        "canonical": isco_uri or uri,
        "alt_labels": alt_labels,
        "lang": english.language or "und",
        "industry": None,
        "region": None,
        "weight": 1.0,
        "source": source,
        "license": "European Commission ESCO reuse terms",
        "concept_uri": uri,
        "isco_uri": isco_uri,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rdf", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default="esco-1.2.0")
    args = parser.parse_args()

    from rdflib import Graph, Namespace, RDF, URIRef

    graph = Graph()
    graph.parse(args.rdf)
    esco = Namespace("http://data.europa.eu/esco/model#")
    classes = {
        URIRef(str(esco.Occupation)): "title",
        URIRef(str(esco.Skill)): "activity",
        URIRef(str(esco.SkillCompetence)): "activity",
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for subject, _, class_uri in graph.triples((None, RDF.type, None)):
        type_ = classes.get(class_uri)
        uri = str(subject)
        if type_ is None or uri in seen:
            continue
        seen.add(uri)
        row = row_for(graph, subject, type_, source=args.source)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda item: item["id"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8", newline="\n", compresslevel=9) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"rows": len(rows), "out": str(args.out)}, sort_keys=True))


if __name__ == "__main__":
    main()
