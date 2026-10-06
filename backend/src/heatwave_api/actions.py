"""Recommended authority actions: a deterministic mapping from a prediction's risk
class and SHAP factors to a fixed action list (config/recommended_actions.yaml)."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from heatwave_ml.features import FEATURE_COLUMNS, FEATURE_DISPLAY, RISK_CLASS_LABELS

RISK_CLASSES = ("NORMAL", "HEATWAVE", "SEVERE_HEATWAVE")
DIRECTIONS = ("increases_risk", "decreases_risk")


@dataclass(frozen=True)
class Action:
    code: str
    text: str


@dataclass(frozen=True)
class FactorRule:
    feature: str
    direction: str
    min_share_pct: float
    classes: tuple[str, ...]
    action: Action

    def matches(self, risk_class: str, factor: dict) -> bool:
        if risk_class not in self.classes or factor["direction"] != self.direction:
            return False
        return abs(factor["share_pct"]) >= self.min_share_pct


@dataclass(frozen=True)
class ActionPlan:
    version: str
    by_class: dict[str, tuple[Action, ...]]
    factor_rules: tuple[FactorRule, ...]

    @classmethod
    def load(cls, path: Path) -> "ActionPlan":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if tuple(raw["classes"]) != RISK_CLASSES:
            raise ValueError(f"{path}: classes must be exactly {RISK_CLASSES} in that order")
        by_class = {
            name: tuple(Action(**a) for a in actions) for name, actions in raw["classes"].items()
        }
        rules = []
        for rule in raw.get("factor_rules", []):
            if rule["feature"] not in FEATURE_COLUMNS:
                raise ValueError(f"{path}: unknown feature {rule['feature']!r}")
            if rule["direction"] not in DIRECTIONS:
                raise ValueError(f"{path}: direction must be one of {DIRECTIONS}")
            if not set(rule["classes"]) <= set(RISK_CLASSES):
                raise ValueError(f"{path}: unknown class in {rule['classes']}")
            rules.append(
                FactorRule(
                    feature=rule["feature"],
                    direction=rule["direction"],
                    min_share_pct=float(rule["min_share_pct"]),
                    classes=tuple(rule["classes"]),
                    action=Action(**rule["action"]),
                )
            )
        groups = {name: [a.code for a in actions] for name, actions in by_class.items()}
        groups["factor_rules"] = [r.action.code for r in rules]
        for name, codes in groups.items():
            if name in RISK_CLASSES and not codes:
                raise ValueError(f"{path}: {name} has no actions")
            if len(codes) != len(set(codes)):
                raise ValueError(f"{path}: duplicate action code in {name}")
        return cls(
            version=str(raw["actions_version"]), by_class=by_class, factor_rules=tuple(rules)
        )

    def recommend(self, risk_class: str, factors: list[dict]) -> list[dict]:
        """The ordered action list for one prediction, each with why it is there."""
        out: list[dict] = []
        seen: set[str] = set()

        def add(action: Action, reason: str) -> None:
            if action.code not in seen:
                seen.add(action.code)
                out.append(
                    {
                        "rank": len(out) + 1,
                        "code": action.code,
                        "text": action.text,
                        "reason": reason,
                    }
                )

        for action in self.by_class[risk_class]:
            add(action, f"{RISK_CLASS_LABELS[risk_class]} predicted")
        by_feature = {f["feature"]: f for f in factors}
        for rule in self.factor_rules:
            factor = by_feature.get(rule.feature)
            if factor and rule.matches(risk_class, factor):
                verb = "raised" if rule.direction == "increases_risk" else "lowered"
                label = FEATURE_DISPLAY[rule.feature]["label"]
                add(
                    rule.action,
                    f"{label} {verb} the risk ({abs(factor['share_pct']):.0f}% of the explanation)",
                )
        return out
