"""Token usage and cost estimation for Anthropic calls."""

from __future__ import annotations

from dataclasses import dataclass

# Claude Haiku 4.5 list pricing (USD per million tokens) — update if Anthropic changes rates.
HAIKU_INPUT_USD_PER_MTOK = 1.0
HAIKU_OUTPUT_USD_PER_MTOK = 5.0


@dataclass(frozen=True)
class LlmUsage:
    model: str
    input_tokens: int
    output_tokens: int
    api_calls: int = 1

    def estimated_cost_usd(
        self,
        *,
        input_usd_per_mtok: float = HAIKU_INPUT_USD_PER_MTOK,
        output_usd_per_mtok: float = HAIKU_OUTPUT_USD_PER_MTOK,
    ) -> float:
        return (
            self.input_tokens * input_usd_per_mtok + self.output_tokens * output_usd_per_mtok
        ) / 1_000_000


@dataclass
class LlmUsageTotals:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0

    def add(self, usage: LlmUsage) -> None:
        if not self.model:
            self.model = usage.model
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.api_calls += usage.api_calls

    @property
    def estimated_cost_usd(self) -> float:
        usage = LlmUsage(
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            api_calls=self.api_calls,
        )
        return usage.estimated_cost_usd()

    def merge(self, other: LlmUsageTotals) -> None:
        if not other.has_usage:
            return
        if not self.model:
            self.model = other.model
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.api_calls += other.api_calls


    @property
    def has_usage(self) -> bool:
        return self.api_calls > 0


def format_llm_cost_usd(amount: float) -> str:
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"


def format_llm_usage_summary(usage: LlmUsageTotals) -> str:
    if not usage.has_usage:
        return ""
    cost = format_llm_cost_usd(usage.estimated_cost_usd)
    return (
        f"**LLM разход (Haiku):** {cost}\n"
        f"- API calls: {usage.api_calls}\n"
        f"- tokens: {usage.input_tokens:,} in / {usage.output_tokens:,} out\n"
        f"_Оценка по list price; виж Anthropic console за точна сума._"
    )
