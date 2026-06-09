"""手動 e2e スモーク（pytest 収集対象外: ファイル名が test_ で始まらない）.

fake source を注入し, 取得→分析→採点→保存→一覧→状態遷移→楽観ロック競合を
TestClient で end-to-end に確認する. 実 Gmail/LLM は叩かない.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import EmailMessage


class FakeSource:
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


def main() -> None:
    with TestClient(app) as client:
        # fake source を注入（実 Gmail を叩かない）
        client.app.state.ingestion._source = FakeSource()

        r = client.get("/health"); assert r.status_code == 200, r.text
        print("health:", r.json())

        r = client.post("/ingest"); assert r.status_code == 200, r.text
        counts = r.json(); print("ingest:", counts)
        assert counts["fetched"] == 2 and counts["inserted"] == 2

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

        # 不正遷移 or 404
        r = client.get("/emails"); assert r.status_code == 200, r.text
        print("emails(stored):", len(r.json()))

        # 再 ingest は冪等（state 保持: in_progress のまま）
        r = client.post("/ingest"); assert r.status_code == 200
        r = client.get("/messages/gmail:100"); assert r.status_code == 200
        print("after re-ingest state:", r.json()["state"])
        assert r.json()["state"] == "in_progress"

    print("E2E_SMOKE_OK")


if __name__ == "__main__":
    main()
