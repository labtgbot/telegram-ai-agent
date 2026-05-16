"""Unit tests for :class:`VoiceProcessingService`.

The service is exercised against :class:`MockComposioClient` plus an
in-memory stub for the SQLAlchemy session / :class:`TokenService` so
the suite runs without a database (same pattern as
``test_image_generation.py`` / ``test_web_search.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.services.composio import (
    ComposioTransientError,
    MockComposioClient,
    ToolInvocation,
    ToolResult,
)
from app.services.token_service import (
    InsufficientTokensError,
    SpendResult,
    UserNotFoundError,
)
from app.services.voice_processing import (
    DEFAULT_VOICE,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_URL_LENGTH,
    MAX_LANGUAGE_LENGTH,
    MAX_PROMPT_LENGTH,
    MAX_VOICE_LENGTH,
    MODE_STT,
    MODE_TTS,
    SERVICE_TYPE,
    VOICE_COST,
    InvalidAudioError,
    InvalidVoicePromptError,
    VoiceProcessingResult,
    VoiceProcessingService,
    VoiceProviderError,
)

# --------------------------------------------------------------- stubs


@dataclass
class _RecordedSpend:
    user_id: int
    amount: int
    service: str
    request_params: dict[str, Any] | None
    response_status: str | None
    processing_time_ms: int | None
    composio_tool: str | None
    mcp_server: str | None


class _FakeTokenService:
    """Stand-in for :class:`TokenService` that doesn't touch a DB."""

    def __init__(self, *, balances: dict[int, int] | None = None) -> None:
        self.balances: dict[int, int] = dict(balances or {})
        self.spends: list[_RecordedSpend] = []
        self.balance_calls: list[int] = []
        self._next_tx = 1000
        self._next_log = 5000

    async def get_balance(self, user_id: int) -> int:
        self.balance_calls.append(user_id)
        if user_id not in self.balances:
            raise UserNotFoundError(f"user {user_id} not found")
        return self.balances[user_id]

    async def spend(
        self,
        *,
        user_id: int,
        amount: int,
        service: str,
        request_params: dict[str, Any] | None = None,
        response_status: str | None = "ok",
        processing_time_ms: int | None = None,
        composio_tool: str | None = None,
        mcp_server: str | None = None,
    ) -> SpendResult:
        if user_id not in self.balances:
            raise UserNotFoundError(f"user {user_id} not found")
        current = self.balances[user_id]
        if current < amount:
            raise InsufficientTokensError(required=amount, available=current)
        self.balances[user_id] = current - amount
        self.spends.append(
            _RecordedSpend(
                user_id=user_id,
                amount=amount,
                service=service,
                request_params=dict(request_params or {}),
                response_status=response_status,
                processing_time_ms=processing_time_ms,
                composio_tool=composio_tool,
                mcp_server=mcp_server,
            )
        )
        self._next_tx += 1
        self._next_log += 1
        return SpendResult(
            user_id=user_id,
            amount=amount,
            new_balance=self.balances[user_id],
            transaction_id=self._next_tx,
            transaction_type="spend",
            usage_log_id=self._next_log,
        )


class _FakeSession:
    """Minimal AsyncSession stub — collects audit rows added via ``add``."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushes = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.fixture
def fake_tokens() -> _FakeTokenService:
    return _FakeTokenService(balances={42: 500})


@pytest.fixture
def fake_session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def composio_mock() -> MockComposioClient:
    return MockComposioClient()


def _build_service(
    session: _FakeSession,
    composio: MockComposioClient,
    tokens: _FakeTokenService,
) -> VoiceProcessingService:
    service = VoiceProcessingService(session, composio)  # type: ignore[arg-type]
    service._tokens = tokens  # type: ignore[assignment]
    return service


def _stt_only_handler(transcript: str = "hello world", language: str = "en"):
    """Return a handler that produces an STT payload only."""

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={"transcript": transcript, "language": language},
            service_type=invocation.service_type,
        )

    return _handler


def _stt_plus_tts_handler(
    transcript: str = "hello world",
    audio_url: str = "https://cdn.example.com/reply.mp3",
):
    """Return a handler that flips between STT and TTS based on ``mode``."""

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        mode = invocation.params.get("mode")
        if mode == MODE_STT:
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"transcript": transcript, "language": "en"},
                service_type=invocation.service_type,
            )
        if mode == MODE_TTS:
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"audio_url": audio_url},
                service_type=invocation.service_type,
            )
        return ToolResult(
            tool=invocation.tool,
            successful=False,
            error=f"unexpected mode {mode!r}",
            service_type=invocation.service_type,
        )

    return _handler


# --------------------------------------------------------------- constants


def test_voice_cost_is_five() -> None:
    assert VOICE_COST == 5


def test_service_type_is_voice() -> None:
    assert SERVICE_TYPE == "voice"


def test_mode_constants_are_stable() -> None:
    assert MODE_STT == "stt"
    assert MODE_TTS == "tts"


# ------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_rejects_missing_audio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(user_id=42)
    assert composio_mock.calls == []


@pytest.mark.asyncio
async def test_rejects_empty_audio_url_and_base64(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(user_id=42, audio_url="   ", audio_base64="   ")


@pytest.mark.asyncio
async def test_rejects_overlong_audio_url(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/" + ("a" * (MAX_AUDIO_URL_LENGTH + 1)),
        )


@pytest.mark.asyncio
async def test_rejects_non_http_audio_url(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(user_id=42, audio_url="ftp://example.com/a.ogg")


@pytest.mark.asyncio
async def test_rejects_oversized_audio_base64(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    # 4 base64 chars per 3 bytes — go just above MAX_AUDIO_BYTES.
    over_chars = (MAX_AUDIO_BYTES // 3) * 4 + 100
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(user_id=42, audio_base64="a" * over_chars)


@pytest.mark.asyncio
async def test_rejects_overlong_language(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            language="x" * (MAX_LANGUAGE_LENGTH + 1),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_duration", [-1.0, "abc"])
async def test_rejects_invalid_duration(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
    bad_duration: Any,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            duration_seconds=bad_duration,
        )


@pytest.mark.asyncio
async def test_rejects_duration_over_cap(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidAudioError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            duration_seconds=MAX_AUDIO_DURATION_SECONDS + 1,
        )


@pytest.mark.asyncio
async def test_rejects_overlong_reply_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidVoicePromptError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            synthesize_reply=True,
            reply_prompt="x" * (MAX_PROMPT_LENGTH + 1),
        )


@pytest.mark.asyncio
async def test_rejects_reply_prompt_without_synthesize_flag(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidVoicePromptError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            synthesize_reply=False,
            reply_prompt="Hello back",
        )


@pytest.mark.asyncio
async def test_rejects_overlong_voice(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    service = _build_service(fake_session, composio_mock, fake_tokens)
    with pytest.raises(InvalidVoicePromptError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            synthesize_reply=True,
            voice="v" * (MAX_VOICE_LENGTH + 1),
        )


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_stt_only_debits_flat_cost(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler("elevenlabs", _stt_only_handler())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.process(
        user_id=42, audio_url="https://example.com/a.ogg"
    )

    assert isinstance(outcome, VoiceProcessingResult)
    assert outcome.transcript == "hello world"
    assert outcome.language == "en"
    assert outcome.reply_text is None
    assert outcome.reply_audio_url is None
    assert outcome.tokens_spent == VOICE_COST
    assert outcome.new_balance == 500 - VOICE_COST
    assert outcome.composio_tool == "elevenlabs"
    assert outcome.usage_log_id > 0
    assert outcome.transaction_id > 0
    # Only one Composio call (STT — no TTS leg).
    assert len(composio_mock.calls) == 1
    assert composio_mock.calls[0].params["mode"] == MODE_STT


@pytest.mark.asyncio
async def test_stt_plus_tts_runs_two_calls(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler("elevenlabs", _stt_plus_tts_handler())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.process(
        user_id=42,
        audio_url="https://example.com/a.ogg",
        synthesize_reply=True,
        reply_prompt="Hi back",
    )

    assert outcome.transcript == "hello world"
    assert outcome.reply_text == "Hi back"
    assert outcome.reply_audio_url == "https://cdn.example.com/reply.mp3"
    assert outcome.tokens_spent == VOICE_COST
    # Two Composio invocations — STT then TTS.
    assert len(composio_mock.calls) == 2
    assert composio_mock.calls[0].params["mode"] == MODE_STT
    assert composio_mock.calls[1].params["mode"] == MODE_TTS
    assert composio_mock.calls[1].params["voice"] == DEFAULT_VOICE
    assert composio_mock.calls[1].params["text"] == "Hi back"


@pytest.mark.asyncio
async def test_tts_uses_transcript_when_no_reply_prompt(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler("elevenlabs", _stt_plus_tts_handler())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.process(
        user_id=42,
        audio_url="https://example.com/a.ogg",
        synthesize_reply=True,
    )

    assert outcome.reply_text == "hello world"
    # TTS leg uses the transcript verbatim when no prompt was supplied.
    assert composio_mock.calls[1].params["text"] == "hello world"


@pytest.mark.asyncio
async def test_voice_passes_request_metadata_to_composio(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler("elevenlabs", _stt_only_handler())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.process(
        user_id=42,
        audio_url="https://example.com/a.ogg",
        language="en",
        duration_seconds=12.5,
        request_id="req-voice-1",
        composio_user_id="composio-user-42",
    )

    call = composio_mock.calls[0]
    assert call.tool == "elevenlabs"
    assert call.service_type == "voice"
    assert call.request_id == "req-voice-1"
    assert call.user_id == "composio-user-42"
    assert call.metadata == {"app_user_id": "42", "phase": MODE_STT}
    assert call.params["audio_url"] == "https://example.com/a.ogg"
    assert call.params["language"] == "en"
    assert call.params["duration_seconds"] == 12.5


@pytest.mark.asyncio
async def test_voice_base64_audio_inlined_in_provider_params(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler("elevenlabs", _stt_only_handler())
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.process(user_id=42, audio_base64="aGVsbG8=")

    call = composio_mock.calls[0]
    # The full binary is sent to the provider…
    assert call.params["audio_base64"] == "aGVsbG8="
    # …but the audit row only stores its length, not the payload itself.
    assert fake_tokens.spends[0].request_params is not None
    stt_audit = fake_tokens.spends[0].request_params["stt"]
    assert stt_audit["audio_base64_len"] == len("aGVsbG8=")
    assert "audio_base64" not in stt_audit


@pytest.mark.asyncio
async def test_voice_spend_audit_has_both_legs_when_synthesizing(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock.set_handler(
        "elevenlabs", _stt_plus_tts_handler()
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    await service.process(
        user_id=42,
        audio_url="https://example.com/a.ogg",
        synthesize_reply=True,
        reply_prompt="Bonjour!",
        voice="alloy",
    )

    assert len(fake_tokens.spends) == 1
    audit = fake_tokens.spends[0].request_params
    assert audit is not None
    assert "stt" in audit and "tts" in audit
    assert audit["tts"]["voice"] == "alloy"
    assert audit["tts"]["text_len"] == len("Bonjour!")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"transcript": "hi"}, "hi"),
        ({"transcription": "hi"}, "hi"),
        ({"text": "hi"}, "hi"),
        ({"output_text": "hi"}, "hi"),
        ({"stt_text": "hi"}, "hi"),
        ({"stt": {"transcript": "hi"}}, "hi"),
        ({"result": {"text": "hi"}}, "hi"),
        ({"response": {"transcription": "hi"}}, "hi"),
    ],
)
async def test_voice_extracts_transcript_from_various_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    payload: dict[str, Any],
    expected: str,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("elevenlabs", data=payload)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.process(
        user_id=42, audio_url="https://example.com/a.ogg"
    )
    assert outcome.transcript == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"transcript": "hi", "language": "ru"}, "ru"),
        ({"transcript": "hi", "detected_language": "fr"}, "fr"),
        ({"transcript": "hi", "lang": "de"}, "de"),
        ({"transcript": "hi", "stt": {"language": "es"}}, "es"),
    ],
)
async def test_voice_extracts_language_from_various_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    payload: dict[str, Any],
    expected: str,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("elevenlabs", data=payload)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.process(
        user_id=42, audio_url="https://example.com/a.ogg"
    )
    assert outcome.language == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected_url",
    [
        ({"audio_url": "https://cdn/a.mp3"}, "https://cdn/a.mp3"),
        ({"url": "https://cdn/b.mp3"}, "https://cdn/b.mp3"),
        ({"output_audio_url": "https://cdn/c.mp3"}, "https://cdn/c.mp3"),
        ({"result_url": "https://cdn/d.mp3"}, "https://cdn/d.mp3"),
        ({"audio": {"url": "https://cdn/e.mp3"}}, "https://cdn/e.mp3"),
        ({"audio": "https://cdn/f.mp3"}, "https://cdn/f.mp3"),
    ],
)
async def test_voice_extracts_audio_url_from_various_shapes(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
    payload: dict[str, Any],
    expected_url: str,
) -> None:
    composio_mock = MockComposioClient()

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        if invocation.params.get("mode") == MODE_STT:
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"transcript": "hi"},
                service_type=invocation.service_type,
            )
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data=payload,
            service_type=invocation.service_type,
        )

    composio_mock.set_handler("elevenlabs", _handler)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    outcome = await service.process(
        user_id=42,
        audio_url="https://example.com/a.ogg",
        synthesize_reply=True,
    )
    assert outcome.reply_audio_url == expected_url


# --------------------------------------------------------- balance + provider


@pytest.mark.asyncio
async def test_insufficient_balance_is_raised_before_provider_call(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={42: 3})  # below 5
    composio_mock.set_handler("elevenlabs", _stt_only_handler())
    service = _build_service(fake_session, composio_mock, tokens)

    with pytest.raises(InsufficientTokensError) as exc:
        await service.process(
            user_id=42, audio_url="https://example.com/a.ogg"
        )
    assert exc.value.required == VOICE_COST
    assert exc.value.available == 3
    assert composio_mock.calls == []
    assert tokens.spends == []


@pytest.mark.asyncio
async def test_unknown_user_raises_user_not_found(
    fake_session: _FakeSession,
    composio_mock: MockComposioClient,
) -> None:
    tokens = _FakeTokenService(balances={})
    service = _build_service(fake_session, composio_mock, tokens)
    with pytest.raises(UserNotFoundError):
        await service.process(
            user_id=999, audio_url="https://example.com/a.ogg"
        )


@pytest.mark.asyncio
async def test_provider_error_in_stt_phase_is_translated(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_error(
        "elevenlabs", ComposioTransientError("stt upstream 503")
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VoiceProviderError) as exc:
        await service.process(
            user_id=42, audio_url="https://example.com/a.ogg"
        )
    assert exc.value.provider_error is not None
    assert "stt" in str(exc.value).lower()
    assert fake_tokens.spends == []
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_provider_error_in_tts_phase_does_not_charge(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        if invocation.params.get("mode") == MODE_STT:
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"transcript": "hello"},
                service_type=invocation.service_type,
            )
        # TTS leg fails.
        raise ComposioTransientError("tts upstream 503")

    composio_mock.set_handler("elevenlabs", _handler)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VoiceProviderError) as exc:
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            synthesize_reply=True,
        )
    assert "tts" in str(exc.value).lower()
    # Balance untouched — STT cost is not charged if the TTS leg fails.
    assert fake_tokens.spends == []
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_empty_transcript_audits_failure_and_raises(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response("elevenlabs", data={"transcript": ""})
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VoiceProviderError):
        await service.process(
            user_id=42, audio_url="https://example.com/a.ogg"
        )

    assert len(fake_session.added) >= 1
    assert fake_session.flushes >= 1
    assert fake_tokens.spends == []
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_empty_tts_audio_url_audits_failure_and_raises(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()

    async def _handler(invocation: ToolInvocation) -> ToolResult:
        if invocation.params.get("mode") == MODE_STT:
            return ToolResult(
                tool=invocation.tool,
                successful=True,
                data={"transcript": "hello"},
                service_type=invocation.service_type,
            )
        # TTS leg succeeds but doesn't return an audio URL.
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={},
            service_type=invocation.service_type,
        )

    composio_mock.set_handler("elevenlabs", _handler)
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VoiceProviderError):
        await service.process(
            user_id=42,
            audio_url="https://example.com/a.ogg",
            synthesize_reply=True,
        )

    assert len(fake_session.added) >= 1
    assert fake_session.flushes >= 1
    assert fake_tokens.spends == []
    assert fake_tokens.balances[42] == 500


@pytest.mark.asyncio
async def test_unsuccessful_stt_response_translates_to_provider_error(
    fake_session: _FakeSession,
    fake_tokens: _FakeTokenService,
) -> None:
    composio_mock = MockComposioClient()
    composio_mock.set_response(
        "elevenlabs",
        successful=False,
        data={},
        error="rate_limited",
    )
    service = _build_service(fake_session, composio_mock, fake_tokens)

    with pytest.raises(VoiceProviderError) as exc:
        await service.process(
            user_id=42, audio_url="https://example.com/a.ogg"
        )
    assert exc.value.provider_error == "rate_limited"
    assert fake_tokens.spends == []
