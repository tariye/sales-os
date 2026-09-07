"""Shared producer client plus Groove, Sales, and Private Equity conveniences."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def stable_dedupe_key(system_id: str, local_event_id: str) -> str:
    return f"{system_id}:{clean_text(local_event_id)}"


@dataclass
class ProducerResult:
    ok: bool
    delivered: bool
    status_code: int | None
    event_id: str | None
    signal_id: str | None
    alert_id: str | None
    error: str | None
    response: dict[str, Any] | None


class SharedEventProducer:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = clean_text(base_url or os.environ.get("INFO_ANALYZER_BASE_URL"))
        self.api_key = clean_text(api_key or os.environ.get("INFO_ANALYZER_API_KEY"))
        self.timeout_seconds = float(timeout_seconds or 5.0)

    def publish(
        self,
        *,
        system_id: str,
        event_type: str,
        local_event_id: str,
        payload: dict[str, Any],
        priority: str = "P2",
        confidence: float = 1.0,
        occurred_at: str | None = None,
    ) -> ProducerResult:
        if not self.base_url:
            return ProducerResult(False, False, None, None, None, None, "INFO_ANALYZER_BASE_URL is not configured", None)
        if not self.api_key:
            return ProducerResult(False, False, None, None, None, None, "INFO_ANALYZER_API_KEY is not configured", None)
        body = {
            "source_system_id": system_id,
            "event_type": event_type,
            "occurred_at": occurred_at or utc_now(),
            "dedupe_key": stable_dedupe_key(system_id, local_event_id),
            "source_ref": clean_text(local_event_id),
            "priority": priority,
            "confidence": confidence,
            "payload": payload,
        }
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/events",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return self._from_response(response.status, json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            try:
                response_body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                response_body = {"error": exc.reason}
            return self._from_response(exc.code, response_body)
        except Exception as exc:
            return ProducerResult(False, False, None, None, None, None, str(exc), None)

    @staticmethod
    def _from_response(status_code: int, body: dict[str, Any]) -> ProducerResult:
        event = body.get("event") if isinstance(body, dict) else None
        signal_id = body.get("signal_id") if isinstance(body, dict) else None
        alert_id = body.get("alert_id") if isinstance(body, dict) else None
        if isinstance(event, dict):
            event_id = clean_text(event.get("event_id")) or None
        else:
            event_id = None
        for effect in body.get("effects") or []:
            if not isinstance(effect, dict):
                continue
            signal_id = signal_id or effect.get("signal_id")
            alert_id = alert_id or effect.get("alert_id")
        ok = status_code in {200, 201}
        return ProducerResult(
            ok=ok,
            delivered=ok,
            status_code=status_code,
            event_id=event_id,
            signal_id=clean_text(signal_id) or None,
            alert_id=clean_text(alert_id) or None,
            error=None if ok else body.get("error") if isinstance(body, dict) else "request failed",
            response=body,
        )


class GrooveProducer(SharedEventProducer):
    def project_blocked(self, local_event_id: str, project_name: str, blocker: str, next_action: str) -> ProducerResult:
        return self.publish(
            system_id="sys_groove",
            event_type="project_blocked",
            local_event_id=local_event_id,
            priority="P1",
            payload={
                "project_name": project_name,
                "blocker": blocker,
                "next_action": next_action,
            },
        )

    def release_milestone_reached(self, local_event_id: str, project_name: str, milestone: str) -> ProducerResult:
        return self.publish(
            system_id="sys_groove",
            event_type="release_milestone_reached",
            local_event_id=local_event_id,
            payload={
                "project_name": project_name,
                "milestone": milestone,
            },
        )


class SalesProducer(SharedEventProducer):
    def followup_due(
        self,
        local_event_id: str,
        opportunity_name: str,
        next_action: str,
        context: str = "",
    ) -> ProducerResult:
        return self.publish(
            system_id="sys_sales",
            event_type="followup_due",
            local_event_id=local_event_id,
            priority="P1",
            payload={
                "opportunity_name": opportunity_name,
                "next_action": next_action,
                "context": context,
            },
        )

    def deal_stage_changed(self, local_event_id: str, opportunity_name: str, stage: str) -> ProducerResult:
        return self.publish(
            system_id="sys_sales",
            event_type="deal_stage_changed",
            local_event_id=local_event_id,
            payload={
                "opportunity_name": opportunity_name,
                "stage": stage,
            },
        )


class PrivateEquityProducer(SharedEventProducer):
    def thesis_changed(
        self,
        local_event_id: str,
        asset_name: str,
        change: str,
        materiality: float,
        evidence: str = "",
    ) -> ProducerResult:
        return self.publish(
            system_id="sys_private_equity",
            event_type="thesis_changed",
            local_event_id=local_event_id,
            payload={
                "asset_name": asset_name,
                "change": change,
                "materiality": materiality,
                "evidence": evidence,
            },
        )

    def risk_limit_breached(self, local_event_id: str, asset_name: str, rule: str) -> ProducerResult:
        return self.publish(
            system_id="sys_private_equity",
            event_type="risk_limit_breached",
            local_event_id=local_event_id,
            priority="P0",
            payload={
                "asset_name": asset_name,
                "rule": rule,
            },
        )
