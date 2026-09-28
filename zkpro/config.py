"""Runtime settings.

Everything can be overridden with environment variables or a ``zkpro.ini``
file next to the program (``[server]`` section, same names in lower case).
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _ini() -> dict[str, str]:
    path = Path(os.getenv("ZK_CONFIG", BASE_DIR / "zkpro.ini"))
    if not path.exists():
        return {}
    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")
    return dict(cp["server"]) if cp.has_section("server") else {}


def _ports(value: str) -> list[int]:
    return [int(p) for p in str(value).replace(";", ",").split(",") if p.strip()]


@dataclass
class Settings:
    data_dir: Path
    database_url: str
    host: str
    web_port: int
    adms_ports: list[int] = field(default_factory=list)
    secret_key: str = ""
    session_hours: int = 12
    # A device that has not contacted the server for this many seconds is offline.
    offline_after: int = 120

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


def load_settings() -> Settings:
    ini = _ini()

    def get(name: str, default: str) -> str:
        return os.getenv("ZK_" + name.upper(), ini.get(name, default))

    data_dir = Path(get("data_dir", "data"))
    if not data_dir.is_absolute():  # relative to the program, not to the (service) working dir
        data_dir = BASE_DIR / data_dir
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_url = get("database_url", f"sqlite:///{(data_dir / 'zkpro.db').as_posix()}")
    s = Settings(
        data_dir=data_dir,
        database_url=db_url,
        host=get("host", "0.0.0.0"),
        web_port=int(get("web_port", "8090")),
        adms_ports=_ports(get("adms_ports", "8081,90")),
        secret_key=get("secret_key", ""),
        session_hours=int(get("session_hours", "12")),
        offline_after=int(get("offline_after", "120")),
    )
    s.photos_dir.mkdir(parents=True, exist_ok=True)
    s.backups_dir.mkdir(parents=True, exist_ok=True)
    if not s.secret_key:
        key_file = data_dir / ".secret_key"
        if not key_file.exists():
            key_file.write_text(os.urandom(32).hex(), encoding="utf-8")
        s.secret_key = key_file.read_text(encoding="utf-8").strip()
    return s


settings = load_settings()
