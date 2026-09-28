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


def test_dry_run_defaults_to_false(tmp_path, monkeypatch):
    _write_env(tmp_path, "ANNCSU_UPDATE_CODICE_COMUNE=I501\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANNCSU_UPDATE_DRY_RUN", raising=False)
    s = AnncsuUpdateSettings()
    assert s.dry_run is False


@pytest.mark.parametrize(
    "value, expected",
    [("true", True), ("1", True), ("yes", True), ("false", False), ("0", False), ("no", False)],
)
def test_dry_run_from_env_var(tmp_path, monkeypatch, value, expected):
    _write_env(tmp_path, "ANNCSU_UPDATE_CODICE_COMUNE=I501\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANNCSU_UPDATE_DRY_RUN", value)
    s = AnncsuUpdateSettings()
    assert s.dry_run is expected


def test_dry_run_from_env_file(tmp_path, monkeypatch):
    _write_env(tmp_path, "ANNCSU_UPDATE_CODICE_COMUNE=I501\nANNCSU_UPDATE_DRY_RUN=true\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANNCSU_UPDATE_DRY_RUN", raising=False)
    s = AnncsuUpdateSettings()
    assert s.dry_run is True


def test_dry_run_invalid_value_raises(tmp_path, monkeypatch):
    _write_env(tmp_path, "ANNCSU_UPDATE_CODICE_COMUNE=I501\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANNCSU_UPDATE_DRY_RUN", "maybe")
    with pytest.raises(ValidationError):
        AnncsuUpdateSettings()
