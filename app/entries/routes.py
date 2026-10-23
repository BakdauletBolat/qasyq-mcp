from fastapi import APIRouter, Depends, HTTPException, Request

from app.entries import repo
from app.oauth.deps import require_bearer

router = APIRouter(prefix="/entries", dependencies=[Depends(require_bearer)])


def _db(request: Request) -> str:
    return request.app.state.settings.db_path


@router.post("", status_code=201)
def create(entry: repo.EntryIn, request: Request):
    return repo.add_entry(_db(request), entry)


@router.get("")
def day(date: str, request: Request):
    try:
        return repo.get_day(_db(request), date)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")


@router.delete("/{entry_id}")
def delete(entry_id: int, request: Request):
    if not repo.delete_entry(_db(request), entry_id):
        raise HTTPException(404, "entry not found")
    return {"deleted": entry_id}
