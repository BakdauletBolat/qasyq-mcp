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


def get_range(db_path: str, start: str, end: str) -> dict:
    start = date_type.fromisoformat(start).isoformat()
    end = date_type.fromisoformat(end).isoformat()
    if start > end:
        raise ValueError("start must not be after end")
    with connect(db_path) as conn:
        days = [
            dict(r)
            for r in conn.execute(
                "SELECT date, COUNT(*) AS entries, ROUND(SUM(kcal), 2) AS kcal, ROUND(SUM(protein), 2) AS protein, "
                "ROUND(SUM(fat), 2) AS fat, ROUND(SUM(carbs), 2) AS carbs "
                "FROM entries WHERE date BETWEEN ? AND ? GROUP BY date ORDER BY date",
                (start, end),
            )
        ]
    n = len(days)
    avg = {k: round(sum(d[k] for d in days) / n, 2) for k in ("kcal", "protein", "fat", "carbs")} if n else {}
    return {"start": start, "end": end, "days_logged": n, "average_per_logged_day": avg, "days": days}


def delete_entry(db_path: str, entry_id: int) -> bool:
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0
