"""アカウント設定の CRUD ルート."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import AuthDep, get_account_repo
from app.models import AccountConfig, AccountConfigCreate
from app.repositories.account_repository import AccountRepository

router = APIRouter()


@router.get(
    "/accounts",
    response_model=list[AccountConfig],
    tags=["accounts"],
    dependencies=[AuthDep],
)
def list_accounts(repo: AccountRepository = Depends(get_account_repo)) -> list[AccountConfig]:
    return repo.list_all()


@router.post(
    "/accounts",
    response_model=AccountConfig,
    status_code=status.HTTP_201_CREATED,
    tags=["accounts"],
    dependencies=[AuthDep],
)
def create_account(
    body: AccountConfigCreate,
    repo: AccountRepository = Depends(get_account_repo),
) -> AccountConfig:
    return repo.create(
        provider=body.provider,
        label=body.label,
        address=body.address,
        credential=body.credential,
    )


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["accounts"],
    dependencies=[AuthDep],
)
def delete_account(
    account_id: str,
    repo: AccountRepository = Depends(get_account_repo),
) -> None:
    found = repo.delete(account_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="アカウントが見つかりません",
        )
