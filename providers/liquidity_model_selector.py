from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


MODEL_A_NAME = "Model A - Standard Liquidity"
MODEL_B_NAME = "Model B - Star / High Liquidity"

MIN_COMP_COUNT_FOR_MARKET_PROMOTION = 8
STRONG_BIN_PREMIUM_THRESHOLD = 1.15


HIGH_LIQUIDITY_PLAYERS = {
    "baseball": {
        "ken griffey jr",
        "ken griffey",
        "griffey jr",
        "griffey",
        "derek jeter",
        "cal ripken jr",
        "nolan ryan",
        "ricky henderson",
        "bo jackson",
        "frank thomas",
        "barry bonds",
        "deion sanders",
    },
    "football": {
        "barry sanders",
        "emmitt smith",
        "jerry rice",
        "joe montana",
        "dan marino",
        "troy aikman",
        "brett favre",
        "walter payton",
        "deion sanders",
    },
    "basketball": {
        "michael jordan",
        "shaquille o'neal",
        "kobe bryant",
        "magic johnson",
        "larry bird",
        "charles barkley",
        "penny hardaway",
        "anfernee hardaway",
        "hakeem olajuwaon",
    },
    "hockey": {
        "wayne gretzky",
        "mario lemieux",
        "patrick roy",
        "steve yzerman",
        "mark messier",
    },
}


@dataclass(frozen=True)
class LiquiditySelectorInput:
    sport: str
    year: int
    set_name: str
    player_name: Optional[str] = None
    card_number: Optional[str] = None
    filtered_comp_count: int = 0
    recent_median_value: Optional[float] = None
    strong_bin_value: Optional[float] = None
    peak_auction_value: Optional[float] = None
    manual_model_override: Optional[str] = None


@dataclass(frozen=True)
class LiquiditySelectionResult:
    selected_model_name: str
    confidence: str
    reason: str
    triggered_by: list[str]


def _norm(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _is_manual_model_a(value: str | None) -> bool:
    v = _norm(value)
    return v in {
        "a",
        "model a",
        "standard",
        "standard liquidity",
        MODEL_A_NAME.lower(),
    }


def _is_manual_model_b(value: str | None) -> bool:
    v = _norm(value)
    return v in {
        "b",
        "model b",
        "star",
        "star liquidity",
        "high liquidity",
        "star / high liquidity",
        MODEL_B_NAME.lower(),
    }


def _is_curated_high_liquidity_player(sport: str, player_name: str | None) -> bool:
    sport_key = _norm(sport)
    player_key = _norm(player_name)

    if not sport_key or not player_key:
        return False

    return player_key in HIGH_LIQUIDITY_PLAYERS.get(sport_key, set())


def _has_market_behavior_premium(
    *,
    filtered_comp_count: int,
    recent_median_value: Optional[float],
    strong_bin_value: Optional[float],
) -> bool:
    if filtered_comp_count < MIN_COMP_COUNT_FOR_MARKET_PROMOTION:
        return False

    if recent_median_value is None or strong_bin_value is None:
        return False

    if recent_median_value <= 0:
        return False

    ratio = strong_bin_value / recent_median_value
    return ratio >= STRONG_BIN_PREMIUM_THRESHOLD


def select_liquidity_model(
    selector_input: LiquiditySelectorInput,
) -> LiquiditySelectionResult:
    if _is_manual_model_a(selector_input.manual_model_override):
        return LiquiditySelectionResult(
            selected_model_name=MODEL_A_NAME,
            confidence="high",
            reason="Manual override selected Model A.",
            triggered_by=["manual_override"],
        )

    if _is_manual_model_b(selector_input.manual_model_override):
        return LiquiditySelectionResult(
            selected_model_name=MODEL_B_NAME,
            confidence="high",
            reason="Manual override selected Model B.",
            triggered_by=["manual_override"],
        )

    if _is_curated_high_liquidity_player(
        selector_input.sport,
        selector_input.player_name,
    ):
        return LiquiditySelectionResult(
            selected_model_name=MODEL_B_NAME,
            confidence="high",
            reason="Player matched curated high-liquidity star list.",
            triggered_by=["curated_star_player"],
        )

    if _has_market_behavior_premium(
        filtered_comp_count=selector_input.filtered_comp_count,
        recent_median_value=selector_input.recent_median_value,
        strong_bin_value=selector_input.strong_bin_value,
    ):
        return LiquiditySelectionResult(
            selected_model_name=MODEL_B_NAME,
            confidence="medium",
            reason=(
                "Market behavior promoted this card to Model B because "
                "strong BIN pricing materially exceeded recent median pricing."
            ),
            triggered_by=["market_behavior_premium"],
        )

    return LiquiditySelectionResult(
        selected_model_name=MODEL_A_NAME,
        confidence="medium",
        reason="Defaulted to Model A because no high-liquidity trigger was met.",
        triggered_by=["default_fallback"],
    )