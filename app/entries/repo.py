from datetime import date as date_type

from pydantic import BaseModel, Field, field_validator

from app.db import connect


class EntryIn(BaseModel):
    date: str
    name: str = Field(min_length=1)
    grams: float = Field(ge=0)
    kcal: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    carbs: float = Field(ge=0)

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        return date_type.fromisoformat(v).isoformat()


def add_entry(db_path: str, entry: EntryIn) -> dict:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO entries (date, name, grams, kcal, protein, fat, carbs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry.date, entry.name, entry.grams, entry.kcal, entry.protein, entry.fat, entry.carbs),
        )
        return {"id": cur.lastrowid, **entry.model_dump()}


def get_day(db_path: str, day: str) -> dict:
    day = date_type.fromisoformat(day).isoformat()
    with connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM entries WHERE date = ? ORDER BY id", (day,))]
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ("grams", "kcal", "protein", "fat", "carbs")}
    return {"date": day, "entries": rows, "totals": totals}


def delete_entry(db_path: str, entry_id: int) -> bool:
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0
