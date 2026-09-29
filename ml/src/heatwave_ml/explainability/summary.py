"""The one-sentence explanation shown under the factor bars (Part 06 §3, Part 12 §2.4).

Templated from the ranked factors, never generated, so the same explanation always
gives the same sentence and every word traces to a field of the response:

    The model predicts Severe Heatwave conditions (>99% probability), mainly because of
    Temperature Deviation (+8.0 °C) and Maximum Temperature (42.6 °C). Wind Speed
    (5.0 m/s) partly offset the risk.

Factors are named with their values and no adjectives. An adjective ("high humidity")
would need a reference point, and against the obvious ones (the annual median, the
background) a factor can be "high" yet lower the risk, which reads as a contradiction.
Whether a factor raised or lowered the risk comes from its SHAP sign; the value lets
the reader judge the weather.
"""

from heatwave_ml.features.schema import FEATURE_DISPLAY, RISK_CLASS_LABELS

# A factor must carry at least this share of the explanation to be named.
MIN_SHARE_PCT = 5.0
MAX_DRIVERS = 3
MAX_OFFSETS = 2


def format_value(feature: str, value: float) -> str:
    """41.1 °C, +7.4 °C, 35%, 3.1 m/s: the display unit and precision from the shared table."""
    spec = FEATURE_DISPLAY[feature]
    number = f"{value:+.{spec['decimals']}f}" if spec["signed"] else f"{value:.{spec['decimals']}f}"
    return f"{number}%" if spec["unit"] == "%" else f"{number} {spec['unit']}"


def format_probability(p: float) -> str:
    """A whole percentage, but never "100%" or "0%": the model is never certain."""
    if p >= 0.995:
        return ">99%"
    return "<1%" if p < 0.005 else f"{p:.0%}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _named(factors, direction: str, limit: int) -> list[str]:
    chosen = [f for f in factors if f.direction == direction and abs(f.share_pct) >= MIN_SHARE_PCT]
    return [f"{f.label} ({f.display_value})" for f in chosen[:limit]]


def summarize(risk_class: str, probabilities: dict, factors) -> str:
    """One or two sentences, from factors already ranked by |contribution|."""
    raising = _named(factors, "increases_risk", MAX_DRIVERS)
    lowering = _named(factors, "decreases_risk", MAX_DRIVERS)
    head = (
        f"The model predicts {RISK_CLASS_LABELS[risk_class]} conditions "
        f"({format_probability(probabilities[risk_class])} probability)"
    )
    if risk_class == "NORMAL":
        main, other, other_text = lowering, raising[:MAX_OFFSETS], "raised the risk somewhat"
        lead = (
            "The main factor keeping the risk low is"
            if len(main) == 1
            else ("The main factors keeping the risk low are")
        )
        body = f". {lead} {_join(main)}." if main else None
    else:
        main, other, other_text = raising, lowering[:MAX_OFFSETS], "partly offset the risk"
        body = f", mainly because of {_join(main)}." if main else None

    sentence = head + (body or ". No single factor stood out.")
    if other:
        sentence += f" {_join(other)} {other_text}."
    return sentence
