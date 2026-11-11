"""Deepgram Flux Text-to-Speech Streaming (/v2/speak).

Python implementation of Deepgram's Flux conversational streaming TTS API.
Streams LLM tokens into /v2/speak with Speak and Flush messages, receives raw
24kHz linear16 PCM audio frames, and handles barge-in via Interrupt messages
while preserving cross-turn conversational prosody.

Reference:
- https://developers.deepgram.com/docs/flux-tts/overview
- https://developers.deepgram.com/docs/flux-tts/quickstart
- https://developers.deepgram.com/docs/flux-tts/client-messages

Input: Text strings / VoiceAgentEvent
Output: TTS events (tts_chunk for audio chunks, plus passthrough events)
"""

import asyncio
import base64
import binascii
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any, Literal
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from ..schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptEvent,
    SpeechStartedEvent,
    TTSChunkEvent,
    VoiceAgentEvent,
)
from ..utils.merge_async_iters import merge_async_iters


class DeepgramFluxTTS:
    """Real-time conversational streaming TTS client using Deepgram Flux (/v2/speak)."""

    api_key: str
    model: str
    encoding: Literal["linear16", "mulaw", "alaw"]
    sample_rate: int
    speed: float
    expressivity: int
    base_url: str
    _ws: ClientConnection | None
    _connection_signal: asyncio.Event
    _close_signal: asyncio.Event
    _discard_audio: bool
    _turn_active: bool

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        api_key: str | None = None,
        model: str | None = None,
        encoding: Literal["linear16", "mulaw", "alaw"] = "linear16",
        sample_rate: int = 24000,
        speed: float = 1.0,
        expressivity: int = 0,
        base_url: str = "wss://api.deepgram.com/v2/speak",
    ) -> None:
        resolved_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        if not resolved_key:
            raise ValueError("Deepgram API key is required (DEEPGRAM_API_KEY)")

        self.api_key = resolved_key
        self.model = model or os.getenv("DEEPGRAM_TTS_MODEL", "flux-wade-en")
        self.encoding = encoding
        self.sample_rate = sample_rate
        self.speed = speed
        self.expressivity = expressivity
        self.base_url = base_url or os.getenv(
            "DEEPGRAM_TTS_URL", "wss://api.deepgram.com/v2/speak"
        )

        self._ws = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._discard_audio = False
        self._turn_active = False

    def _build_url(self) -> str:
        params: dict[str, Any] = {
            "model": self.model,
            "encoding": self.encoding,
            "sample_rate": self.sample_rate,
        }
        if self.speed != 1.0:
            params["speed"] = self.speed
        if self.expressivity != 0:
            params["expressivity"] = self.expressivity
        return f"{self.base_url}?{urlencode(params)}"

    @staticmethod
    def _parse_audio_chunk(chunk: bytes | None) -> TTSChunkEvent | None:
        if not chunk or not isinstance(chunk, bytes):
            return None
        # Ensure 16-bit PCM alignment (even number of bytes)
        valid_len = len(chunk) - (len(chunk) % 2)
        if valid_len <= 0:
            return None
        return TTSChunkEvent.create(chunk[:valid_len])

    def _parse_message(
        self, message: dict[str, Any] | bytes | None
    ) -> TTSChunkEvent | None:
        result: TTSChunkEvent | None = None
        if isinstance(message, bytes):
            if not self._discard_audio:
                result = self._parse_audio_chunk(message)
        elif isinstance(message, dict):
            msg_type = message.get("type")
            if msg_type == "SpeechStarted":
                self._discard_audio = False
                self._turn_active = True
            elif msg_type in {"SpeechMetadata", "SpeechInterrupted"}:
                self._turn_active = False
            elif msg_type == "Error":
                err = message.get("description") or message.get("message") or message
                print(f"[DEBUG] Deepgram Flux TTS error: {err}")
            else:
                data = message.get("data") or message.get("audio")
                if isinstance(data, str) and not self._discard_audio:
                    with contextlib.suppress(ValueError, binascii.Error):
                        result = self._parse_audio_chunk(base64.b64decode(data))
        return result

    async def send_text(self, text: str | None, *, flush: bool = False) -> None:
        """Send a Speak message with text to synthesize on /v2/speak."""
        if text is None or not text.strip():
            if flush and self._turn_active:
                await self.flush()
            return

        ws = await self._ensure_connection()
        self._discard_audio = False
        self._turn_active = True

        await ws.send(json.dumps({"type": "Speak", "text": text}))
        if flush:
            await self.flush()

    async def flush(self) -> None:
        """Send a Flush control message to close the active turn and drain buffered audio."""
        if self._ws is not None and self._ws.close_code is None and self._turn_active:
            await self._ws.send(json.dumps({"type": "Flush"}))

    async def configure(self, speed: float) -> None:
        """Update synthesis speed mid-stream on /v2/speak (0.5 to 1.5 in 0.05 increments)."""
        self.speed = speed
        if self._ws is not None and self._ws.close_code is None:
            await self._ws.send(json.dumps({"type": "Configure", "speed": speed}))

    async def cancel(self) -> None:
        """Interrupt active synthesis on barge-in using Flux TTS Interrupt control frame."""
        self._discard_audio = True
        if self._ws is not None and self._ws.close_code is None and self._turn_active:
            self._turn_active = False
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "Interrupt"}))

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

            if self._ws is not None and self._ws.close_code is None:
                self._connection_signal.clear()
                try:
                    async for raw_message in self._ws:
                        if isinstance(raw_message, bytes):
                            event = self._parse_message(raw_message)
                            if event is not None:
                                yield event
                            continue

                        try:
                            message = json.loads(raw_message)
                            event = self._parse_message(message)
                            if event is not None:
                                yield event
                        except json.JSONDecodeError as e:
                            print(f"[DEBUG] Deepgram Flux TTS JSON decode error: {e}")
                            continue
                except ConnectionClosed:
                    pass
                finally:
                    if self._ws is not None and self._ws.close_code is not None:
                        self._ws = None
                        self._turn_active = False

    async def close(self) -> None:
        """Gracefully close the /v2/speak WebSocket connection."""
        self._discard_audio = True
        self._turn_active = False
        if self._ws is not None and self._ws.close_code is None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "Close"}))
            await self._ws.close()
        self._ws = None
        self._close_signal.set()

    async def _ensure_connection(self) -> ClientConnection:
        if self._close_signal.is_set():
            raise RuntimeError(
                "DeepgramFluxTTS tried establishing a connection after it was closed"
            )
        if self._ws is not None and self._ws.close_code is None:
            return self._ws

        url = self._build_url()
        ws = await connect(
            url,
            additional_headers={"Authorization": f"Token {self.api_key}"},
        )
        self._ws = ws
        self._connection_signal.set()
        return ws


DeepgramTTS = DeepgramFluxTTS


async def tts_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Voice Events → Voice Events (with Audio)

    Streams LLM chunks directly into Deepgram Flux TTS (/v2/speak) using Speak
    messages, flushes at the end of the agent turn, and sends Interrupt on barge-in.
    """
    tts = DeepgramFluxTTS()

    async def process_upstream() -> AsyncIterator[VoiceAgentEvent]:
        has_sent_in_turn = False
        last_chunk_ended_with_space = True

        async for event in event_stream:
            # Barge-in or explicit interrupt: immediately interrupt active synthesis
            if isinstance(event, (InterruptEvent, SpeechStartedEvent)):
                has_sent_in_turn = False
                last_chunk_ended_with_space = True
                await tts.cancel()
                yield event
                continue

            yield event

            if isinstance(event, AgentChunkEvent):
                chunk_text = event.text
                if not chunk_text or not chunk_text.strip():
                    continue
                # Ensure whitespace between stitched LLM generations if needed
                if (
                    has_sent_in_turn
                    and not last_chunk_ended_with_space
                    and not chunk_text[0].isspace()
                    and chunk_text[0] not in ".,!?;:)]}"
                ):
                    chunk_text = f" {chunk_text}"
                await tts.send_text(chunk_text)
                has_sent_in_turn = True
                last_chunk_ended_with_space = chunk_text[-1].isspace()
            elif isinstance(event, AgentEndEvent):
                if has_sent_in_turn:
                    await tts.flush()
                has_sent_in_turn = False
                last_chunk_ended_with_space = True

    try:
        async for stream_event in merge_async_iters(
            process_upstream(), tts.receive_events()
        ):
            yield stream_event
    finally:
        await tts.close()
