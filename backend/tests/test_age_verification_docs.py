"""Documentation contract tests for the age-verification stub."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOCS = (
    REPO_ROOT / "docs/API_REFERENCE.md",
    REPO_ROOT / "docs/USER_GUIDE.md",
    REPO_ROOT / "docs/legal/AGE_VERIFICATION.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return " ".join(text.split())


def test_public_docs_do_not_reference_removed_age_verify_endpoint() -> None:
    for path in PUBLIC_DOCS:
        assert "/compliance/age-verify" not in _read(path), path


def test_public_docs_pin_current_age_verification_stub_contract() -> None:
    api_reference = _read(REPO_ROOT / "docs/API_REFERENCE.md")
    user_guide = _read(REPO_ROOT / "docs/USER_GUIDE.md")
    legal_policy = _read(REPO_ROOT / "docs/legal/AGE_VERIFICATION.md")

    assert "`GET` | `/user/me/age-verification`" in api_reference
    assert "`POST` | `/user/me/age-verification`" in api_reference
    assert "`POST /api/v1/user/me/age-verification`" in user_guide
    assert "does not persist `age_verified_at`" in api_reference
    assert "does not persist `age_verified_at`" in _normalized(legal_policy)
    assert "Future provider requirements" in legal_policy
