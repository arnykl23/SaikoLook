"""手動 e2e スモーク（pytest 収集対象外: ファイル名が test_ で始まらない）.

fake source を注入し, 取得→分析→採点→保存→一覧→状態遷移→楽観ロック競合を
TestClient で end-to-end に確認する. 実 Gmail/LLM は叩かない.

オフライン・決定的に動かすため, app を import する前に環境変数で隔離 DB・
スケジューラ無効・起動時取り込み無効を設定する.
"""

import os
import tempfile

# ── app を import する前に隔離設定を効かせる（settings は import 時に読まれる）──
_TMP_DB = os.path.join(tempfile.gettempdir(), "SaikoLook_smoke.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["ANALYZER"] = "stub"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["INGEST_ON_STARTUP"] = "false"
os.environ["NOTIFIER"] = "log"
os.environ["SYNC_REMOTE_CHANGES"] = "false"
# secrets/gmail.env の値で env フォールバック源が作られないように明示的に空へ.
os.environ["GMAIL_ADDRESS"] = ""
os.environ["GMAIL_APP_PASSWORD"] = ""

from datetime import datetime, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AnalysisResult, EmailMessage  # noqa: E402


class CountingStubSource:
    """固定の2通を返す読み取り専用フェイクソース. address は MessageSource 互換用."""

    address = "smoke@example.com"

    def list_recent(self, limit: int = 10) -> list[EmailMessage]:
        return [
            EmailMessage(
                id="100", provider="gmail",
                subject="【至急】契約書の返信をお願いします 本日中",
                sender="boss@corp.com", is_unread=True,
                body_text="本日中にご返信ください。期限厳守でお願いします。",
                received_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
            EmailMessage(
                id="101", provider="gmail",
                subject="週末セールのお知らせ newsletter",
                sender="no-reply@shop.example", is_unread=False,
                body_text="お得なセール情報です。配信停止はこちら。",
                received_at=datetime(2026, 6, 8, tzinfo=timezone.utc),
            ),
        ]

    def close(self) -> None:
        pass


class CountingAnalyzer:
    """analyze 呼び出し回数を数える stub ラッパ（analyze-once の検証用）."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, email: EmailMessage) -> AnalysisResult:
        self.calls += 1
        urgent = "至急" in email.subject or "本日中" in email.subject
        return AnalysisResult(
            importance=5 if urgent else 2,
            task_weight="heavy" if urgent else "light",
            request_type="reply_required" if urgent else "info_only",
            is_promotional=not urgent,
            summary=email.subject,
            deadline=email.received_at if urgent else None,
            reason="スモーク用",
            analyzer="stub",
        )


def main() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        # fake source / counting analyzer を注入（実 Gmail・LLM を叩かない）.
        # マージ後の run_once は (source, acc) ペアを期待する.
        client.app.state.ingestion._sources_override = [
            (CountingStubSource(),
             {"id": "", "provider": "gmail", "address": "smoke@example.com"})
        ]
        analyzer = CountingAnalyzer()
        client.app.state.ingestion._analyzer = analyzer

        r = client.get("/health"); assert r.status_code == 200, r.text
        print("health:", r.json())

        r = client.post("/ingest"); assert r.status_code == 200, r.text
        counts = r.json(); print("ingest:", counts)
        assert counts["fetched"] == 2 and counts["inserted"] == 2
        assert analyzer.calls == 2  # 新着 2 件を分析

        r = client.get("/messages"); assert r.status_code == 200, r.text
        msgs = r.json(); print("messages:", len(msgs))
        assert len(msgs) == 2
        # トリアージ降順: 緊急契約(100)が先頭
        top = msgs[0]
        print("top:", top["message_id"], "importance=", top["analysis"]["importance"],
              "score=", round(top["triage_score"], 2), "state=", top["state"])
        assert top["message_id"] == "gmail:100"
        assert msgs[0]["triage_score"] >= msgs[1]["triage_score"]

        # 状態遷移（正常）
        mid = top["message_id"]; ver = top["version"]
        r = client.post(f"/messages/{mid}/state", json={"state": "in_progress", "version": ver})
        assert r.status_code == 200, r.text
        upd = r.json(); print("transition:", upd["state"], "version=", upd["version"])
        assert upd["state"] == "in_progress" and upd["version"] == ver + 1

        # 楽観ロック競合（古い version）
        r = client.post(f"/messages/{mid}/state", json={"state": "done", "version": ver})
        print("conflict status:", r.status_code)
        assert r.status_code == 409, r.text

        r = client.get("/emails"); assert r.status_code == 200, r.text
        print("emails(stored):", len(r.json()))

        # 再 ingest は冪等（state 保持: in_progress のまま）かつ
        # 分析は呼び直さない（analyze-once: calls が増えない）.
        r = client.post("/ingest"); assert r.status_code == 200
        print("re-ingest:", r.json(), "analyze_calls=", analyzer.calls)
        assert analyzer.calls == 2  # ★ 再取得しても analyze は増えない（従量課金の抑制）
        r = client.get("/messages/gmail:100"); assert r.status_code == 200
        print("after re-ingest state:", r.json()["state"])
        assert r.json()["state"] == "in_progress"

    print("E2E_SMOKE_OK")


if __name__ == "__main__":
    main()
