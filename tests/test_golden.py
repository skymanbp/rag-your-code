from __future__ import annotations

import json
from pathlib import Path

from benchmarks.run_benchmark import FIXTURE_ROOT, GOLDEN_PATH, build_units, evaluate, hybrid_search, run


def test_golden_queries_have_expected_units():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    units = build_units(FIXTURE_ROOT)
    ids = {(unit.path, unit.name) for unit in units}
    for query in golden["queries"]:
        assert all((item["path"], item["name"]) in ids for item in query["relevant"])


def test_hybrid_retrieval_meets_golden_recall():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    units = build_units(FIXTURE_ROOT)
    result = evaluate("hybrid", hybrid_search, units, golden["queries"], golden["k"], repetitions=1)
    assert result["aggregate"]["recall_at_k"] == 1.0
    assert result["aggregate"]["top1_accuracy"] == 1.0
    assert result["aggregate"]["mrr"] == 1.0


def test_graph_benchmark_recovers_related_callee():
    result = run()["graph"]
    assert result["hybrid_related_recall_at_3"] == 0.0
    assert result["graph_related_recall_at_3"] == 1.0
    assert result["edges"] >= 1
    assert result["graph_top"].index("payments.py:4:retry_charge") < result["graph_top"].index("payments.py:13:refund_payment")
