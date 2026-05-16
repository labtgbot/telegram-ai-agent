"""Legal documents API.

Serves the public-facing legal docs that live in :mod:`docs/legal/`:

* ``GET /api/v1/legal/privacy`` — Privacy Policy (GDPR Art. 13/14 notice).
* ``GET /api/v1/legal/terms`` — Terms of Service.
* ``GET /api/v1/legal/dpa`` — Data Processing Agreement template (Art. 28).
* ``GET /api/v1/legal/subprocessors`` — Current list of sub-processors.
* ``GET /api/v1/legal/age-verification`` — Age verification policy.

Each endpoint returns the rendered Markdown source so the Mini App can
display it inside a webview without an extra fetch to GitHub. The default
response is JSON (``LegalDocumentResponse``); request the same path with
``Accept: text/markdown`` (or ``?format=markdown``) for the raw body.

The same documents are also exposed at the bare root (``/privacy``,
``/terms``) for direct browser access — wired up in :mod:`app.main`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.logging import get_logger

router = APIRouter(prefix="/legal", tags=["legal"])
logger = get_logger(__name__)

# ``backend/app/api/v1/legal.py`` → ``docs/legal/`` (repo root / docs / legal).
_LEGAL_DIR: Final[Path] = (
    Path(__file__).resolve().parents[4] / "docs" / "legal"
).resolve()


class LegalDocument(BaseModel):
    """Metadata about a published legal document."""

    slug: str = Field(description="URL slug (``privacy``, ``terms`` …).")
    title: str = Field(description="Human-readable title.")
    filename: str = Field(description="Source filename under ``docs/legal/``.")


class LegalDocumentResponse(BaseModel):
    """Full legal document body with metadata."""

    slug: str
    title: str
    content_type: str = "text/markdown"
    body: str
    last_updated: date | None = None
    fetched_at: datetime


class LegalIndexResponse(BaseModel):
    """List of available legal documents."""

    documents: list[LegalDocument]


# Slug → (filename, title). Keep the slugs short and stable (Mini App / bot
# reference them by name).
LEGAL_DOCUMENTS: Final[dict[str, tuple[str, str]]] = {
    "privacy": ("PRIVACY_POLICY.md", "Privacy Policy"),
    "terms": ("TERMS_OF_SERVICE.md", "Terms of Service"),
    "dpa": ("DPA_TEMPLATE.md", "Data Processing Agreement (Template)"),
    "subprocessors": ("SUBPROCESSORS.md", "Sub-processors"),
    "age-verification": ("AGE_VERIFICATION.md", "Age Verification Policy"),
}


def _legal_path(filename: str) -> Path:
    """Resolve and validate a document path inside ``_LEGAL_DIR``.

    Guards against path traversal by checking the resolved path is still
    inside ``_LEGAL_DIR``.
    """
    candidate = (_LEGAL_DIR / filename).resolve()
    try:
        candidate.relative_to(_LEGAL_DIR)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="legal_document_not_found"
        ) from exc
    return candidate


def _parse_last_updated(body: str) -> date | None:
    """Best-effort extraction of the ``Last updated: YYYY-MM-DD`` marker."""
    for line in body.splitlines()[:20]:
        marker = "Last updated:"
        if marker in line:
            try:
                raw = line.split(marker, 1)[1].strip().strip("*").strip()
                return date.fromisoformat(raw[:10])
            except (ValueError, IndexError):
                continue
    return None


def _wants_markdown(request: Request, fmt: str | None) -> bool:
    if fmt and fmt.lower() in {"markdown", "md", "text"}:
        return True
    accept = request.headers.get("accept", "")
    return "text/markdown" in accept or "text/plain" in accept


def load_legal_document(slug: str) -> LegalDocumentResponse:
    """Read a legal document from disk. Raises 404 if the slug is unknown."""
    entry = LEGAL_DOCUMENTS.get(slug)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="legal_document_not_found"
        )
    filename, title = entry
    path = _legal_path(filename)
    try:
        body = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        logger.warning("legal.document_missing", slug=slug, path=str(path))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="legal_document_not_found"
        ) from exc
    return LegalDocumentResponse(
        slug=slug,
        title=title,
        body=body,
        last_updated=_parse_last_updated(body),
        fetched_at=datetime.now(UTC),
    )


@router.get(
    "",
    response_model=LegalIndexResponse,
    summary="List of available legal documents",
)
async def list_legal() -> LegalIndexResponse:
    return LegalIndexResponse(
        documents=[
            LegalDocument(slug=slug, title=title, filename=filename)
            for slug, (filename, title) in LEGAL_DOCUMENTS.items()
        ]
    )


@router.get(
    "/{slug}",
    summary="Get a legal document by slug",
    response_model=LegalDocumentResponse,
)
async def get_legal_document(
    slug: str,
    request: Request,
    format: str | None = Query(default=None, description="Force ``markdown`` to bypass JSON."),
) -> Response:
    document = load_legal_document(slug)
    if _wants_markdown(request, format):
        return Response(content=document.body, media_type="text/markdown; charset=utf-8")
    return Response(
        content=document.model_dump_json(),
        media_type="application/json",
    )
