"""SlackApiSource の正規化テスト.

実 Slack API は叩かない. httpx.get / httpx.post をモックし,
conversations.list / conversations.history / users.info / auth.test の応答を
SlackApiSource が EmailMessage 列・検証結果へ正規化することを検証する.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.adapters.sources.slack_api import SlackApiSource
from app.models import EmailMessage
from app.ports.source import MessageSource


def _resp(data: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = data
    return m


# === Protocol 適合 ===

def test_satisfies_message_source_protocol() -> None:
    src = SlackApiSource("xoxb-test", "my-team")
    assert isinstance(src, MessageSource)


# === 正規化（チャンネルメッセージ）===

def test_list_recent_normalizes_channel_message() -> None:
    channels_resp = _resp(
        {"ok": True, "channels": [{"id": "C1", "name": "general", "is_member": True}]}
    )
    history_resp = _resp(
        {
            "ok": True,
            "messages": [{"ts": "1700000000.000100", "user": "U1", "text": "こんにちは\n世界"}],
        }
    )
    user_resp = _resp(
        {"ok": True, "user": {"name": "alice", "profile": {"real_name": "Alice"}}}
    )

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            return history_resp
        if url.endswith("users.info"):
            return user_resp
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        src = SlackApiSource("xoxb-test", "my-team")
        result = src.list_recent(limit=5)

    assert len(result) == 1
    m = result[0]
    assert isinstance(m, EmailMessage)
    assert m.id == "C1-1700000000.000100"
    assert m.provider == "slack"
    assert m.subject == "#general"
    assert m.sender == "Alice"
    assert m.to == ["#general"]
    assert m.is_unread is True
    assert m.received_at is not None
    assert m.snippet == "こんにちは 世界"  # 改行は空白へ畳む
    assert m.body_text == "こんにちは\n世界"


# === 複数チャンネル → 新しい順 ===

def test_results_sorted_newest_first() -> None:
    channels_resp = _resp(
        {
            "ok": True,
            "channels": [
                {"id": "C1", "name": "a", "is_member": True},
                {"id": "C2", "name": "b", "is_member": True},
            ],
        }
    )
    history_c1 = _resp({"ok": True, "messages": [{"ts": "100.0", "user": "", "text": "old"}]})
    history_c2 = _resp({"ok": True, "messages": [{"ts": "200.0", "user": "", "text": "new"}]})

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            return history_c1 if params["channel"] == "C1" else history_c2
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        result = SlackApiSource("xoxb-test", "my-team").list_recent(limit=10)

    assert [m.snippet for m in result] == ["new", "old"]


# === システムメッセージ（subtype）は除外 ===

def test_subtype_messages_excluded() -> None:
    channels_resp = _resp(
        {"ok": True, "channels": [{"id": "C1", "name": "general", "is_member": True}]}
    )
    history_resp = _resp(
        {
            "ok": True,
            "messages": [
                {"ts": "1.0", "user": "U1", "text": "joined", "subtype": "channel_join"},
                {"ts": "2.0", "user": "U1", "text": "hello"},
            ],
        }
    )
    user_resp = _resp({"ok": True, "user": {"name": "alice", "profile": {}}})

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            return history_resp
        if url.endswith("users.info"):
            return user_resp
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        result = SlackApiSource("xoxb-test", "my-team").list_recent()

    assert len(result) == 1
    assert result[0].snippet == "hello"


# === 未参加チャンネル(is_member=False)は除外 ===

def test_non_member_channels_excluded() -> None:
    channels_resp = _resp(
        {
            "ok": True,
            "channels": [
                {"id": "C1", "name": "joined", "is_member": True},
                {"id": "C2", "name": "not-joined", "is_member": False},
            ],
        }
    )
    history_resp = _resp({"ok": True, "messages": [{"ts": "1.0", "user": "", "text": "hi"}]})
    requested_channels: list[str] = []

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            requested_channels.append(params["channel"])
            return history_resp
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        SlackApiSource("xoxb-test", "my-team").list_recent()

    assert requested_channels == ["C1"]


# === DM チャンネルの subject ===

def test_dm_channel_label() -> None:
    channels_resp = _resp({"ok": True, "channels": [{"id": "D1", "is_im": True}]})
    history_resp = _resp({"ok": True, "messages": [{"ts": "1.0", "user": "U1", "text": "hi"}]})
    user_resp = _resp({"ok": True, "user": {"name": "bob", "profile": {"real_name": "Bob"}}})

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            return history_resp
        if url.endswith("users.info"):
            return user_resp
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        result = SlackApiSource("xoxb-test", "my-team").list_recent()

    assert result[0].subject == "DM: Bob"


# === snippet 長さ上限 ===

def test_snippet_truncated_to_limit() -> None:
    long_text = "あ" * 500
    channels_resp = _resp(
        {"ok": True, "channels": [{"id": "C1", "name": "general", "is_member": True}]}
    )
    history_resp = _resp({"ok": True, "messages": [{"ts": "1.0", "user": "", "text": long_text}]})

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            return history_resp
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        result = SlackApiSource("xoxb-test", "my-team").list_recent()

    assert len(result[0].snippet) == 120


# === body_text の文字数上限 ===

def test_body_text_truncated_to_max_chars() -> None:
    long_text = "x" * 9000
    channels_resp = _resp(
        {"ok": True, "channels": [{"id": "C1", "name": "general", "is_member": True}]}
    )
    history_resp = _resp({"ok": True, "messages": [{"ts": "1.0", "user": "", "text": long_text}]})

    def get_side_effect(url: str, params: dict | None = None, **kwargs):
        if url.endswith("conversations.list"):
            return channels_resp
        if url.endswith("conversations.history"):
            return history_resp
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.slack_api.httpx.get", side_effect=get_side_effect):
        src = SlackApiSource("xoxb-test", "my-team", max_body_chars=100)
        result = src.list_recent()

    assert len(result[0].body_text or "") == 100


# === チャンネル無し → 空 ===

def test_no_channels_returns_empty() -> None:
    channels_resp = _resp({"ok": True, "channels": []})
    with patch("app.adapters.sources.slack_api.httpx.get", return_value=channels_resp):
        result = SlackApiSource("xoxb-test", "my-team").list_recent()
    assert result == []


# === 認証情報未設定 → RuntimeError ===

def test_missing_token_raises() -> None:
    src = SlackApiSource("", "my-team")
    with pytest.raises(RuntimeError):
        src.list_recent()


# === verify_credentials ===

def test_verify_credentials_success() -> None:
    resp = _resp({"ok": True, "user_id": "U1", "team": "T1"})
    with patch("app.adapters.sources.slack_api.httpx.post", return_value=resp):
        SlackApiSource.verify_credentials("xoxb-test")


def test_verify_credentials_failure() -> None:
    resp = _resp({"ok": False, "error": "invalid_auth"})
    with patch("app.adapters.sources.slack_api.httpx.post", return_value=resp):
        with pytest.raises(RuntimeError):
            SlackApiSource.verify_credentials("xoxb-bad")


# === close は no-op（例外を出さない）===

def test_close_is_noop() -> None:
    src = SlackApiSource("xoxb-test", "my-team")
    assert src.close() is None
