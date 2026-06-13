"""メッセージ操作・取り込み・認証のルート.

ダッシュボードの主フィード（/messages）と状態遷移（/messages/{id}/state）,
手動取り込み（/ingest）, ログイン（/auth/login）を担う. ドメイン例外
（NotFound/Conflict/Transition）は main の例外ハンドラが HTTP へ写像する.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import authenticate, create_access_token
from app.api.deps import (
    AuthDep,
    get_ingestion,
    get_repo,
    get_settings,
    get_state_service,
)
from app.api.schemas import (
    IngestResult,
    LoginRequest,
    StateUpdateRequest,
    TokenResponse,
)
from app.config import Settings
from app.models import MessageRecord, MessageState
from app.ports import MessageQuery, Repository
from app.services.ingestion import IngestionService
from app.services.state_service import StateService

router = APIRouter()


@router.get(
    "/messages",
    response_model=list[MessageRecord],
    tags=["messages"],
    dependencies=[AuthDep],
)
def list_messages(
    state: MessageState | None = Query(default=None),
    unread_only: bool = Query(default=False),
    archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    order_by: Literal["triage_score", "received_at", "importance"] = Query(
        default="triage_score"
    ),
    descending: bool = Query(default=True),
    providers: list[str] = Query(default=[]),
    account_addresses: list[str] = Query(default=[]),
    importance_min: int | None = Query(default=None, ge=1, le=6),
    received_after: datetime | None = Query(default=None),
    received_before: datetime | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> list[MessageRecord]:
    q = MessageQuery(
        state=state,
        unread_only=unread_only,
        archived=archived,
        limit=limit,
        offset=offset,
        order_by=order_by,
        descending=descending,
        providers=providers,
        account_addresses=account_addresses,
        importance_min=importance_min,
        received_after=received_after,
        received_before=received_before,
    )
    return repo.query(q)


@router.get(
    "/messages/{message_id}",
    response_model=MessageRecord,
    tags=["messages"],
    dependencies=[AuthDep],
)
def get_message(
    message_id: str,
    repo: Repository = Depends(get_repo),
) -> MessageRecord:
    record = repo.get(message_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="メッセージが見つかりません",
        )
    return record


@router.post(
    "/messages/{message_id}/state",
    response_model=MessageRecord,
    tags=["messages"],
    dependencies=[AuthDep],
)
def update_message_state(
    message_id: str,
    body: StateUpdateRequest,
    svc: StateService = Depends(get_state_service),
) -> MessageRecord:
    # ドメイン例外は main の例外ハンドラが 404/409 へ写像する.
    return svc.transition(message_id, body.state, body.version)


@router.post(
    "/messages/{message_id}/archive",
    response_model=MessageRecord,
    tags=["messages"],
    dependencies=[AuthDep],
)
def archive_message(
    message_id: str,
    repo: Repository = Depends(get_repo),
) -> MessageRecord:
    return repo.set_archived(message_id, True)


@router.post(
    "/messages/{message_id}/unarchive",
    response_model=MessageRecord,
    tags=["messages"],
    dependencies=[AuthDep],
)
def unarchive_message(
    message_id: str,
    repo: Repository = Depends(get_repo),
) -> MessageRecord:
    return repo.unarchive(message_id)


@router.get(
    "/providers",
    response_model=list[str],
    tags=["messages"],
    dependencies=[AuthDep],
)
def list_providers(repo: Repository = Depends(get_repo)) -> list[str]:
    return repo.list_providers()


@router.post(
    "/ingest",
    response_model=IngestResult,
    tags=["ingest"],
    dependencies=[AuthDep],
)
def trigger_ingest(
    ingestion: IngestionService = Depends(get_ingestion),
) -> dict:
    return ingestion.run_once()


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="認証は無効です",
        )
    if not authenticate(settings, body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ユーザー名またはパスワードが違います",
        )
    token = create_access_token(settings, body.username)
    return TokenResponse(access_token=token)
