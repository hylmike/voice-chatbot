"""Cartesia Text-to-Speech Streaming.

Python implementation of Cartesia's Sonic streaming TTS API.
Converts text to PCM audio in real-time using WebSocket streaming.

Input: Text strings / VoiceAgentEvent
Output: TTS events (tts_chunk for audio chunks, plus passthrough events)
"""

import asyncio
import base64
import contextlib
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

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


class CartesiaTTS:
    api_key: str
    _ws: ClientConnection | None
    _connection_signal: asyncio.Event
    _close_signal: asyncio.Event

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        api_key: str | None = None,
        voice_id: str = "f6ff7c0c-e396-40a9-a70b-f7607edb6937",
        model_id: str = "sonic-3.6",
        sample_rate: int = 24000,
        encoding: Literal[
            "pcm_s16le", "pcm_f32le", "pcm_mulaw", "pcm_alaw"
        ] = "pcm_s16le",
        language: str = "en",
        cartesia_version: str = "2026-08-14",
    ) -> None:
        resolved_key = api_key or os.getenv("CARTESIA_API_KEY")
        if not resolved_key:
            raise ValueError("Cartesia API key is required")

        self.api_key = resolved_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.sample_rate = sample_rate
        self.encoding = encoding
        self.language = language
        self.cartesia_version = cartesia_version or os.getenv(
            "CARTESIA_VERSION", "2026-08-14"
        )
        self._ws = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._context_counter = 0

    def _generate_context_id(self) -> str:
        """Generate a valid context_id for Cartesia.

        Context IDs must only contain alphanumeric characters, underscores, and hyphens.
        """
        timestamp = int(time.time() * 1000)
        counter = self._context_counter
        self._context_counter += 1
        return f"ctx_{timestamp}_{counter}"

    @staticmethod
    def _parse_message(message: dict[str, Any]) -> TTSChunkEvent | None:
        data = message.get("data")
        if isinstance(data, str | bytes):
            audio_chunk = base64.b64decode(data)
            if audio_chunk:
                return TTSChunkEvent.create(audio_chunk)
        return None

    async def send_text(self, text: str | None) -> None:
        if text is None:
            return

        if not text.strip():
            return

        ws = await self._ensure_connection()

        payload = {
            "model_id": self.model_id,
            "transcript": text,
            "voice": {
                "mode": "id",
                "id": self.voice_id,
            },
            "output_format": {
                "container": "raw",
                "encoding": self.encoding,
                "sample_rate": self.sample_rate,
            },
            "language": self.language,
            "context_id": self._generate_context_id(),
        }
        await ws.send(json.dumps(payload))

    async def cancel(self) -> None:
        """Cancel ongoing TTS generation immediately by resetting the active WebSocket."""
        if self._ws is not None and self._ws.close_code is None:
            await self._ws.close()
        self._ws = None

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
                        try:
                            message = json.loads(raw_message)
                            event = self._parse_message(message)
                            if event is not None:
                                yield event
                            if message.get("done"):
                                break
                            if message.get("error"):
                                print(f"[DEBUG] Cartesia error: {message['error']}")
                                break
                        except json.JSONDecodeError as e:
                            print(f"[DEBUG] Cartesia JSON decode error: {e}")
                            continue
                except ConnectionClosed:
                    pass
                finally:
                    if self._ws is not None and self._ws.close_code is None:
                        await self._ws.close()
                    self._ws = None

    async def close(self) -> None:
        if self._ws is not None and self._ws.close_code is None:
            await self._ws.close()
        self._ws = None
        self._close_signal.set()

    async def _ensure_connection(self) -> ClientConnection:
        if self._close_signal.is_set():
            raise RuntimeError(
                "CartesiaTTS tried establishing a connection after it was closed"
            )
        if self._ws is not None and self._ws.close_code is None:
            return self._ws

        url = (
            "wss://api.cartesia.ai/tts/websocket"
            f"?api_key={self.api_key}&cartesia_version={self.cartesia_version}"
        )
        ws = await connect(url)
        self._ws = ws
        self._connection_signal.set()
        return ws


async def tts_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Voice Events → Voice Events (with Audio)

    Processes upstream events, synthesizes TTS audio chunks, and supports
    instant barge-in / interrupt cancellation.
    """
    tts = CartesiaTTS()

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
