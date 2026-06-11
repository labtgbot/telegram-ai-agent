"""Autogenerate filters for partition-managed database objects."""

from __future__ import annotations

from app.core.alembic_autogenerate import include_object


def test_token_usage_partition_children_are_excluded_from_autogenerate() -> None:
    assert include_object(object(), "token_usage_logs_2026_06", "table", True, None) is False
    assert include_object(object(), "token_usage_logs_default", "table", True, None) is False


def test_token_usage_parent_is_excluded_from_autogenerate() -> None:
    assert include_object(object(), "token_usage_logs", "table", True, object()) is False
    assert include_object(object(), "token_usage_logs", "table", False, object()) is False


def test_unrelated_tables_are_included_in_autogenerate() -> None:
    assert include_object(object(), "users", "table", True, object()) is True
    assert include_object(object(), "ix_token_usage_logs_created", "index", True, object()) is True
