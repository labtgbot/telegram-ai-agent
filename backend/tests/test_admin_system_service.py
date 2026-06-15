"""Service-level tests for admin system settings."""

from __future__ import annotations

import pytest

from app.services import admin_system
from app.services.admin_system import InvalidSettingPayloadError


def test_validate_composio_accepts_allowed_config_schema() -> None:
    enabled_tools, config = admin_system._validate_composio(
        [" gemini ", "gemini", " composio_search "],
        {
            "tool_overrides": {"text": "claude"},
            "tool_options": {
                "gemini": {
                    "enabled": True,
                    "timeout_seconds": 20,
                    "max_retries": 2,
                }
            },
        },
    )

    assert enabled_tools == ["gemini", "composio_search"]
    assert config == {
        "tool_overrides": {"text": "claude"},
        "tool_options": {
            "gemini": {
                "enabled": True,
                "timeout_seconds": 20.0,
                "max_retries": 2,
            }
        },
    }


def test_validate_composio_rejects_secret_like_root_config_field() -> None:
    with pytest.raises(InvalidSettingPayloadError, match="unsupported Composio config field"):
        admin_system._validate_composio(["gemini"], {"api_key": "secret"})


def test_validate_composio_rejects_secret_like_tool_option_field() -> None:
    with pytest.raises(InvalidSettingPayloadError, match="unsupported Composio tool option"):
        admin_system._validate_composio(
            ["gemini"],
            {"tool_options": {"gemini": {"token": "secret"}}},
        )


def test_coerce_composio_sanitizes_legacy_secret_config() -> None:
    state = admin_system._coerce_composio(
        {
            "enabled_tools": [" gemini ", "gemini"],
            "config": {
                "api_key": "secret",
                "tool_overrides": {"text": "claude", "unknown": "gemini"},
                "tool_options": {
                    "gemini": {
                        "enabled": True,
                        "api_key": "secret",
                        "timeout_seconds": 20,
                        "max_retries": 2,
                    },
                    "unknown_tool": {"token": "secret"},
                },
            },
        }
    )

    assert state.enabled_tools == ["gemini"]
    assert state.config == {
        "tool_overrides": {"text": "claude"},
        "tool_options": {
            "gemini": {
                "enabled": True,
                "timeout_seconds": 20.0,
                "max_retries": 2,
            }
        },
    }
