"""GithubApiSource の正規化テスト.

実 GitHub API は叩かない. httpx.get をモックし,
GET /notifications / PR・Issue 本体 / コメント の応答を
GithubApiSource が EmailMessage 列へ正規化することを検証する.
"""

from datetime import timezone
from unittest.mock import MagicMock, call, patch

import pytest

from app.adapters.sources.github_api import GithubApiSource
from app.models import EmailMessage
from app.ports.source import MessageSource

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _resp(data, *, status_code: int = 200) -> MagicMock:
    """httpx.Response のミニマムなモックを返す."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = data
    return m


def _make_notification(
    nid: str = "1",
    reason: str = "review_requested",
    title: str = "Fix login bug",
    subject_url: str = "https://api.github.com/repos/org/repo/pulls/42",
    latest_comment_url: str | None = None,
    updated_at: str = "2024-01-01T00:00:00Z",
    unread: bool = True,
    full_name: str = "org/repo",
) -> dict:
    return {
        "id": nid,
        "reason": reason,
        "unread": unread,
        "updated_at": updated_at,
        "subject": {
            "title": title,
            "url": subject_url,
            "latest_comment_url": latest_comment_url,
        },
        "repository": {"full_name": full_name},
    }


def _make_pr_body(login: str = "alice", body: str = "PR body text") -> dict:
    return {
        "user": {"login": login},
        "html_url": "https://github.com/org/repo/pull/42",
        "body": body,
    }


def _make_comment_body(body: str = "Comment text") -> dict:
    return {"body": body}


def _account_repo_mock() -> MagicMock:
    m = MagicMock()
    m.set_auth_status = MagicMock()
    return m


# ---------------------------------------------------------------------------
# 1. MessageSource Protocol 適合
# ---------------------------------------------------------------------------

def test_satisfies_message_source_protocol() -> None:
    src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
    assert isinstance(src, MessageSource)


# ---------------------------------------------------------------------------
# 2. 6種 reason の正規化（subject プレフィックス）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reason, expected_prefix", [
    ("review_requested", "[review依頼]"),
    ("mention",          "[メンション]"),
    ("comment",          "[コメント]"),
    ("assign",           "[アサイン]"),
    ("author",           "[自分のPR/Issue]"),
    ("team_mention",     "[チームメンション]"),
])
def test_reason_subject_prefix(reason: str, expected_prefix: str) -> None:
    notif = _make_notification(reason=reason, title="Some title")
    pr_body = _make_pr_body()

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        # subject.url または コメント URL
        return _resp(pr_body)

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    assert len(result) == 1
    assert result[0].subject.startswith(expected_prefix)
    assert "Some title" in result[0].subject


# ---------------------------------------------------------------------------
# 3. 対象外 reason は除外される
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reason", ["subscribed", "ci_activity", "state_change", "security_alert"])
def test_uninterested_reason_excluded(reason: str) -> None:
    notif = _make_notification(reason=reason)

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        return _resp(_make_pr_body())

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    assert result == []


# ---------------------------------------------------------------------------
# 4. 本文・送信者の追加取得が EmailMessage に反映される
# ---------------------------------------------------------------------------

def test_body_and_sender_fetched() -> None:
    subject_url = "https://api.github.com/repos/org/repo/pulls/42"
    comment_url = "https://api.github.com/repos/org/repo/issues/comments/99"
    notif = _make_notification(
        subject_url=subject_url,
        latest_comment_url=comment_url,
    )

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        if url == subject_url:
            return _resp({"user": {"login": "bob"}, "html_url": "https://...", "body": "PR body"})
        if url == comment_url:
            return _resp({"body": "Latest comment text"})
        raise AssertionError(f"unexpected url: {url}")

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    assert len(result) == 1
    m = result[0]
    assert isinstance(m, EmailMessage)
    assert m.sender == "bob"
    # コメント本文が優先される
    assert m.body_text is not None
    assert "Latest comment text" in m.body_text


# ---------------------------------------------------------------------------
# 5. snippet / body_text の切り詰め
# ---------------------------------------------------------------------------

def test_snippet_truncated_to_120_chars() -> None:
    long_body = "あ" * 500
    notif = _make_notification(
        subject_url="https://api.github.com/repos/org/repo/pulls/1",
        latest_comment_url=None,
    )

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        return _resp({"user": {"login": "alice"}, "html_url": "https://...", "body": long_body})

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    assert len(result[0].snippet) <= 120


def test_body_text_truncated_to_max_body_chars() -> None:
    long_body = "x" * 9000
    notif = _make_notification(
        subject_url="https://api.github.com/repos/org/repo/pulls/1",
        latest_comment_url=None,
    )

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        return _resp({"user": {"login": "alice"}, "html_url": "https://...", "body": long_body})

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock(), max_body_chars=100)
        result = src.list_recent(limit=10)

    assert len(result[0].body_text or "") == 100


# ---------------------------------------------------------------------------
# 6. 401 レスポンスで set_auth_status + RuntimeError
# ---------------------------------------------------------------------------

def test_401_calls_set_auth_status_and_raises() -> None:
    account_repo = _account_repo_mock()

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp({}, status_code=401)
        raise AssertionError("should not reach here")

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", account_repo)
        with pytest.raises(RuntimeError):
            src.list_recent(limit=10)

    account_repo.set_auth_status.assert_called_once_with("acc-1", "reauth_required")


# ---------------------------------------------------------------------------
# 7. 本体取得失敗時に sender が repository.full_name にフォールバックし継続
# ---------------------------------------------------------------------------

def test_subject_fetch_failure_falls_back_to_full_name() -> None:
    notif = _make_notification(
        nid="5",
        reason="mention",
        full_name="org/myrepo",
        subject_url="https://api.github.com/repos/org/myrepo/issues/10",
        latest_comment_url=None,
    )

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        # 本体取得は 500 を返して失敗させる
        return _resp({}, status_code=500)

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    # 継続して1件返ること
    assert len(result) == 1
    assert result[0].sender == "org/myrepo"
    assert result[0].body_text is None


# ---------------------------------------------------------------------------
# 8. received_at が tz-aware（UTC）
# ---------------------------------------------------------------------------

def test_received_at_is_tz_aware_utc() -> None:
    notif = _make_notification(updated_at="2024-03-15T12:00:00Z")
    pr_body = _make_pr_body()

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        return _resp(pr_body)

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    assert result[0].received_at is not None
    assert result[0].received_at.tzinfo is not None
    assert result[0].received_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# 9. verify_credentials 成功 / 失敗
# ---------------------------------------------------------------------------

def test_verify_credentials_success() -> None:
    resp = _resp({"login": "alice", "id": 1})
    with patch("app.adapters.sources.github_api.httpx.get", return_value=resp):
        # 例外が出なければ OK
        GithubApiSource.verify_credentials("token-ok")


def test_verify_credentials_failure_4xx() -> None:
    resp = _resp({"message": "Bad credentials"}, status_code=401)
    with patch("app.adapters.sources.github_api.httpx.get", return_value=resp):
        with pytest.raises(RuntimeError):
            GithubApiSource.verify_credentials("token-bad")


def test_verify_credentials_connection_error() -> None:
    import httpx
    with patch(
        "app.adapters.sources.github_api.httpx.get",
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        with pytest.raises(RuntimeError):
            GithubApiSource.verify_credentials("token-bad")


# ---------------------------------------------------------------------------
# 10. close が no-op
# ---------------------------------------------------------------------------

def test_close_is_noop() -> None:
    src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
    assert src.close() is None


# ---------------------------------------------------------------------------
# 追加: EmailMessage フィールドの詳細検証
# ---------------------------------------------------------------------------

def test_email_message_fields_mapped_correctly() -> None:
    """id / provider / to / is_unread が正しくマッピングされる."""
    notif = _make_notification(
        nid="42",
        reason="assign",
        full_name="myorg/myrepo",
        unread=True,
        updated_at="2024-06-01T09:30:00Z",
    )

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        return _resp(_make_pr_body())

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    m = result[0]
    assert m.id == "42"
    assert m.provider == "github"
    assert m.to == ["myorg/myrepo"]
    assert m.is_unread is True


def test_snippet_uses_title_when_body_is_none() -> None:
    """本体・コメント取得失敗時、snippet は notification title から作られる."""
    notif = _make_notification(
        reason="comment",
        title="Important PR title",
        subject_url="https://api.github.com/repos/org/repo/pulls/1",
        latest_comment_url=None,
    )

    def get_side_effect(url: str, **kwargs):
        if "/notifications" in url:
            return _resp([notif])
        return _resp({}, status_code=500)

    with patch("app.adapters.sources.github_api.httpx.get", side_effect=get_side_effect):
        src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
        result = src.list_recent(limit=10)

    assert "Important PR title" in result[0].snippet


def test_address_property() -> None:
    src = GithubApiSource("token", "alice", "acc-1", _account_repo_mock())
    assert src.address == "alice"
