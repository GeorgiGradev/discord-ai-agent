"""Grounded Q&A evaluation — enabled after C2 agent is implemented."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"


def _load_questions() -> list[dict]:
    if yaml is None:
        pytest.skip("PyYAML not installed")
    data = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return list(data.get("questions", []))


@pytest.mark.eval
@pytest.mark.skip(reason="Q&A eval requires C2 grounded agent")
@pytest.mark.parametrize("question", _load_questions(), ids=lambda q: q["id"])
def test_qa_eval_question(question: dict) -> None:
    """Placeholder until agent + citations validator exist."""
    raise NotImplementedError("Implement in C2")
