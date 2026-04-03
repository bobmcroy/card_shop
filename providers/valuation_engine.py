from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from providers.ebay_comp_buckets import CompBuckets


@dataclass(frozen=True)
class LiquidityModel:
    name: str
    recent_median_weight: float
    strong_bin_weight: float
    peak_auction_weight: float

    def validate(self) -> None:
        total = (
            self.recent_median_weight
            + self.strong_bin_weight
            + self.peak_auction_weight
        )
        if round(total, 6) != 1.0:
            raise ValueError(
                f"Liquidity model weights must sum to 1.0, got {total}"
            )


MODEL_A = LiquidityModel(
    name="Model A - Standard Liquidity",
    recent_median_weight=0.60,
    strong_bin_weight=0.30,
    peak_auction_weight=0.10,
)

MODEL_B = LiquidityModel(
    name="Model B - Star / High Liquidity",
    recent_median_weight=0.40,
    strong_bin_weight=0.50,
    peak_auction_weight=0.10,
)


@dataclass(frozen=True)
class ValuationResult:
    model_name: str
    weighting_mode: str
    recent_median_value: Optional[float]
    strong_bin_value: Optional[float]
    peak_auction_value: Optional[float]
    effective_recent_median_weight: float
    effective_strong_bin_weight: float
    effective_peak_auction_weight: float
    blended_value: Optional[float]


def _round2(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _effective_weights(
    buckets: CompBuckets,
    model: LiquidityModel,
    rebalance_missing: bool,
) -> tuple[float, float, float]:
    base = {
        "recent": model.recent_median_weight,
        "bin": model.strong_bin_weight,
        "auction": model.peak_auction_weight,
    }

    present = {
        "recent": buckets.recent_median_value is not None,
        "bin": buckets.strong_bin_value is not None,
        "auction": buckets.peak_auction_value is not None,
    }

    if not rebalance_missing:
        return (
            base["recent"] if present["recent"] else 0.0,
            base["bin"] if present["bin"] else 0.0,
            base["auction"] if present["auction"] else 0.0,
        )

    kept_total = sum(weight for key, weight in base.items() if present[key])
    if kept_total == 0:
        return (0.0, 0.0, 0.0)

    return (
        (base["recent"] / kept_total) if present["recent"] else 0.0,
        (base["bin"] / kept_total) if present["bin"] else 0.0,
        (base["auction"] / kept_total) if present["auction"] else 0.0,
    )


def apply_liquidity_model(
    buckets: CompBuckets,
    model: LiquidityModel,
    *,
    rebalance_missing: bool = False,
) -> ValuationResult:
    model.validate()

    recent_w, bin_w, auction_w = _effective_weights(
        buckets,
        model,
        rebalance_missing=rebalance_missing,
    )

    total = 0.0
    used_any = False

    if buckets.recent_median_value is not None and recent_w > 0:
        total += buckets.recent_median_value * recent_w
        used_any = True

    if buckets.strong_bin_value is not None and bin_w > 0:
        total += buckets.strong_bin_value * bin_w
        used_any = True

    if buckets.peak_auction_value is not None and auction_w > 0:
        total += buckets.peak_auction_value * auction_w
        used_any = True

    return ValuationResult(
        model_name=model.name,
        weighting_mode="rebalance" if rebalance_missing else "strict",
        recent_median_value=_round2(buckets.recent_median_value),
        strong_bin_value=_round2(buckets.strong_bin_value),
        peak_auction_value=_round2(buckets.peak_auction_value),
        effective_recent_median_weight=round(recent_w, 4),
        effective_strong_bin_weight=round(bin_w, 4),
        effective_peak_auction_weight=round(auction_w, 4),
        blended_value=_round2(total) if used_any else None,
    )


def valuation_to_dict(result: ValuationResult) -> dict[str, Any]:
    return {
        "model_name": result.model_name,
        "weighting_mode": result.weighting_mode,
        "recent_median_value": result.recent_median_value,
        "strong_bin_value": result.strong_bin_value,
        "peak_auction_value": result.peak_auction_value,
        "effective_recent_median_weight": result.effective_recent_median_weight,
        "effective_strong_bin_weight": result.effective_strong_bin_weight,
        "effective_peak_auction_weight": result.effective_peak_auction_weight,
        "blended_value": result.blended_value,
    }