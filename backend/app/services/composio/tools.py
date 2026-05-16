"""Mapping between logical AI service types and Composio toolkits.

The mapping is read by both the production HTTP client and the mock
client.  It is intentionally lower-case and centralised so the rest of
the codebase can call ``resolve_tool("image")`` without knowing the
upstream toolkit identifier.

The defaults below cover the Phase 1 acceptance criteria:

* ``gemini`` — text generation (Gemini, fallback to other providers via
  Composio routing rules).
* ``composio_search`` — web search.
* ``image_gen`` — image generation.
* ``video_gen`` — video generation.

Voice and document toolkits are listed for forward-compatibility; the
upstream identifier may change once Phase 2 issues add those services.
"""

from __future__ import annotations

from app.services.composio.errors import ComposioInvalidToolError

SERVICE_TYPE_TO_TOOL: dict[str, str] = {
    "text": "gemini",
    "chat": "gemini",
    "search": "composio_search",
    "image": "image_gen",
    "video": "video_gen",
    "voice": "elevenlabs",
    "document": "document_parser",
}

SUPPORTED_TOOLKITS: frozenset[str] = frozenset(
    {
        "gemini",
        "claude",
        "openai_gpt",
        "composio_search",
        "image_gen",
        "video_gen",
        "elevenlabs",
        "document_parser",
    }
)


def resolve_tool(service_type: str, *, overrides: dict[str, str] | None = None) -> str:
    """Return the Composio toolkit identifier for a logical service type.

    ``overrides`` accepts per-call replacements (typically loaded from
    ``admin_settings.ai_routing``) so operators can A/B test providers
    without a code release.  Raises :class:`ComposioInvalidToolError`
    when the service type is unknown.
    """
    if not service_type or not service_type.strip():
        raise ComposioInvalidToolError("service_type is required")
    key = service_type.strip().lower()
    mapping = {**SERVICE_TYPE_TO_TOOL, **(overrides or {})}
    tool = mapping.get(key)
    if tool is None:
        raise ComposioInvalidToolError(
            f"no Composio tool configured for service_type {service_type!r}"
        )
    return tool


__all__ = ["SERVICE_TYPE_TO_TOOL", "SUPPORTED_TOOLKITS", "resolve_tool"]
