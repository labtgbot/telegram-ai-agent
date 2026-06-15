"""Voice-message domain service.

Phase-2 sibling of :mod:`app.services.image_generation`,
:mod:`app.services.text_generation` and :mod:`app.services.web_search`.
The same Composio toolkit gateway, ``TokenService`` debit pattern and
``token_usage_logs`` audit shape are reused — only the request/response
payloads differ.

A single ``process`` call orchestrates one voice-message round-trip:

1.  Validate the audio reference (URL/base64 + duration cap) and the
    optional reply prompt.
2.  Atomically debit the flat 5-token price before the provider call.
3.  Invoke the Composio ``elevenlabs`` toolkit asking for STT — and, if
    ``synthesize_reply`` is on, follow up with TTS for the assistant's
    answer.
4.  Normalise the transcripts / audio URL pulled out of the heterogenous
    payloads.
5.  Attach provider metadata to the structured ``token_usage_logs`` row;
    on provider failure, refund the debit and write a zero-cost audit row.

The service flushes its writes but does **not** commit — the caller
controls the outer transaction, matching every other service in
``app.services``.
"""

from __future__ import annotations

import base64
import io
import wave
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.balance_cache import get_default_balance_cache
from app.services.composio import (
    ComposioClient,
    ComposioError,
    ToolResult,
    log_invocation,
)
from app.services.token_service import TokenService

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

SERVICE_TYPE: Final[str] = "voice"

# Flat 5-token price for the round trip (STT + optional TTS) — issue #16.
VOICE_COST: Final[int] = 5

# Provider-side modes used when invoking Composio.
MODE_STT: Final[str] = "stt"
MODE_TTS: Final[str] = "tts"

# Hard limits — see issue #16. The cap is enforced both as audio length
# (seconds) and binary size (bytes) so a forged URL can't pull a 1 GB file.
MAX_AUDIO_DURATION_SECONDS: Final[int] = 5 * 60
MAX_AUDIO_BYTES: Final[int] = 25 * 1024 * 1024  # 25 MB
MAX_LANGUAGE_LENGTH: Final[int] = 16
MAX_PROMPT_LENGTH: Final[int] = 4000
MAX_AUDIO_URL_LENGTH: Final[int] = 2048
DEFAULT_VOICE: Final[str] = "default"
MAX_VOICE_LENGTH: Final[int] = 64
_AUDIO_DOWNLOAD_CHUNK_BYTES: Final[int] = 64 * 1024
_AUDIO_FETCH_TIMEOUT_SECONDS: Final[float] = 10.0
_AUDIO_HTTP_HEADERS: Final[dict[str, str]] = {
    "User-Agent": "telegram-ai-agent/voice-url-validator",
}


# ----------------------------------------------------------------- errors


class VoiceProcessingError(Exception):
    """Base class for voice-processing errors."""


class InvalidAudioError(VoiceProcessingError):
    """Raised when the supplied audio reference is missing or invalid."""


class InvalidVoicePromptError(VoiceProcessingError):
    """Raised when the optional reply prompt is empty or too long."""


class VoiceProviderError(VoiceProcessingError):
    """Raised when the Composio voice toolkit fails.

    Exposes ``provider_error`` so the API / bot layer can include the
    upstream message in its response without re-reading the raw payload.
    """

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


# --------------------------------------------------------------- result types


@dataclass(frozen=True)
class VoiceProcessingResult:
    """Outcome of a successful ``process`` call.

    ``reply_text`` and ``reply_audio_url`` are populated when the caller
    asked for synthesis; for transcription-only calls they stay ``None``.
    """

    user_id: int
    transcript: str
    language: str | None = None
    reply_text: str | None = None
    reply_audio_url: str | None = None
    duration_seconds: float | None = None
    tokens_spent: int = 0
    new_balance: int = 0
    composio_tool: str = ""
    mcp_server: str | None = None
    processing_time_ms: int | None = None
    usage_log_id: int = 0
    transaction_id: int = 0
    request_id: str | None = None


@dataclass(frozen=True)
class _RemoteAudioPayload:
    audio_base64: str
    size_bytes: int
    duration_seconds: float
    content_type: str | None = None


# ------------------------------------------------------------------ service


class VoiceProcessingService:
    """Service object — instantiate per request with the active session."""

    def __init__(
        self,
        session: AsyncSession,
        composio: ComposioClient,
        *,
        audio_http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.composio = composio
        self._audio_http_client = audio_http_client
        self._tokens = TokenService(session, get_default_balance_cache())

    async def process(
        self,
        *,
        user_id: int,
        audio_url: str | None = None,
        audio_base64: str | None = None,
        language: str | None = None,
        synthesize_reply: bool = False,
        reply_prompt: str | None = None,
        voice: str | None = None,
        duration_seconds: float | None = None,
        request_id: str | None = None,
        composio_user_id: str | None = None,
    ) -> VoiceProcessingResult:
        """Run one voice round-trip and debit the per-call token cost.

        Either ``audio_url`` or ``audio_base64`` must be provided.  When
        ``synthesize_reply`` is ``True`` the caller may pass ``reply_prompt``
        verbatim (typically the assistant's text generated upstream);
        otherwise we synthesise the transcript itself.

        Raises:
            InvalidAudioError: missing audio reference / duration or size over the cap.
            InvalidVoicePromptError: ``reply_prompt`` empty or too long.
            InsufficientTokensError: balance below :data:`VOICE_COST`.
            UserNotFoundError: ``user_id`` does not exist.
            VoiceProviderError: upstream Composio failure.
        """
        audio_url_clean, audio_b64_clean = self._validate_audio(
            audio_url=audio_url,
            audio_base64=audio_base64,
        )
        language_clean = self._validate_language(language)
        duration_clean = self._validate_duration(duration_seconds)
        reply_prompt_clean = self._validate_reply_prompt(
            reply_prompt, synthesize_reply=synthesize_reply
        )
        voice_clean = self._validate_voice(voice)

        remote_audio: _RemoteAudioPayload | None = None
        duration_for_request = duration_clean
        if audio_url_clean is not None:
            remote_audio = await self._load_audio_url(audio_url_clean)
            duration_for_request = remote_audio.duration_seconds

        stt_request_params: dict[str, Any] = {
            "mode": MODE_STT,
        }
        if audio_url_clean is not None:
            stt_request_params["audio_url"] = audio_url_clean
        if remote_audio is not None:
            stt_request_params["audio_size_bytes"] = remote_audio.size_bytes
            if remote_audio.content_type is not None:
                stt_request_params["audio_content_type"] = remote_audio.content_type
        if audio_b64_clean is not None:
            # We only log a fingerprint of the base64 blob — storing the
            # whole payload in ``token_usage_logs`` would balloon the row.
            stt_request_params["audio_base64_len"] = len(audio_b64_clean)
        if language_clean is not None:
            stt_request_params["language"] = language_clean
        if duration_for_request is not None:
            stt_request_params["duration_seconds"] = duration_for_request

        stt_provider_params: dict[str, Any] = {
            "mode": MODE_STT,
        }
        provider_audio_base64 = audio_b64_clean or (
            remote_audio.audio_base64 if remote_audio is not None else None
        )
        # The Composio toolkit expects the binary inline when present.
        if provider_audio_base64 is not None:
            stt_provider_params["audio_base64"] = provider_audio_base64
        elif audio_url_clean is not None:
            stt_provider_params["audio_url"] = audio_url_clean
        if language_clean is not None:
            stt_provider_params["language"] = language_clean
        if duration_for_request is not None:
            stt_provider_params["duration_seconds"] = duration_for_request

        spend = await self._tokens.spend(
            user_id=user_id,
            amount=VOICE_COST,
            service=SERVICE_TYPE,
            request_params={"stt": stt_request_params},
            response_status="pending",
        )

        try:
            stt_result = await self._invoke_provider(
                user_id=user_id,
                params=stt_provider_params,
                request_id=request_id,
                composio_user_id=composio_user_id,
                phase=MODE_STT,
            )
        except VoiceProviderError:
            await self._refund_spend(
                user_id=user_id,
                transaction_id=spend.transaction_id,
                reason="voice stt provider failed",
            )
            raise

        transcript = self._extract_transcript(stt_result)
        if not transcript:
            await self._refund_spend(
                user_id=user_id,
                transaction_id=spend.transaction_id,
                reason="voice provider returned empty transcript",
            )
            await log_invocation(
                self.session,
                user_id=user_id,
                result=stt_result,
                tokens_consumed=0,
                request_params=stt_request_params,
            )
            raise VoiceProviderError(
                "voice provider did not return a transcript",
                provider_error=stt_result.error,
            )

        detected_language = self._extract_language(stt_result) or language_clean

        reply_text: str | None = None
        reply_audio_url: str | None = None
        tts_result: ToolResult | None = None
        if synthesize_reply:
            reply_text = reply_prompt_clean or transcript
            tts_request_params: dict[str, Any] = {
                "mode": MODE_TTS,
                "text": reply_text,
                "voice": voice_clean,
            }
            if detected_language is not None:
                tts_request_params["language"] = detected_language

            tts_provider_params = dict(tts_request_params)
            try:
                tts_result = await self._invoke_provider(
                    user_id=user_id,
                    params=tts_provider_params,
                    request_id=request_id,
                    composio_user_id=composio_user_id,
                    phase=MODE_TTS,
                )
            except VoiceProviderError:
                await self._refund_spend(
                    user_id=user_id,
                    transaction_id=spend.transaction_id,
                    reason="voice tts provider failed",
                )
                raise
            reply_audio_url = self._extract_audio_url(tts_result)
            if reply_audio_url is None:
                await self._refund_spend(
                    user_id=user_id,
                    transaction_id=spend.transaction_id,
                    reason="voice provider returned empty audio",
                )
                await log_invocation(
                    self.session,
                    user_id=user_id,
                    result=tts_result,
                    tokens_consumed=0,
                    request_params=tts_request_params,
                )
                raise VoiceProviderError(
                    "voice provider did not return synthesised audio",
                    provider_error=tts_result.error,
                )

        # Aggregate the two-phase audit shape so admins can see both
        # legs in a single ``token_usage_logs`` row.
        primary_result = tts_result or stt_result
        request_params_audit: dict[str, Any] = {
            "stt": stt_request_params,
        }
        if synthesize_reply:
            request_params_audit["tts"] = {
                "voice": voice_clean,
                "language": detected_language,
                "text_len": len(reply_text or ""),
            }

        await self._record_spend_result(
            user_id=user_id,
            usage_log_id=spend.usage_log_id,
            result=primary_result,
            request_params=request_params_audit,
        )

        logger.info(
            "voice.processed",
            user_id=user_id,
            transcript_len=len(transcript),
            synthesize_reply=synthesize_reply,
            language=detected_language,
            tokens_spent=VOICE_COST,
            new_balance=spend.new_balance,
            composio_tool=primary_result.tool,
            mcp_server=primary_result.mcp_server,
            latency_ms=primary_result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

        return VoiceProcessingResult(
            user_id=user_id,
            transcript=transcript,
            language=detected_language,
            reply_text=reply_text,
            reply_audio_url=reply_audio_url,
            duration_seconds=duration_for_request,
            tokens_spent=VOICE_COST,
            new_balance=spend.new_balance,
            composio_tool=primary_result.tool,
            mcp_server=primary_result.mcp_server,
            processing_time_ms=primary_result.latency_ms,
            usage_log_id=spend.usage_log_id,
            transaction_id=spend.transaction_id,
            request_id=request_id,
        )

    # -------------------------------------------------------------- internal

    async def _record_spend_result(
        self,
        *,
        user_id: int,
        usage_log_id: int,
        result: ToolResult,
        request_params: dict[str, Any],
    ) -> None:
        try:
            await self._tokens.record_spend_result(
                usage_log_id=usage_log_id,
                response_status="ok",
                processing_time_ms=result.latency_ms,
                composio_tool=result.tool,
                mcp_server=result.mcp_server,
                request_params=request_params,
            )
        except Exception as exc:  # noqa: BLE001 — audit metadata is best-effort
            logger.warning(
                "voice.spend_usage_update_failed",
                user_id=user_id,
                usage_log_id=usage_log_id,
                error=str(exc),
            )

    async def _refund_spend(
        self,
        *,
        user_id: int,
        transaction_id: int,
        reason: str,
    ) -> None:
        try:
            await self._tokens.refund(
                transaction_id=transaction_id,
                reason=reason[:100],
            )
        except Exception as exc:  # noqa: BLE001 — preserve the provider error
            logger.warning(
                "voice.refund_failed",
                user_id=user_id,
                transaction_id=transaction_id,
                reason=reason,
                error=str(exc),
            )

    async def _invoke_provider(
        self,
        *,
        user_id: int,
        params: dict[str, Any],
        request_id: str | None,
        composio_user_id: str | None,
        phase: str,
    ) -> ToolResult:
        try:
            result = await self.composio.invoke_for_service(
                SERVICE_TYPE,
                params,
                user_id=composio_user_id,
                request_id=request_id,
                metadata={"app_user_id": str(user_id), "phase": phase},
            )
        except ComposioError as exc:
            logger.warning(
                "voice.composio_failed",
                user_id=user_id,
                phase=phase,
                error=str(exc),
                request_id=request_id,
            )
            raise VoiceProviderError(
                f"voice provider call failed during {phase}",
                provider_error=str(exc),
            ) from exc

        if not result.successful:
            logger.warning(
                "voice.composio_unsuccessful",
                user_id=user_id,
                phase=phase,
                tool=result.tool,
                error=result.error,
                request_id=request_id,
            )
            raise VoiceProviderError(
                f"voice provider returned unsuccessful in {phase}: " f"{result.error or 'unknown'}",
                provider_error=result.error,
            )
        return result

    async def _load_audio_url(self, audio_url: str) -> _RemoteAudioPayload:
        client = self._audio_http_client
        if client is not None:
            return await self._load_audio_url_with_client(client, audio_url)

        timeout = httpx.Timeout(_AUDIO_FETCH_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as owned_client:
            return await self._load_audio_url_with_client(owned_client, audio_url)

    async def _load_audio_url_with_client(
        self,
        client: httpx.AsyncClient,
        audio_url: str,
    ) -> _RemoteAudioPayload:
        try:
            head_response = await client.head(
                audio_url,
                headers=_AUDIO_HTTP_HEADERS,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            logger.info(
                "voice.audio_url_head_failed",
                audio_url_len=len(audio_url),
                error=str(exc),
            )
        else:
            if 200 <= head_response.status_code < 400:
                self._assert_content_length_within_cap(head_response.headers)

        chunks: list[bytes] = []
        total = 0
        content_type: str | None = None
        try:
            async with client.stream(
                "GET",
                audio_url,
                headers=_AUDIO_HTTP_HEADERS,
                follow_redirects=True,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise InvalidAudioError(
                        f"audio_url returned HTTP {response.status_code}"
                    )
                self._assert_content_length_within_cap(response.headers)
                content_type = response.headers.get("Content-Type")

                async for chunk in response.aiter_bytes(
                    chunk_size=_AUDIO_DOWNLOAD_CHUNK_BYTES
                ):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise InvalidAudioError(
                            f"audio payload must be at most {MAX_AUDIO_BYTES} bytes"
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise InvalidAudioError("audio_url could not be fetched") from exc

        if total == 0:
            raise InvalidAudioError("audio_url returned empty audio")

        audio_bytes = b"".join(chunks)
        duration = self._extract_audio_duration_seconds(
            audio_bytes,
            content_type=content_type,
            audio_url=audio_url,
        )
        self._validate_duration(duration)
        return _RemoteAudioPayload(
            audio_base64=base64.b64encode(audio_bytes).decode("ascii"),
            size_bytes=total,
            duration_seconds=duration,
            content_type=content_type,
        )

    @staticmethod
    def _assert_content_length_within_cap(headers: httpx.Headers) -> None:
        value = headers.get("Content-Length")
        if value is None:
            return
        try:
            size = int(value)
        except ValueError:
            return
        if size > MAX_AUDIO_BYTES:
            raise InvalidAudioError(f"audio payload must be at most {MAX_AUDIO_BYTES} bytes")

    @classmethod
    def _extract_audio_duration_seconds(
        cls,
        audio_bytes: bytes,
        *,
        content_type: str | None,
        audio_url: str,
    ) -> float:
        duration = cls._extract_mutagen_duration_seconds(audio_bytes, audio_url=audio_url)
        if duration is None:
            duration = cls._extract_wave_duration_seconds(audio_bytes)
        if duration is None:
            logger.info(
                "voice.audio_url_duration_unknown",
                audio_url_len=len(audio_url),
                content_type=content_type,
                size_bytes=len(audio_bytes),
            )
            raise InvalidAudioError("audio_url duration could not be determined")
        return duration

    @staticmethod
    def _extract_mutagen_duration_seconds(
        audio_bytes: bytes,
        *,
        audio_url: str,
    ) -> float | None:
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            return None

        fileobj = io.BytesIO(audio_bytes)
        filename = urlparse(audio_url).path.rsplit("/", 1)[-1] or "audio"
        fileobj.name = filename
        try:
            audio = MutagenFile(fileobj)
        except Exception as exc:  # noqa: BLE001 - malformed media should be rejected
            logger.debug(
                "voice.audio_url_mutagen_failed",
                audio_url_len=len(audio_url),
                error=str(exc),
            )
            return None
        info = getattr(audio, "info", None)
        length = getattr(info, "length", None)
        if isinstance(length, (int, float)) and length >= 0:
            return float(length)
        return None

    @staticmethod
    def _extract_wave_duration_seconds(audio_bytes: bytes) -> float | None:
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as audio:
                frame_rate = audio.getframerate()
                frame_count = audio.getnframes()
        except (EOFError, wave.Error):
            return None
        if frame_rate <= 0:
            return None
        return frame_count / float(frame_rate)

    @staticmethod
    def _extract_transcript(result: ToolResult) -> str:
        """Pull the transcribed text from a Composio response.

        Different STT toolkits return ``transcript``/``text``/``output_text``
        — we probe the common keys in order so the service keeps working
        as Composio routes between providers.
        """
        data = result.data or {}
        for key in (
            "transcript",
            "transcription",
            "text",
            "output_text",
            "stt_text",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for nested_key in ("stt", "result", "response"):
            nested = data.get(nested_key)
            if isinstance(nested, dict):
                for key in ("transcript", "transcription", "text"):
                    value = nested.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return ""

    @staticmethod
    def _extract_language(result: ToolResult) -> str | None:
        data = result.data or {}
        for key in ("language", "detected_language", "lang"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        stt = data.get("stt")
        if isinstance(stt, dict):
            for key in ("language", "detected_language", "lang"):
                value = stt.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _extract_audio_url(result: ToolResult) -> str | None:
        """Pull the synthesised audio URL from a Composio response."""
        data = result.data or {}
        for key in (
            "audio_url",
            "url",
            "output_audio_url",
            "result_url",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = data.get("audio")
        if isinstance(nested, dict):
            for key in ("url", "audio_url", "result_url"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
        return None

    # --------------------------------------------------------------- validators

    @staticmethod
    def _validate_audio(
        *, audio_url: str | None, audio_base64: str | None
    ) -> tuple[str | None, str | None]:
        url_clean: str | None = None
        b64_clean: str | None = None
        if audio_url is not None:
            url_clean = str(audio_url).strip() or None
        if audio_base64 is not None:
            b64_clean = str(audio_base64).strip() or None
        if url_clean is None and b64_clean is None:
            raise InvalidAudioError("audio_url or audio_base64 is required")
        if url_clean is not None and len(url_clean) > MAX_AUDIO_URL_LENGTH:
            raise InvalidAudioError(f"audio_url must be at most {MAX_AUDIO_URL_LENGTH} characters")
        if url_clean is not None and not (
            url_clean.lower().startswith("http://") or url_clean.lower().startswith("https://")
        ):
            raise InvalidAudioError("audio_url must be an absolute http(s) URL")
        if b64_clean is not None:
            # Each 4 base64 chars encode 3 bytes — over-approximate to keep
            # the maths simple; we only need a hard upper bound here.
            approx_bytes = (len(b64_clean) // 4) * 3
            if approx_bytes > MAX_AUDIO_BYTES:
                raise InvalidAudioError(f"audio payload must be at most {MAX_AUDIO_BYTES} bytes")
        return url_clean, b64_clean

    @staticmethod
    def _validate_language(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_LANGUAGE_LENGTH:
            raise InvalidAudioError(f"language must be at most {MAX_LANGUAGE_LENGTH} characters")
        return clean

    @staticmethod
    def _validate_duration(value: float | None) -> float | None:
        if value is None:
            return None
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidAudioError("duration_seconds must be a number") from exc
        if num < 0:
            raise InvalidAudioError("duration_seconds must be non-negative")
        if num > MAX_AUDIO_DURATION_SECONDS:
            raise InvalidAudioError(
                f"duration_seconds must be at most {MAX_AUDIO_DURATION_SECONDS}"
            )
        return num

    @staticmethod
    def _validate_reply_prompt(value: str | None, *, synthesize_reply: bool) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        if not clean:
            return None
        if len(clean) > MAX_PROMPT_LENGTH:
            raise InvalidVoicePromptError(
                f"reply_prompt must be at most {MAX_PROMPT_LENGTH} characters"
            )
        if not synthesize_reply:
            # Reject the silent footgun: caller passed a prompt but forgot
            # to enable synthesis — surface it instead of dropping the prompt.
            raise InvalidVoicePromptError("reply_prompt requires synthesize_reply=True")
        return clean

    @staticmethod
    def _validate_voice(value: str | None) -> str:
        if value is None or not str(value).strip():
            return DEFAULT_VOICE
        clean = str(value).strip()
        if len(clean) > MAX_VOICE_LENGTH:
            raise InvalidVoicePromptError(f"voice must be at most {MAX_VOICE_LENGTH} characters")
        return clean


__all__ = [
    "DEFAULT_VOICE",
    "InvalidAudioError",
    "InvalidVoicePromptError",
    "MAX_AUDIO_BYTES",
    "MAX_AUDIO_DURATION_SECONDS",
    "MAX_AUDIO_URL_LENGTH",
    "MAX_LANGUAGE_LENGTH",
    "MAX_PROMPT_LENGTH",
    "MAX_VOICE_LENGTH",
    "MODE_STT",
    "MODE_TTS",
    "SERVICE_TYPE",
    "VOICE_COST",
    "VoiceProcessingError",
    "VoiceProcessingResult",
    "VoiceProcessingService",
    "VoiceProviderError",
]
