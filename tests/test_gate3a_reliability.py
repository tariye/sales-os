from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
import unittest

from core_alerts import respond_to_alert, sync_alert_queue
from core_database import connect as core_connect
from core_delivery import (
    record_alert_acknowledgment,
    record_alert_presentation,
    record_delivery_result,
    request_notification,
)
from core_migrations import initialize_core_migrations
from core_events import create_event
from core_observations import event_payload_from_observation, ingest_observation, record_source_observation
from core_operations import claim_operation, complete_attempt
from core_shared_access import get_event_trace


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DB = ROOT / "data" / "info_analyzer.db"


class Gate3AReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def db_path(self, name: str = "gate3a.db") -> Path:
        return self.root / name

    def copy_canonical(self, name: str = "canonical-copy.db") -> Path:
        db = self.db_path(name)
        shutil.copy2(CANONICAL_DB, db)
        initialize_core_migrations(db)
        return db

    def fresh_db(self, name: str = "fresh.db") -> Path:
        db = self.db_path(name)
        initialize_core_migrations(db)
        return db

    def observation_payload(self, **overrides):
        payload = {
            "source_system_id": "sys_innbank",
            "source_connection_id": "conn-wells",
            "account_external_id": "acct-checking",
            "source_name": "Wells Fargo checking",
            "observation_type": "financial_inflow",
            "source_transaction_id": "txn-001",
            "economic_inflow_key": "econ-payday-001",
            "observation_status": "pending",
            "amount_cents": 108414,
            "currency": "USD",
            "account_name": "Wells Fargo checking",
            "classification": "payroll",
            "classification_confidence": 0.99,
            "observed_at": "2026-09-13T12:00:00.000Z",
            "effective_date": "2026-09-13",
        }
        payload.update(overrides)
        return payload

    def seed_alert(self, conn, *, signal_id: str = "SIG-GATE3A") -> str:
        conn.execute(
            """
            INSERT INTO core_signals (
                signal_id, owner_system_id, signal_type, title, summary,
                priority, confidence, actionability_score, status,
                rationale, recommended_action, detected_at, metadata_json
            ) VALUES (?, 'sys_info_analyzer', 'gate3a_test', 'Gate 3A alert',
                      'Gate 3A alert summary', 'P0', 0.95, 0.90, 'new',
                      'test rationale', 'test action', '2026-09-13T12:00:00.000Z', '{}')
            """,
            (signal_id,),
        )
        sync_alert_queue(conn, now="2026-09-13T12:01:00.000Z")
        row = conn.execute("SELECT alert_id FROM core_alerts WHERE signal_id=?", (signal_id,)).fetchone()
        return row["alert_id"]

    def test_migration_repeatability_and_legacy_preservation_on_canonical_copy(self) -> None:
        db = self.copy_canonical()
        with core_connect(db) as conn:
            before = {
                "actions": conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
                "live_signals": conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0],
                "entries": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            }
            versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
            self.assertEqual(versions, [1, 2, 3, 4])
            self.assertIn("core_source_observations", {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()})
            self.assertIn("core_captures", {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()})
        self.assertEqual(initialize_core_migrations(db), [])
        with core_connect(db) as conn:
            after = {
                "actions": conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
                "live_signals": conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0],
                "entries": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            }
        self.assertEqual(before, after)

    def test_same_id_pending_posted_correction_and_exact_retry(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            pending = record_source_observation(conn, self.observation_payload(), worker_id="w1", now="2026-09-13T12:00:00.000Z")
            retry = record_source_observation(conn, self.observation_payload(), worker_id="w1", now="2026-09-13T12:01:00.000Z")
            correction = record_source_observation(conn, self.observation_payload(amount_cents=108514), worker_id="w1", now="2026-09-13T12:02:00.000Z")
            posted = record_source_observation(
                conn,
                self.observation_payload(observation_status="posted", amount_cents=108514, posted_at="2026-09-13T13:00:00.000Z"),
                worker_id="w1",
                now="2026-09-13T13:01:00.000Z",
            )
            conn.commit()

            self.assertEqual(retry["observation"]["observation_id"], pending["observation"]["observation_id"])
            self.assertNotEqual(correction["observation"]["observation_id"], pending["observation"]["observation_id"])
            self.assertEqual(correction["observation"]["supersedes_observation_id"], pending["observation"]["observation_id"])
            self.assertEqual(posted["observation"]["pending_observation_id"], correction["observation"]["observation_id"])
            self.assertEqual(posted["observation"]["observation_status"], "posted")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 0)

    def test_changed_ids_out_of_order_and_uncertain_matches_do_not_regress(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            posted = record_source_observation(
                conn,
                self.observation_payload(source_transaction_id="posted-id", observation_status="posted", posted_at="2026-09-13T13:00:00.000Z"),
                worker_id="w1",
                now="2026-09-13T13:01:00.000Z",
            )
            late_pending = record_source_observation(
                conn,
                self.observation_payload(source_transaction_id="pending-id", observation_status="pending"),
                worker_id="w1",
                now="2026-09-13T13:02:00.000Z",
            )
            conn.commit()
            self.assertEqual(late_pending["observation"]["posted_observation_id"], posted["observation"]["observation_id"])
            self.assertEqual(late_pending["observation"]["match_state"], "probable_match")
            current_posted = conn.execute("SELECT COUNT(*) FROM core_source_observations WHERE observation_status='posted'").fetchone()[0]
            self.assertEqual(current_posted, 1)

    def test_operation_attempt_ownership_reclaim_and_hash_conflict(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            first = claim_operation(
                conn,
                operation_type="ingest_observation",
                operation_key="obs-1:event",
                request_payload={"v": 1},
                worker_id="worker-a",
                immutable_payload=True,
                now="2026-09-13T12:00:00.000Z",
                lease_seconds=60,
            )
            with self.assertRaises(RuntimeError):
                claim_operation(
                    conn,
                    operation_type="ingest_observation",
                    operation_key="obs-1:event",
                    request_payload={"v": 1},
                    worker_id="worker-b",
                    immutable_payload=True,
                    now="2026-09-13T12:00:30.000Z",
                    lease_seconds=60,
                )
            reclaimed = claim_operation(
                conn,
                operation_type="ingest_observation",
                operation_key="obs-1:event",
                request_payload={"v": 1},
                worker_id="worker-b",
                immutable_payload=True,
                now="2026-09-13T12:02:00.000Z",
                lease_seconds=60,
            )
            self.assertNotEqual(first["attempt"]["attempt_id"], reclaimed["attempt"]["attempt_id"])
            with self.assertRaises(RuntimeError):
                complete_attempt(
                    conn,
                    operation_id=reclaimed["operation"]["operation_id"],
                    attempt_id=reclaimed["attempt"]["attempt_id"],
                    worker_id="worker-a",
                    status="succeeded",
                )
            complete_attempt(
                conn,
                operation_id=reclaimed["operation"]["operation_id"],
                attempt_id=reclaimed["attempt"]["attempt_id"],
                worker_id="worker-b",
                status="succeeded",
                now="2026-09-13T12:02:30.000Z",
            )
            exact = claim_operation(
                conn,
                operation_type="ingest_observation",
                operation_key="obs-1:event",
                request_payload={"v": 1},
                worker_id="worker-b",
                immutable_payload=True,
                now="2026-09-13T12:03:00.000Z",
            )
            self.assertTrue(exact["idempotent"])
            with self.assertRaises(ValueError):
                claim_operation(
                    conn,
                    operation_type="ingest_observation",
                    operation_key="obs-1:event",
                    request_payload={"v": 2},
                    worker_id="worker-b",
                    immutable_payload=True,
                    now="2026-09-13T12:04:00.000Z",
                )

    def test_ingestion_dispatch_recovery_and_no_duplicate_events_signals_alerts(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            obs = record_source_observation(
                conn,
                self.observation_payload(observation_status="posted", posted_at="2026-09-13T13:00:00.000Z"),
                worker_id="observer",
                now="2026-09-13T13:01:00.000Z",
            )
            result = ingest_observation(conn, obs["observation"]["observation_id"], worker_id="ingest", now="2026-09-13T13:02:00.000Z")
            repeat = ingest_observation(conn, obs["observation"]["observation_id"], worker_id="ingest", now="2026-09-13T13:03:00.000Z")
            conn.commit()
            self.assertTrue(result["event_id"].startswith("EVT-"))
            self.assertTrue(repeat["idempotent"])
            self.assertEqual(repeat["event_id"], result["event_id"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_ingestion_results WHERE status='succeeded'").fetchone()[0], 1)
            alert = conn.execute("SELECT presented_at FROM core_alerts LIMIT 1").fetchone()
            self.assertIsNone(alert["presented_at"])

    def test_ingestion_recovers_after_event_created_before_dispatch_result(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            obs = record_source_observation(
                conn,
                self.observation_payload(observation_status="posted", posted_at="2026-09-13T13:00:00.000Z"),
                worker_id="observer",
                now="2026-09-13T13:01:00.000Z",
            )
            # Simulate a crash after the event insert but before dispatch/result recording.
            created = create_event(conn, event_payload_from_observation(obs["observation"]))
            self.assertTrue(created["created"])
            conn.commit()

            recovered = ingest_observation(
                conn,
                obs["observation"]["observation_id"],
                worker_id="ingest",
                now="2026-09-13T13:02:00.000Z",
            )
            conn.commit()

            self.assertFalse(recovered["created"])
            self.assertTrue(recovered["duplicate"])
            self.assertEqual(recovered["event_id"], created["event"]["event_id"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_signals").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_alerts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_ingestion_results WHERE status='succeeded'").fetchone()[0], 1)

    def test_exact_retry_of_older_observation_after_newer_version_does_not_regress(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            original = record_source_observation(
                conn,
                self.observation_payload(amount_cents=108414),
                worker_id="observer",
                now="2026-09-13T12:00:00.000Z",
            )
            correction = record_source_observation(
                conn,
                self.observation_payload(amount_cents=108514),
                worker_id="observer",
                now="2026-09-13T12:02:00.000Z",
            )
            replay = record_source_observation(
                conn,
                self.observation_payload(amount_cents=108414),
                worker_id="observer",
                now="2026-09-13T12:05:00.000Z",
            )
            conn.commit()

            latest = conn.execute(
                """
                SELECT *
                FROM core_source_observations
                WHERE source_system_id='sys_innbank'
                  AND source_connection_id='conn-wells'
                  AND account_external_id='acct-checking'
                  AND source_transaction_id='txn-001'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            self.assertEqual(replay["observation"]["observation_id"], original["observation"]["observation_id"])
            self.assertEqual(latest["observation_id"], correction["observation"]["observation_id"])
            self.assertEqual(latest["amount_cents"], 108514)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM core_source_observations").fetchone()[0], 2)

    def test_notification_delivery_presentation_ack_and_cross_case_validation(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            alert_id = self.seed_alert(conn, signal_id="SIG-DELIVERY-1")
            request = request_notification(conn, alert_id=alert_id, channel="mcp", requested_by="test")
            with self.assertRaises(ValueError):
                record_delivery_result(conn, notification_request_id=request["request"]["notification_request_id"], provider_status="delivered")
            unknown = record_delivery_result(conn, notification_request_id=request["request"]["notification_request_id"], provider_status="unknown")
            self.assertEqual(unknown["operation"]["status"], "pending_reconciliation")

            request2 = request_notification(conn, alert_id=alert_id, channel="command_center", requested_by="test")
            delivered = record_delivery_result(
                conn,
                notification_request_id=request2["request"]["notification_request_id"],
                provider_status="delivered",
                trusted_evidence_type="provider_receipt",
                trusted_evidence_ref="receipt-1",
            )
            presentation = record_alert_presentation(conn, alert_id=alert_id, presented_by="ui", presentation_surface="command_center", delivery_result_id=delivered["delivery"]["delivery_result_id"])
            self.assertTrue(presentation["presentation_id"].startswith("PRS-"))
            conn.commit()

            response = respond_to_alert(db, alert_id, {"response": "acknowledge", "decided_by": "human", "_auth_context": "api_key", "_acknowledged_by": "authenticated_api_client"})
            ack_count = conn.execute("SELECT COUNT(*) FROM core_alert_acknowledgments WHERE alert_id=?", (alert_id,)).fetchone()[0]
            self.assertEqual(ack_count, 1)

            other_alert = self.seed_alert(conn, signal_id="SIG-DELIVERY-2")
            with self.assertRaises(ValueError):
                record_alert_acknowledgment(
                    conn,
                    alert_id=other_alert,
                    acknowledged_by="forged",
                    auth_context="api_key",
                    decision_id=response["decision"]["decision_id"],
                )
            with self.assertRaises(ValueError):
                record_alert_acknowledgment(conn, alert_id=other_alert, acknowledged_by="forged", auth_context="")
            conn.commit()

    def test_event_trace_boundaries_and_schema_v2_compatibility(self) -> None:
        db = self.fresh_db()
        with core_connect(db) as conn:
            obs = record_source_observation(
                conn,
                self.observation_payload(observation_status="posted", posted_at="2026-09-13T13:00:00.000Z"),
                worker_id="observer",
                now="2026-09-13T13:01:00.000Z",
            )
            result = ingest_observation(conn, obs["observation"]["observation_id"], worker_id="ingest", now="2026-09-13T13:02:00.000Z")
            conn.commit()
        trace = get_event_trace(db, result["event_id"])
        self.assertEqual(trace["boundaries"]["observed"], "recorded")
        self.assertEqual(trace["boundaries"]["ingested"], "recorded")
        self.assertEqual(trace["boundaries"]["queued"], "recorded")
        self.assertEqual(trace["boundaries"]["delivered"], "not_recorded")
        self.assertEqual(trace["delivery_status"], "delivery_unknown")
        self.assertEqual(trace["legacy_unverified"]["core_alerts_presented_at"], [])

        schema_v2 = self.fresh_db("schema-v2.db")
        with core_connect(schema_v2) as conn:
            for table in [
                "core_alert_acknowledgments",
                "core_alert_presentations",
                "core_notification_delivery_results",
                "core_notification_requests",
                "core_ingestion_results",
                "core_source_observations",
                "core_operation_attempts",
                "core_operations",
            ]:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(
                """
                INSERT INTO core_events (
                    event_id, source_system_id, event_type, occurred_at,
                    received_at, priority, confidence, processing_status,
                    payload_json, created_at
                ) VALUES ('EVT-SCHEMA-V2', 'sys_info_analyzer', 'test', '2026-09-13T12:00:00.000Z',
                          '2026-09-13T12:00:00.000Z', 'P2', 1.0, 'processed', '{}', '2026-09-13T12:00:00.000Z')
                """
            )
            conn.commit()
        legacy_trace = get_event_trace(schema_v2, "EVT-SCHEMA-V2")
        self.assertEqual(legacy_trace["boundaries"]["observed"], "not_recorded")
        self.assertIn("Gate 3A reliability tables are not fully initialized", legacy_trace["coverage"]["limitations"][0])


if __name__ == "__main__":
    unittest.main()
