"""Unit tests for admin content service helpers."""

from __future__ import annotations

from typing import Any

import pytest

from app.services import admin_content as content
from app.services.admin_content import (
    FaqItemDraft,
    PromptTemplateDraft,
    WelcomeMessageDraft,
)

XSS_PAYLOAD = '<img src=x onerror="alert(1)">'
XSS_ESCAPED = "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
CATEGORY_PAYLOAD = "<b>security</b>"
CATEGORY_ESCAPED = "&lt;b&gt;security&lt;/b&gt;"


class _FakeAdmin:
    id = 42


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def test_prompt_template_draft_escapes_html_payloads() -> None:
    cleaned = content._clean_prompt_draft(
        PromptTemplateDraft(
            code="xss_probe",
            title=XSS_PAYLOAD,
            body=XSS_PAYLOAD,
            category=CATEGORY_PAYLOAD,
        )
    )

    assert cleaned.title == XSS_ESCAPED
    assert cleaned.body == XSS_ESCAPED
    assert cleaned.category == CATEGORY_ESCAPED


def test_faq_item_draft_escapes_html_payloads() -> None:
    cleaned = content._clean_faq_draft(
        FaqItemDraft(
            question=XSS_PAYLOAD,
            answer=XSS_PAYLOAD,
            category=CATEGORY_PAYLOAD,
        )
    )

    assert cleaned.question == XSS_ESCAPED
    assert cleaned.answer == XSS_ESCAPED
    assert cleaned.category == CATEGORY_ESCAPED


def test_welcome_message_draft_escapes_html_payloads() -> None:
    cleaned = content._clean_welcome_draft(
        WelcomeMessageDraft(
            name=XSS_PAYLOAD,
            body=XSS_PAYLOAD,
        )
    )

    assert cleaned.name == XSS_ESCAPED
    assert cleaned.body == XSS_ESCAPED


@pytest.mark.asyncio
async def test_create_content_escapes_html_payloads_before_persistence() -> None:
    session = _FakeSession()
    admin = _FakeAdmin()

    prompt = await content.create_prompt_template(
        session,
        admin=admin,  # type: ignore[arg-type]
        draft=PromptTemplateDraft(
            code="xss_probe",
            title=XSS_PAYLOAD,
            body=XSS_PAYLOAD,
            category=CATEGORY_PAYLOAD,
        ),
    )
    faq = await content.create_faq_item(
        session,
        admin=admin,  # type: ignore[arg-type]
        draft=FaqItemDraft(
            question=XSS_PAYLOAD,
            answer=XSS_PAYLOAD,
            category=CATEGORY_PAYLOAD,
        ),
    )
    welcome = await content.create_welcome_message(
        session,
        admin=admin,  # type: ignore[arg-type]
        draft=WelcomeMessageDraft(name=XSS_PAYLOAD, body=XSS_PAYLOAD),
    )

    assert prompt.title == XSS_ESCAPED
    assert prompt.body == XSS_ESCAPED
    assert prompt.category == CATEGORY_ESCAPED
    assert faq.question == XSS_ESCAPED
    assert faq.answer == XSS_ESCAPED
    assert faq.category == CATEGORY_ESCAPED
    assert welcome.name == XSS_ESCAPED
    assert welcome.body == XSS_ESCAPED
