"""Evaluation harness for payment extraction quality."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from assistant.domain.payments import RecordType, normalize_payee
from assistant.extraction.base import ExtractedRecord, MessageView
from assistant.extraction.money import find_verbatim_quote
from assistant.extraction.pipeline import _run_cascade
from assistant.extraction.validation import validate_records

EVAL_ROOT = Path(__file__).parent
EMAILS_DIR = EVAL_ROOT / "emails"
CASES_DIR = EMAILS_DIR / "cases"
FIXTURES_DIR = EVAL_ROOT.parent / "fixtures" / "emails"

COMPARE_FIELDS = (
    "record_type",
    "payee",
    "subscriber_number",
    "description",
    "amount_minor",
    "currency",
    "due_date",
    "payment_status",
)


@dataclass(frozen=True)
class ExpectedRecord:
    record_type: str
    payee: str
    subscriber_number: str | None = None
    description: str | None = None
    amount_minor: int = 0
    currency: str = "EUR"
    due_date: str | None = None
    payment_status: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectedRecord:
        return cls(
            record_type=data["record_type"],
            payee=data["payee"],
            subscriber_number=data.get("subscriber_number"),
            description=data.get("description"),
            amount_minor=data["amount_minor"],
            currency=data.get("currency", "EUR"),
            due_date=data.get("due_date"),
            payment_status=data.get("payment_status"),
        )


@dataclass(frozen=True)
class EvalCase:
    id: str
    description: str
    sender: str | None
    subject: str | None
    labels: list[str]
    text_body: str | None
    html_body: str | None
    expected_extractor: str | None
    expected_records: list[ExpectedRecord]
    expect_no_records: bool = False
    expect_template_miss: bool = False


@dataclass
class FieldMetrics:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float:
        predicted = self.true_positive + self.false_positive
        return 1.0 if predicted == 0 else self.true_positive / predicted

    @property
    def recall(self) -> float:
        expected = self.true_positive + self.false_negative
        return 1.0 if expected == 0 else self.true_positive / expected

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)


@dataclass
class EvalReport:
    cases_total: int = 0
    cases_passed: int = 0
    records_expected: int = 0
    records_predicted: int = 0
    citation_valid: int = 0
    citation_total: int = 0
    field_metrics: dict[str, FieldMetrics] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def citation_validity_rate(self) -> float:
        if self.citation_total == 0:
            return 1.0
        return self.citation_valid / self.citation_total

    @property
    def field_f1_min(self) -> float:
        if not self.field_metrics:
            return 1.0
        return min(metric.f1 for metric in self.field_metrics.values())

    def summary(self) -> str:
        lines = [
            f"cases: {self.cases_passed}/{self.cases_total} passed",
            f"records: expected={self.records_expected} predicted={self.records_predicted}",
            f"citation_validity: {self.citation_validity_rate:.3f}",
            f"field_f1_min: {self.field_f1_min:.3f}",
        ]
        for name, metric in sorted(self.field_metrics.items()):
            lines.append(
                f"  {name}: P={metric.precision:.3f} R={metric.recall:.3f} F1={metric.f1:.3f}"
            )
        if self.failures:
            lines.append("failures:")
            lines.extend(f"  - {item}" for item in self.failures)
        return "\n".join(lines)


def ubb_html(rows: list[tuple[str, str, str, str]]) -> str:
    """Build minimal UBB BitoviSmetki HTML with Bulgarian table rows."""
    header = (
        '<tr><td>Име на компания</td><td>Абонатен номер</td>'
        "<td>Описание</td><td>Сума</td></tr>"
    )
    body_rows = "".join(
        f"<tr><td>{payee}</td><td>{subscriber}</td>"
        f"<td>{description}</td><td>{amount}</td></tr>"
        for payee, subscriber, description, amount in rows
    )
    return (
        "<html><body>"
        f'<table id="TableOblg">{header}{body_rows}</table>'
        "</body></html>"
    )


def anthropic_text(
    *,
    amount: str = "€21.60",
    receipt_number: str = "2118-1269-0068",
    product: str = "Claude Pro Qty 1",
) -> str:
    return (
        "Anthropic, PBC\n\n"
        f"Receipt from Anthropic, PBC {amount} Paid November 22, 2025\n"
        f"Receipt #{receipt_number} Nov 22 – Dec 22, 2025 {product} "
        f"€18.00 Subtotal €18.00 Total excluding tax €18.00 Tax (20%) €3.60 "
        f"Total {amount} Amount paid {amount}\n"
    )


def _record_key(record: ExpectedRecord | ExtractedRecord) -> tuple[str, str | None, int]:
    payee = record.payee if isinstance(record, ExtractedRecord) else record.payee
    subscriber = (
        record.subscriber_number
        if isinstance(record, ExtractedRecord)
        else record.subscriber_number
    )
    amount = record.amount_minor
    return normalize_payee(payee), subscriber, amount


def _field_value(record: ExpectedRecord | ExtractedRecord, field_name: str) -> Any:
    value = getattr(record, field_name)
    if field_name == "record_type" and isinstance(value, RecordType):
        return value.value
    if field_name == "payee" and isinstance(value, str):
        return normalize_payee(value)
    return value


def _load_body(case_dir: Path, meta: dict[str, Any]) -> tuple[str | None, str | None]:
    if "html" in meta:
        return None, meta["html"]
    if "text" in meta:
        return meta["text"], None

    body_file = meta.get("body_file")
    if not body_file:
        return None, None

    path = (case_dir / body_file).resolve()
    if not path.exists():
        path = (FIXTURES_DIR / Path(body_file).name).resolve()
    content = path.read_text(encoding="utf-8")
    body_type = meta.get("body_type", "html" if path.suffix == ".html" else "text")
    if body_type == "html":
        return None, content
    return content, None


def load_case(case_dir: Path) -> EvalCase:
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    text_body, html_body = _load_body(case_dir, meta)

    return EvalCase(
        id=meta["id"],
        description=meta.get("description", meta["id"]),
        sender=meta.get("sender"),
        subject=meta.get("subject"),
        labels=list(meta.get("labels", [])),
        text_body=text_body,
        html_body=html_body,
        expected_extractor=expected.get("extractor"),
        expected_records=[
            ExpectedRecord.from_dict(item) for item in expected.get("records", [])
        ],
        expect_no_records=expected.get("expect_no_records", False),
        expect_template_miss=expected.get("expect_template_miss", False),
    )


def load_manifest() -> list[EvalCase]:
    manifest_path = EMAILS_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for entry in manifest["cases"]:
        case_dir = CASES_DIR / entry["path"]
        cases.append(load_case(case_dir))
    return cases


def _message_view(case: EvalCase) -> MessageView:
    return MessageView(
        id=0,
        account_id=1,
        gm_msgid=f"eval:{case.id}",
        sender=case.sender,
        subject=case.subject,
        labels=case.labels,
        received_at=None,
        text_body=case.text_body,
        html_body=case.html_body,
    )


def _citation_valid(msg: MessageView, record: ExtractedRecord) -> bool:
    try:
        find_verbatim_quote(
            record.evidence_quote,
            text=msg.text_body,
            html=msg.html_body,
        )
    except ValueError:
        return False
    return record.amount_raw in record.evidence_quote


def _compare_records(
    case: EvalCase,
    predicted: list[ExtractedRecord],
    report: EvalReport,
) -> bool:
    expected = case.expected_records
    report.records_expected += len(expected)
    report.records_predicted += len(predicted)

    expected_map = {_record_key(record): record for record in expected}
    predicted_map = {_record_key(record): record for record in predicted}

    ok = True
    if set(expected_map) != set(predicted_map):
        ok = False
        report.failures.append(
            f"{case.id}: record keys expected={sorted(expected_map)} "
            f"predicted={sorted(predicted_map)}"
        )

    all_keys = set(expected_map) | set(predicted_map)
    for field_name in COMPARE_FIELDS:
        metric = report.field_metrics.setdefault(field_name, FieldMetrics())
        for key in all_keys:
            exp = expected_map.get(key)
            pred = predicted_map.get(key)
            if exp is None and pred is not None:
                metric.false_positive += 1
                ok = False
                report.failures.append(
                    f"{case.id}: unexpected record {key} field={field_name}"
                )
                continue
            if pred is None and exp is not None:
                metric.false_negative += 1
                ok = False
                report.failures.append(
                    f"{case.id}: missing record {key} field={field_name}"
                )
                continue
            if exp is None or pred is None:
                continue
            if _field_value(exp, field_name) == _field_value(pred, field_name):
                metric.true_positive += 1
            else:
                metric.false_positive += 1
                metric.false_negative += 1
                ok = False
                report.failures.append(
                    f"{case.id}: {key} {field_name} "
                    f"expected={_field_value(exp, field_name)!r} "
                    f"predicted={_field_value(pred, field_name)!r}"
                )

    msg = _message_view(case)
    for record in predicted:
        report.citation_total += 1
        if _citation_valid(msg, record):
            report.citation_valid += 1
        else:
            ok = False
            report.failures.append(
                f"{case.id}: invalid citation for {record.payee} {record.amount_raw!r}"
            )

    return ok


def evaluate_case(case: EvalCase, report: EvalReport) -> bool:
    report.cases_total += 1
    msg = _message_view(case)

    try:
        records, extractor_name, template_miss = _run_cascade(msg)
    except Exception as exc:
        report.failures.append(f"{case.id}: cascade raised {exc!r}")
        return False

    if case.expect_template_miss:
        if not template_miss:
            report.failures.append(f"{case.id}: expected template_miss=True")
            return False
        report.cases_passed += 1
        return True

    if case.expect_no_records:
        if records:
            report.failures.append(
                f"{case.id}: expected no records, got {len(records)} from {extractor_name}"
            )
            return False
        if case.expected_extractor and extractor_name != case.expected_extractor:
            report.failures.append(
                f"{case.id}: extractor expected={case.expected_extractor!r} "
                f"got={extractor_name!r}"
            )
            return False
        report.cases_passed += 1
        return True

    if case.expected_extractor and extractor_name != case.expected_extractor:
        report.failures.append(
            f"{case.id}: extractor expected={case.expected_extractor!r} "
            f"got={extractor_name!r}"
        )
        return False

    try:
        validate_records(msg, records)
    except ValueError as exc:
        report.failures.append(f"{case.id}: validation failed: {exc}")
        return False

    if _compare_records(case, records, report):
        report.cases_passed += 1
        return True
    return False


def run_extraction_eval() -> EvalReport:
    report = EvalReport()
    for case in load_manifest():
        evaluate_case(case, report)
    return report
