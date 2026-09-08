"""Enterprise fixture and executable-row bytes survive process hash randomization."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from worldloom.corpus import tree_divergence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = """
import json
import sys
from pathlib import Path
from worldloom.world import World
from worldloom.enterprise_queries import plan_queries
from worldloom.enterprise_corpus import materialize_corpus
from worldloom.enterprise_io import export_corpus
from worldloom.enterprise_rows import compile_rows, runtime_records
world = World.load('examples/retail-close')
queries, _ = plan_queries(world, strategy='exhaustive', limit=32, dag_shapes=('*',) if sys.argv[2] == 'grammar' else ())
corpus = materialize_corpus(world, tuple(queries))
out = Path(sys.argv[1])
export_corpus(corpus, out)
report = compile_rows(corpus.queries, corpus.fixtures, runtime_records(corpus.connector_data.records))
compiled = {'rows': report.rows, 'refusals': report.reasons()}
(out / 'rows.json').write_text(json.dumps(compiled, sort_keys=True) + '\\n', encoding='utf-8', newline='\\n')
"""


@pytest.mark.parametrize('trajectory', ('legacy', 'grammar'))
def test_fixture_and_compiler_replay_across_hash_seeds(tmp_path: Path, trajectory: str) -> None:
    outputs = [tmp_path / "first", tmp_path / "second"]
    for seed, directory in zip(("13", "927"), outputs, strict=True):
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT, str(directory), trajectory],
            cwd=ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert tree_divergence(*outputs) is None
