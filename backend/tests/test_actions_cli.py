"""The recommended-actions mapping, and the operator CLI."""

import json

import pytest
import yaml

from heatwave_api import cli
from heatwave_api.actions import ActionPlan
from heatwave_api.config import REPO_ROOT
from heatwave_api.db import Database
from heatwave_api.db.repository import Repository
from heatwave_api.security import verify_password

ACTIONS_FILE = REPO_ROOT / "config" / "recommended_actions.yaml"


def factor(feature, share, direction="increases_risk"):
    return {"feature": feature, "share_pct": share, "direction": direction}


@pytest.fixture(scope="module")
def plan() -> ActionPlan:
    return ActionPlan.load(ACTIONS_FILE)


def test_actions_follow_the_class_then_the_matching_factor_rules(plan):
    actions = plan.recommend(
        "SEVERE_HEATWAVE",
        [
            factor("temp_deviation_c", 62.0),
            factor("rh_pct", 12.0),
            factor("wind_ms", -15.0, "decreases_risk"),
        ],
    )
    codes = [a["code"] for a in actions]
    assert codes[:5] == [a.code for a in plan.by_class["SEVERE_HEATWAVE"]]
    assert codes[5:] == ["HUMID_HEAT_GUIDANCE", "UNSEASONAL_HEAT_MESSAGE"]
    assert [a["rank"] for a in actions] == list(range(1, len(actions) + 1))
    assert actions[0]["reason"] == "Severe Heatwave predicted"
    assert actions[5]["reason"] == "Relative Humidity raised the risk (12% of the explanation)"


def test_factor_rules_need_a_risk_class_the_right_sign_and_enough_share(plan):
    normal = plan.recommend("NORMAL", [factor("rh_pct", 40.0)])
    assert [a["code"] for a in normal] == ["ROUTINE_MONITORING", "KEEP_PLAN_READY"]
    weak = plan.recommend("HEATWAVE", [factor("rh_pct", 9.9)])
    assert "HUMID_HEAT_GUIDANCE" not in [a["code"] for a in weak]
    lowering = plan.recommend("HEATWAVE", [factor("rh_pct", -30.0, "decreases_risk")])
    assert "HUMID_HEAT_GUIDANCE" not in [a["code"] for a in lowering]


def test_the_mapping_is_deterministic(plan):
    factors = [factor("temp_deviation_c", 70.0), factor("solar_mj_m2", 11.0)]
    assert plan.recommend("HEATWAVE", factors) == plan.recommend("HEATWAVE", factors)


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda c: c["classes"].pop("NORMAL"), "classes must be exactly"),
        (lambda c: c["factor_rules"][0].update(feature="humidity"), "unknown feature"),
        (lambda c: c["factor_rules"][0].update(direction="up"), "direction"),
        (lambda c: c["classes"]["HEATWAVE"].append(c["classes"]["HEATWAVE"][0]), "duplicate"),
        (lambda c: c["classes"].update(NORMAL=[]), "no actions"),
    ],
)
def test_a_broken_actions_file_is_refused(tmp_path, edit, message):
    config = yaml.safe_load(ACTIONS_FILE.read_text(encoding="utf-8"))
    edit(config)
    path = tmp_path / "actions.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        ActionPlan.load(path)


def test_cli_migrate_and_users(settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setenv("NEW_PASSWORD", "a-long-enough-password")
    assert cli.main(["migrate"]) == 0
    assert "applied ['0001_initial']" in capsys.readouterr().out
    assert cli.main(["migrate"]) == 0
    assert "up to date" in capsys.readouterr().out

    args = ["create-user", "duty1", "--display-name", "Duty One", "--password-env", "NEW_PASSWORD"]
    assert cli.main(args) == 0
    assert cli.main(args) == 2  # already exists
    monkeypatch.setenv("SHORT", "short")
    assert cli.main(["set-password", "duty1", "--password-env", "SHORT"]) == 2
    monkeypatch.setenv("NEXT", "another-long-password")
    assert cli.main(["set-password", "duty1", "--password-env", "NEXT"]) == 0
    with Database(settings.sqlite_path).connect() as conn:
        user = Repository(conn).user_by_username("duty1")
    assert user["display_name"] == "Duty One"
    assert verify_password("another-long-password", user["password_hash"])


def test_the_committed_openapi_contract_is_current():
    """docs/api/openapi.json is generated; regenerate it with `heatwave-api openapi`."""
    committed = json.loads(cli.OPENAPI_PATH.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(cli.openapi_schema())), (
        "docs/api/openapi.json is stale: run `uv run heatwave-api openapi`"
    )
