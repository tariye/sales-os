"""Reusable Home Sentinel HTTP producer for the Info Analyzer event gateway."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 3.0
EVENT_ENDPOINT = "/events"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def stable_dedupe_key(local_event_id: str) -> str:
    return f"home-sentinel:{clean_text(local_event_id)}"


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


class HomeSentinelProducer:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = clean_text(base_url or os.environ.get("INFO_ANALYZER_BASE_URL"))
        self.api_key = clean_text(api_key or os.environ.get("INFO_ANALYZER_API_KEY"))
        self.timeout_seconds = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    def publish_camera_health(
        self,
        *,
        local_event_id: str,
        occurred_at: str,
        camera_name: str,
        status: str,
        metrics: dict[str, Any] | None = None,
    ) -> ProducerResult:
        payload = {
            "source_system_id": "sys_home_sentinel",
            "event_type": "camera_health_changed",
            "occurred_at": occurred_at,
            "dedupe_key": stable_dedupe_key(local_event_id),
            "source_ref": clean_text(local_event_id),
            "payload": {
                "camera_name": camera_name,
                "status": status,
            },
        }
        if metrics is not None:
            payload["payload"]["metrics"] = metrics
        return self._publish(payload)

    def publish_detection(
        self,
        *,
        local_event_id: str,
        occurred_at: str,
        camera_name: str,
        detection_type: str,
        detection_confidence: float,
        zone: str,
        expected: bool | None = None,
        image_ref: str | None = None,
    ) -> ProducerResult:
        payload = {
            "source_system_id": "sys_home_sentinel",
            "event_type": "detection_observed",
            "occurred_at": occurred_at,
            "dedupe_key": stable_dedupe_key(local_event_id),
            "source_ref": clean_text(local_event_id),
            "payload": {
                "detection_type": detection_type,
                "camera_name": camera_name,
                "detection_confidence": detection_confidence,
                "zone": zone,
            },
        }
        if expected is not None:
            payload["payload"]["expected"] = expected
        if image_ref:
            payload["payload"]["image_ref"] = image_ref
        return self._publish(payload)

    def _publish(self, payload: dict[str, Any]) -> ProducerResult:
        if not self.base_url:
            return ProducerResult(
                ok=False,
                delivered=False,
                status_code=None,
                event_id=None,
                signal_id=None,
                alert_id=None,
                error="INFO_ANALYZER_BASE_URL is not configured",
                response=None,
            )
        if not self.api_key:
            return ProducerResult(
                ok=False,
                delivered=False,
                status_code=None,
                event_id=None,
                signal_id=None,
                alert_id=None,
                error="INFO_ANALYZER_API_KEY is not configured",
                response=None,
            )
        url = self.base_url.rstrip("/") + EVENT_ENDPOINT
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
                return self._result_from_response(response.status, body)
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = {"error": exc.reason}
            return self._result_from_response(exc.code, body)
        except Exception as exc:
            return ProducerResult(
                ok=False,
                delivered=False,
                status_code=None,
                event_id=None,
                signal_id=None,
                alert_id=None,
                error=str(exc),
                response=None,
            )

    @staticmethod
    def _result_from_response(status_code: int, body: dict[str, Any]) -> ProducerResult:
        event = body.get("event") if isinstance(body, dict) else None
        effects = body.get("effects") if isinstance(body, dict) else []
        signal_id = body.get("signal_id") if isinstance(body, dict) else None
        alert_id = body.get("alert_id") if isinstance(body, dict) else None
        if isinstance(event, dict):
            event_id = clean_text(event.get("event_id")) or None
        else:
            event_id = None
        for effect in effects or []:
            if not isinstance(effect, dict):
                continue
            if not signal_id and effect.get("signal_id"):
                signal_id = effect.get("signal_id")
            if not alert_id and effect.get("alert_id"):
                alert_id = effect.get("alert_id")
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

