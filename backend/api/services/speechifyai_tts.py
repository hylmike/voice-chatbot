"""Speechify Text-to-Speech Streaming.

Python implementation of Speechify AI's streaming TTS API.
Converts text to PCM audio in real-time using HTTP chunked streaming.

Input: Text strings / VoiceAgentEvent
Output: TTS events (tts_chunk for audio chunks, plus passthrough events)
"""

import asyncio
import base64
import binascii
import contextlib
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptEvent,
    SpeechStartedEvent,
    TTSChunkEvent,
    VoiceAgentEvent,
)
from ..utils.merge_async_iters import merge_async_iters


class SpeechifyTTS:
    api_key: str
    voice_id: str
    model_id: str
    output_format: str
    sample_rate: int
    language: str | None
    api_url: str
    chunk_size: int
    _client: httpx.AsyncClient | None
    _active_response: httpx.Response | None
    _connection_signal: asyncio.Event
    _close_signal: asyncio.Event
    _cancel_signal: asyncio.Event
    _request_counter: int

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        api_key: str | None = None,
        voice_id: str = "geffen_32",
        model_id: str = "simba-3.2",
        output_format: str = "pcm_24000",
        sample_rate: int = 24000,
        language: str | None = None,
        api_url: str = "https://api.speechify.ai/v1/audio/stream",
        chunk_size: int = 2400,
    ) -> None:
        resolved_key = api_key or os.getenv("SPEECHIFY_API_KEY")
        if not resolved_key:
            raise ValueError("Speechify API key is required")

        self.api_key = resolved_key
        self.voice_id = voice_id or os.getenv("SPEECHIFY_VOICE_ID", "geffen_32")
        self.model_id = model_id or os.getenv("SPEECHIFY_MODEL_ID", "simba-3.2")
        self.output_format = output_format or os.getenv(
            "SPEECHIFY_OUTPUT_FORMAT", f"pcm_{sample_rate}"
        )
        self.sample_rate = sample_rate
        self.language = language or os.getenv("SPEECHIFY_LANGUAGE")
        self.api_url = api_url or os.getenv(
            "SPEECHIFY_API_URL", "https://api.speechify.ai/v1/audio/stream"
        )
        self.chunk_size = chunk_size

        self._client = None
        self._active_response = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._cancel_signal = asyncio.Event()
        self._request_counter = 0

    def _generate_request_id(self) -> str:
        """Generate a valid request_id for Speechify tracking."""
        timestamp = int(time.time() * 1000)
        counter = self._request_counter
        self._request_counter += 1
        return f"req_{timestamp}_{counter}"

    def _generate_context_id(self) -> str:
        """Alias for Cartesia compatibility."""
        return self._generate_request_id()

    @staticmethod
    def _parse_chunk(chunk: bytes | None) -> TTSChunkEvent | None:
        if chunk and isinstance(chunk, bytes) and len(chunk) > 0:
            return TTSChunkEvent.create(chunk)
        return None

    @staticmethod
    def _parse_message(message: dict[str, Any] | bytes | None) -> TTSChunkEvent | None:
        if isinstance(message, bytes):
            return SpeechifyTTS._parse_chunk(message)
        if isinstance(message, dict):
            data = message.get("data") or message.get("audio")
            if isinstance(data, str):
                try:
                    audio_chunk = base64.b64decode(data)
                    if audio_chunk:
                        return TTSChunkEvent.create(audio_chunk)
                except (ValueError, binascii.Error):
                    return None
            elif isinstance(data, bytes) and data:
                return TTSChunkEvent.create(data)
        return None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._close_signal.is_set():
            raise RuntimeError(
                "SpeechifyTTS tried establishing a connection after it was closed"
            )
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        return self._client

    async def send_text(self, text: str | None) -> None:
        if text is None:
            return

        if not text.strip():
            return

        if self._close_signal.is_set():
            raise RuntimeError("SpeechifyTTS tried sending text after it was closed")

        # Cancel any ongoing stream before initiating a new one
        await self.cancel()
        self._cancel_signal.clear()

        client = await self._ensure_client()
        request_id = self._generate_request_id()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
            "Speechify-Request-Id": request_id,
        }
        payload: dict[str, Any] = {
            "input": text,
            "voice_id": self.voice_id,
            "model": self.model_id,
            "output_format": self.output_format,
        }
        if self.language:
            payload["language"] = self.language

        request = client.build_request(
            "POST",
            self.api_url,
            headers=headers,
            json=payload,
        )
        response = await client.send(request, stream=True)
        self._active_response = response
        self._connection_signal.set()

    async def cancel(self) -> None:
        """Cancel ongoing TTS generation immediately by closing the active response."""
        self._cancel_signal.set()
        self._connection_signal.clear()
        if self._active_response is not None:
            await self._active_response.aclose()
            self._active_response = None

    async def _stream_response_chunks(
        self, response: httpx.Response
    ) -> AsyncIterator[TTSChunkEvent]:
        """Stream chunks from HTTP response buffered to even 16-bit PCM boundaries."""
        buffer = bytearray()
        async for raw_chunk in response.aiter_bytes():
            if self._cancel_signal.is_set():
                break
            buffer.extend(raw_chunk)
            while len(buffer) >= self.chunk_size:
                chunk_to_send = bytes(buffer[: self.chunk_size])
                buffer = buffer[self.chunk_size :]
                event = self._parse_chunk(chunk_to_send)
                if event is not None:
                    yield event

        if buffer and not self._cancel_signal.is_set():
            valid_len = len(buffer) - (len(buffer) % 2)
            if valid_len > 0:
                event = self._parse_chunk(bytes(buffer[:valid_len]))
                if event is not None:
                    yield event

    async def receive_events(self) -> AsyncIterator[TTSChunkEvent]:
        while not self._close_signal.is_set():
            _, pending = await asyncio.wait(
                [
                    asyncio.create_task(self._close_signal.wait()),
                    asyncio.create_task(self._connection_signal.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            with contextlib.suppress(asyncio.CancelledError):
                for task in pending:
                    task.cancel()

            if self._close_signal.is_set():
                break

            if self._active_response is not None:
                self._connection_signal.clear()
                response = self._active_response
                try:
                    if response.is_error:
                        error_body = await response.aread()
                        print(
                            f"[DEBUG] Speechify error: {response.status_code} "
                            f"{error_body.decode('utf-8', errors='replace')}"
                        )
                    else:
                        async for event in self._stream_response_chunks(response):
                            yield event
                except (httpx.HTTPError, asyncio.CancelledError):
                    pass
                finally:
                    await response.aclose()
                    if self._active_response is response:
                        self._active_response = None

    async def close(self) -> None:
        """Close active streams and HTTP client."""
        await self.cancel()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._close_signal.set()


SpeechifyAITTS = SpeechifyTTS


async def tts_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Voice Events → Voice Events (with Audio)

    Processes upstream events, synthesizes TTS audio chunks, and supports
    instant barge-in / interrupt cancellation using Speechify AI streaming TTS.
    """
    tts = SpeechifyTTS()

    async def process_upstream() -> AsyncIterator[VoiceAgentEvent]:
        buffer: list[str] = []
        async for event in event_stream:
            # Handle barge-in / explicit interrupt: clear text and abort ongoing synthesis
            if isinstance(event, (InterruptEvent, SpeechStartedEvent)):
                buffer = []
                await tts.cancel()
                yield event
                continue

            yield event

            if isinstance(event, AgentChunkEvent):
                buffer.append(event.text)
            elif isinstance(event, AgentEndEvent) and buffer:
                await tts.send_text("".join(buffer))
                buffer = []

    try:
        async for stream_event in merge_async_iters(
            process_upstream(), tts.receive_events()
        ):
            yield stream_event
    finally:
        await tts.close()
