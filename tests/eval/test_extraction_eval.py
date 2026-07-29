"""Extraction evaluation suite (deterministic, no LLM)."""

from __future__ import annotations

import pytest

from eval.harness import evaluate_case, load_manifest, run_extraction_eval


def _threshold(name: str, default: float) -> float:
    try:
        import tomllib
        from pathlib import Path

        data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        return float(data.get("tool", {}).get("assistant", {}).get("eval", {}).get(name, default))
    except Exception:
        return default


@pytest.mark.eval
def test_extraction_eval_harness_meets_thresholds():
    report = run_extraction_eval()

    field_f1_min = _threshold("extraction_field_f1_min", 0.95)
    citation_min = _threshold("citation_validity_min", 1.0)

    assert report.cases_passed == report.cases_total, report.summary()
    assert report.field_f1_min >= field_f1_min, report.summary()
    assert report.citation_validity_rate >= citation_min, report.summary()


@pytest.mark.eval
@pytest.mark.parametrize("case", load_manifest(), ids=lambda case: case.id)
def test_extraction_eval_case(case):
    from eval.harness import EvalReport

    report = EvalReport()
    assert evaluate_case(case, report), report.summary()
