import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str
    owner_password: str
    db_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        base_url = os.environ.get("BASE_URL", "").rstrip("/")
        password = os.environ.get("OWNER_PASSWORD", "")
        if not base_url:
            raise RuntimeError("BASE_URL is required")
        if not password:
            raise RuntimeError("OWNER_PASSWORD is required")
        return cls(
            base_url=base_url,
            owner_password=password,
            db_path=os.environ.get("DB_PATH", "./data/food.db"),
        )
