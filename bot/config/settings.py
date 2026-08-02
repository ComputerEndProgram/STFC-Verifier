from dataclasses import dataclass
from pathlib import Path

from bot.config import env


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    debug: bool = False
    default_language: str = "en"
    database_url: str | None = None
    sqlite_path: str | None = None

    @property
    def database_path(self) -> Path:
        if self.sqlite_path:
            return Path(self.sqlite_path)
        if self.database_url and self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.removeprefix("sqlite:///"))
        data_dir = Path("data")
        return data_dir / "verifier.sqlite3"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            discord_token=env.required("DISCORD_TOKEN"),
            debug=bool(int(env.optional("DEBUG") or "0")),
            default_language=env.optional("DEFAULT_LANGUAGE") or "en",
            database_url=env.optional("DATABASE_URL"),
            sqlite_path=env.optional("SQLITE_PATH"),
        )
