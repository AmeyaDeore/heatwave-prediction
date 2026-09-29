"""Part 06: per-prediction SHAP explanations for the production model.

The backend needs one call:

    from heatwave_ml.explainability import load_production_explainer

    explainer = load_production_explainer(registry)   # at startup; refuses a stale explainer
    result = explainer.explain_one(model_input(features)).to_dict()

The contract ``to_dict`` returns is specified in docs/ml/explainability.md §3.
"""

from heatwave_ml.explainability.explainer import (
    ExplainerError,
    Explanation,
    Factor,
    HeatwaveExplainer,
    explainer_dir,
    load_production_explainer,
)

__all__ = [
    "ExplainerError",
    "Explanation",
    "Factor",
    "HeatwaveExplainer",
    "explainer_dir",
    "load_production_explainer",
]
