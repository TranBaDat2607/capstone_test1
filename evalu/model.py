"""Result container shared by every metric in evalu/metrics.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MetricResult:
    """
    One label-free measurement.

    `value` is None whenever the metric is genuinely undefined (0/0). That is a
    deliberate distinction from 0.0: "no claim had any evidence to exclude" and
    "every piece of evidence was excluded" are opposite findings, and collapsing
    both to zero would misreport the pipeline.

    `target` / `passed` are advisory only. Nothing in this package gates a
    pipeline run — §2 of the framework is diagnostic instrumentation, not a
    quality gate.

    `purpose` / `how_to_read` / `limitation` are not decoration. A number with no
    stated purpose cannot be used in a thesis: the reader cannot tell what a good
    value means, nor what a bad one obliges them to do. `limitation` is required
    wherever the metric is near-tautological or blind to its real failure mode —
    stating that on the face of the report is the difference between a diagnostic
    and a misleading reassurance.
    """

    metric_id: str
    module: str
    name: str
    value: Optional[float] = None
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    target: Optional[str] = None
    passed: Optional[bool] = None
    higher_is_better: bool = True
    purpose: str = ""
    how_to_read: str = ""
    limitation: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def pct(self) -> Optional[str]:
        return None if self.value is None else f"{self.value * 100:.2f}%"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "module": self.module,
            "name": self.name,
            "value": self.value,
            "pct": self.pct,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "target": self.target,
            "passed": self.passed,
            "higher_is_better": self.higher_is_better,
            "purpose": self.purpose,
            "how_to_read": self.how_to_read,
            "limitation": self.limitation,
            "details": self.details,
        }


def ratio(numerator: float, denominator: float) -> Optional[float]:
    """0/0 is undefined, not zero — see MetricResult.value."""
    if not denominator:
        return None
    return numerator / denominator
