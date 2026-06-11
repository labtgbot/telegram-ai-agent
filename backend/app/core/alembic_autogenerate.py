"""Alembic autogenerate filters for objects managed outside metadata."""

from __future__ import annotations

import re
from typing import Any

TOKEN_USAGE_PARENT_TABLE = "token_usage_logs"
TOKEN_USAGE_DEFAULT_PARTITION = "token_usage_logs_default"
_TOKEN_USAGE_MONTHLY_PARTITION_RE = re.compile(r"^token_usage_logs_\d{4}_\d{2}$")


def is_token_usage_partition_table(name: str | None) -> bool:
    """Return true for the partitioned parent and its managed child tables."""
    if name is None:
        return False
    return (
        name
        in (
            TOKEN_USAGE_PARENT_TABLE,
            TOKEN_USAGE_DEFAULT_PARTITION,
        )
        or _TOKEN_USAGE_MONTHLY_PARTITION_RE.fullmatch(name) is not None
    )


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],  # noqa: ARG001
) -> bool:
    """Skip token usage partition tables before reflection."""
    return not (type_ == "table" and is_token_usage_partition_table(name))


def include_object(
    object_: Any,  # noqa: ARG001
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: ARG001
    compare_to: Any,  # noqa: ARG001
) -> bool:
    """Skip token usage partition-managed tables in autogenerate diffs."""
    return not (type_ == "table" and is_token_usage_partition_table(name))
