"""GET /emails（後方互換）.

PoC 時代の GET /emails の「形」（list[EmailMessage]）を維持する. 実装は
ライブ取得ではなく, リポジトリに保存済みのメールを新しい順（received_at 降順）
で返す. 取得は Ingestion パイプライン経由に一本化された.
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthDep, get_repo
from app.models import EmailMessage
from app.ports import MessageQuery, Repository

router = APIRouter(tags=["emails"])


@router.get("/emails", response_model=list[EmailMessage], dependencies=[AuthDep])
def get_emails(
    limit: int = Query(10, ge=1, le=50),
    repo: Repository = Depends(get_repo),
) -> list[EmailMessage]:
    q = MessageQuery(order_by="received_at", descending=True, limit=limit)
    records = repo.query(q)
    return [r.email for r in records]
