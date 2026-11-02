from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from app.db import connect


class WeightIn(BaseModel):
    kg: float = Field(gt=0, lt=1000)
    recorded_at: str | None = None

    @field_validator("recorded_at")
    @classmethod
    def _iso_datetime(cls, v: str | None) -> str | None:
        return None if v is None else datetime.fromisoformat(v).isoformat(timespec="seconds")


def add_weight(db_path: str, weight: WeightIn) -> dict:
    recorded_at = weight.recorded_at or datetime.now().isoformat(timespec="seconds")
    with connect(db_path) as conn:
        cur = conn.execute("INSERT INTO weights (recorded_at, kg) VALUES (?, ?)", (recorded_at, weight.kg))
        return {"id": cur.lastrowid, "recorded_at": recorded_at, "kg": weight.kg}


def get_last_months(db_path: str, months: int = 3) -> dict:
    since = (datetime.now() - timedelta(days=30 * months)).isoformat(timespec="seconds")
    with connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, recorded_at, kg FROM weights WHERE recorded_at >= ? ORDER BY recorded_at", (since,)
            )
        ]
    return {"since": since, "weights": rows}
