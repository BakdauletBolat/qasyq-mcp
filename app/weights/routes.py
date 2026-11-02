from fastapi import APIRouter, Depends, Request

from app.oauth.deps import require_bearer
from app.weights import repo

router = APIRouter(prefix="/weights", dependencies=[Depends(require_bearer)])


def _db(request: Request) -> str:
    return request.app.state.settings.db_path


@router.post("", status_code=201)
def create(weight: repo.WeightIn, request: Request):
    return repo.add_weight(_db(request), weight)


@router.get("/recent")
def recent(request: Request):
    return repo.get_last_months(_db(request), months=3)
