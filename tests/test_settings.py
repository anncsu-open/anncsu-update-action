import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

# Ensure src is on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from settings import AnncsuUpdateSettings  # noqa: E402


def _write_env(tmp_path, content: str):
    (tmp_path / ".env").write_text(content, encoding="utf-8")


def test_loads_from_env_file(tmp_path, monkeypatch):
    _write_env(tmp_path, "ANNCSU_UPDATE_CODICE_COMUNE=I501\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANNCSU_UPDATE_CODICE_COMUNE", raising=False)
    s = AnncsuUpdateSettings()
    assert s.codice_comune == "I501"


def test_empty_value_allowed(tmp_path, monkeypatch):
    _write_env(tmp_path, "ANNCSU_UPDATE_CODICE_COMUNE=\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANNCSU_UPDATE_CODICE_COMUNE", raising=False)
    s = AnncsuUpdateSettings()
    assert s.codice_comune == ""


def test_missing_key_raises(tmp_path, monkeypatch):
    # no .env file present -> should raise MissingKeyError
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANNCSU_UPDATE_CODICE_COMUNE", raising=False)
    with pytest.raises(ValidationError):
        AnncsuUpdateSettings()
