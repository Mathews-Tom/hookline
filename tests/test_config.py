"""Tests for configuration precedence logic."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


def _config_mod() -> Any:
    """Get the notify.config module (not shadowed by __init__.py re-exports)."""
    return sys.modules["notify.config"]


class TestCfgBool:
    """Test _cfg_bool: env var -> config file -> default."""

    def test_env_var_1_is_true(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_BOOL", "1")
        assert notify._cfg_bool("TEST_BOOL", "test_bool", False) is True

    def test_env_var_0_is_false(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_BOOL", "0")
        assert notify._cfg_bool("TEST_BOOL", "test_bool", True) is False

    def test_config_file_bool(self, notify: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        cfg = _config_mod()
        config = tmp_path / "notify-config.json"
        config.write_text('{"test_bool": true}')
        monkeypatch.setattr(cfg, "NOTIFY_CONFIG_PATH", config)
        monkeypatch.setattr(cfg, "_notify_config", None)
        monkeypatch.delenv("TEST_BOOL", raising=False)
        assert notify._cfg_bool("TEST_BOOL", "test_bool", False) is True

    def test_default_used_when_no_env_or_config(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_BOOL", raising=False)
        assert notify._cfg_bool("TEST_BOOL", "missing_key", True) is True
        assert notify._cfg_bool("TEST_BOOL", "missing_key", False) is False

    def test_env_overrides_config(self, notify: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        cfg = _config_mod()
        config = tmp_path / "notify-config.json"
        config.write_text('{"test_bool": true}')
        monkeypatch.setattr(cfg, "NOTIFY_CONFIG_PATH", config)
        monkeypatch.setattr(cfg, "_notify_config", None)
        monkeypatch.setenv("TEST_BOOL", "0")
        assert notify._cfg_bool("TEST_BOOL", "test_bool", True) is False


class TestCfgInt:
    """Test _cfg_int: env var -> config file -> default."""

    def test_env_var_int(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_INT", "42")
        assert notify._cfg_int("TEST_INT", "test_int", 0) == 42

    def test_config_file_int(self, notify: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        cfg = _config_mod()
        config = tmp_path / "notify-config.json"
        config.write_text('{"test_int": 99}')
        monkeypatch.setattr(cfg, "NOTIFY_CONFIG_PATH", config)
        monkeypatch.setattr(cfg, "_notify_config", None)
        monkeypatch.delenv("TEST_INT", raising=False)
        assert notify._cfg_int("TEST_INT", "test_int", 0) == 99

    def test_default(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_INT", raising=False)
        assert notify._cfg_int("TEST_INT", "missing", 77) == 77


class TestCfgStr:
    """Test _cfg_str: env var -> config file -> default."""

    def test_env_var_str(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_STR", "hello")
        assert notify._cfg_str("TEST_STR", "test_str", "default") == "hello"

    def test_default(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_STR", raising=False)
        assert notify._cfg_str("TEST_STR", "missing", "fallback") == "fallback"


class TestCfgSuppress:
    """Test _cfg_suppress: env var (comma-separated) -> config file (list) -> empty set."""

    def test_env_var_comma_separated(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_SUP", "Stop,Notification")
        result = notify._cfg_suppress("TEST_SUP", "suppress")
        assert result == {"Stop", "Notification"}

    def test_config_file_list(self, notify: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        cfg = _config_mod()
        config = tmp_path / "notify-config.json"
        config.write_text('{"suppress": ["TeammateIdle"]}')
        monkeypatch.setattr(cfg, "NOTIFY_CONFIG_PATH", config)
        monkeypatch.setattr(cfg, "_notify_config", None)
        monkeypatch.delenv("TEST_SUP", raising=False)
        result = notify._cfg_suppress("TEST_SUP", "suppress")
        assert result == {"TeammateIdle"}

    def test_empty_default(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_SUP", raising=False)
        result = notify._cfg_suppress("TEST_SUP", "missing")
        assert result == set()
