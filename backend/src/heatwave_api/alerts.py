"""Alert creation, editing and issuing (Part 07 §3.3-3.4, §6).

One alert record moves through an explicit status field, never through separate
endpoints ("Save as Draft" and "Issue Warning" write the same record):

    DRAFT <-> READY --> ISSUED          (DRAFT --> ISSUED directly is allowed too)

ISSUED is final: an issued alert cannot be edited or un-issued. Reaching ISSUED, and
only that, dispatches the alert to its channels. Each channel's outcome is committed
on its own (READY -> PENDING -> NOTIFIED | FAILED), so a failed channel is visible on
the record and in the response, not hidden behind an overall "success".

Idempotency: every create carries a client-generated ``client_request_id``. Replaying
it with the same body returns the original alert (HTTP 200, meta.idempotent_replay);
with a different body it is a 409. A new alert always needs a new id.
"""

import hashlib
import json
import logging
from datetime import datetime

from heatwave_api.db import utcnow
from heatwave_api.db.repository import Repository
from heatwave_api.errors import Conflict, NotFound, ValidationFailed
from heatwave_api.predictions import resolve_region
from heatwave_api.reference import CHANNEL_LABELS, DELIVERY_STATUSES
from heatwave_api.schemas import AlertCreate, AlertUpdate
from heatwave_api.services import Services
from heatwave_api.weather import LOCAL_TZ
from heatwave_ml.features import RISK_CLASS_LABELS

log = logging.getLogger(__name__)

ISSUED = "ISSUED"
CODE_PREFIX = "HW"


def alert_code(year: int, seq: int) -> str:
    """HW-2026-0007: prefix, year, sequence within the year (the UI mockup's pattern)."""
    return f"{CODE_PREFIX}-{year}-{seq:04d}"


def _fingerprint(body: AlertCreate) -> str:
    content = body.model_dump(mode="json", exclude={"client_request_id"})
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _check_prediction(repo: Repository, prediction_id: str | None, region_id: str) -> None:
    if prediction_id is None:
        return
    run = repo.run_summaries([prediction_id]).get(prediction_id)
    if run is None:
        raise ValidationFailed(f"No prediction '{prediction_id}'.", code="UNKNOWN_PREDICTION")
    if run["region_id"] != region_id:
        raise ValidationFailed(
            f"Prediction '{prediction_id}' is for region '{run['region_id']}', not '{region_id}'.",
            code="PREDICTION_REGION_MISMATCH",
        )


def create_alert(
    services: Services, repo: Repository, user: dict, body: AlertCreate
) -> tuple[dict, bool, list[str]]:
    """Returns (alert payload, created, warnings). created=False for a replay."""
    resolve_region(services, body.region_id)
    fingerprint = _fingerprint(body)
    now = utcnow()
    with repo.transaction():
        existing = repo.alert(client_request_id=str(body.client_request_id))
        if existing is not None:
            if existing["request_fingerprint"] != fingerprint:
                raise Conflict(
                    "This client_request_id was already used for a different alert. "
                    "Generate a new one for a new alert.",
                    code="IDEMPOTENCY_CONFLICT",
                    details={"alert_id": existing["code"]},
                )
            return alert_payload(services, existing), False, []
        _check_prediction(repo, body.prediction_id, body.region_id)
        year = datetime.now(LOCAL_TZ).year
        seq = repo.next_alert_seq(year)
        issued = body.status == ISSUED
        alert_id = repo.insert_alert(
            {
                "code": alert_code(year, seq),
                "year": year,
                "seq": seq,
                "region_id": body.region_id,
                "severity": body.severity,
                "status": body.status,
                "message": body.message,
                "prediction_id": body.prediction_id,
                "client_request_id": str(body.client_request_id),
                "request_fingerprint": fingerprint,
                "created_by": user["id"],
                "created_at": now,
                "updated_at": now,
                "issued_at": now if issued else None,
                "issued_by": user["id"] if issued else None,
            }
        )
        repo.replace_channels(alert_id, body.channels, "PENDING" if issued else "READY", now)
        code = alert_code(year, seq)
    log.info(
        "alert created",
        extra={"alert": code, "status": body.status, "region_id": body.region_id},
    )
    warnings = dispatch(services, repo, code) if issued else []
    return alert_payload(services, repo.alert(code=code)), True, warnings


def update_alert(
    services: Services, repo: Repository, user: dict, code: str, body: AlertUpdate
) -> tuple[dict, list[str]]:
    changes = body.model_dump(exclude_unset=True)
    now = utcnow()
    with repo.transaction():
        alert = repo.alert(code=code)
        if alert is None:
            raise NotFound(f"No alert '{code}'.", code="ALERT_NOT_FOUND")
        if alert["status"] == ISSUED:
            raise Conflict(
                f"Alert {code} has been issued and can no longer be changed.",
                code="ALERT_ALREADY_ISSUED",
            )
        region_id = changes.get("region_id", alert["region_id"])
        if "region_id" in changes:
            resolve_region(services, region_id)
        if "prediction_id" in changes or "region_id" in changes:
            _check_prediction(repo, changes.get("prediction_id", alert["prediction_id"]), region_id)
        channels = changes.pop("channels", None)
        issuing = changes.get("status") == ISSUED
        if issuing:
            changes |= {"issued_at": now, "issued_by": user["id"]}
        repo.update_alert(alert["id"], changes | {"updated_at": now})
        if channels is not None:
            repo.replace_channels(alert["id"], channels, "READY", now)
        if issuing:
            repo.set_channels_status(alert["id"], "PENDING", now)
    log.info("alert updated", extra={"alert": code, "fields": sorted(body.model_fields_set)})
    warnings = dispatch(services, repo, code) if issuing else []
    return alert_payload(services, repo.alert(code=code)), warnings


def dispatch(services: Services, repo: Repository, code: str) -> list[str]:
    """Deliver an issued alert to each of its channels, recording each outcome as it
    happens. Never raises for a channel failure; returns one warning per failure.

    Synchronous for now: the mock is instant, and the response then carries the real
    per-channel status. Part 09 decides whether live providers move to a background
    task; the frontend polls GET /alerts/{id} either way (Part 13).
    """
    alert = repo.alert(code=code)
    warnings = []
    for channel in alert["channels"]:
        name = channel["channel"]
        try:
            result = services.notifier.send(alert, name)
            status, error = ("NOTIFIED", None) if result.delivered else ("FAILED", result.error)
        except Exception as exc:  # one channel's crash must not stop the others
            log.exception("delivery crashed", extra={"alert": code, "channel": name})
            status, error = "FAILED", f"Delivery error ({type(exc).__name__})"
        repo.record_delivery(alert["id"], name, status, error)
        log.info(
            "alert delivery",
            extra={"alert": code, "channel": name, "delivery_status": status, "error": error},
        )
        if status == "FAILED":
            warnings.append(f"{CHANNEL_LABELS[name]}: delivery failed ({error})")
    return warnings


def _user(row: dict | None) -> dict | None:
    return {"username": row["username"], "display_name": row["display_name"]} if row else None


def alert_payload(services: Services, alert: dict) -> dict:
    summary = dict.fromkeys(DELIVERY_STATUSES, 0)
    for c in alert["channels"]:
        summary[c["status"]] += 1
    return {
        "alert_id": alert["code"],
        "status": alert["status"],
        "severity": alert["severity"],
        "severity_label": RISK_CLASS_LABELS[alert["severity"]],
        "region": services.reference.display_region(alert["region_id"]),
        "message": alert["message"],
        "channels": [
            {
                "channel": c["channel"],
                "label": CHANNEL_LABELS[c["channel"]],
                "status": c["status"],
                "attempts": c["attempts"],
                "last_error": c["last_error"],
                "updated_at": c["updated_at"],
            }
            for c in alert["channels"]
        ],
        "delivery_summary": summary,
        "prediction_id": alert["prediction_id"],
        "created_at": alert["created_at"],
        "created_by": _user(alert["creator"]),
        "updated_at": alert["updated_at"],
        "issued_at": alert["issued_at"],
        "issued_by": _user(alert["issuer"]),
    }
