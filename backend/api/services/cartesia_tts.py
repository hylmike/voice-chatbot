"""Cartesia Text-to-Speech Streaming.

Python implementation of Cartesia's Sonic streaming TTS API.
Converts text to PCM audio in real-time using WebSocket streaming.

Input: Text strings
Output: TTS events (tts_chunk for audio chunks)
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
                    print("Cartesia: WebSocket connection closed")
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
    """
    Transform stream: Voice Events → Voice Events (with Audio)

    This function takes a stream of upstream voice agent events and processes them.
    When agent_chunk events arrive, it sends the text to Cartesia for TTS synthesis.
    Audio is streamed back as tts_chunk events as it's generated.
    All upstream events are passed through unchanged.

    It uses merge_async_iters to combine two concurrent streams:
    - process_upstream(): Iterates through incoming events, yields them for
      passthrough, and sends agent text chunks to Cartesia for synthesis.
    - tts.receive_events(): Yields audio chunks from Cartesia as they are
      synthesized.

    The merge utility runs both iterators concurrently, yielding items from
    either stream as they become available. This allows audio generation to
    begin before the agent has finished generating all text, minimizing latency.

    Args:
        event_stream: An async iterator of upstream voice agent events

    Yields:
        All upstream events plus tts_chunk events for synthesized audio
    """

    tts = CartesiaTTS()

    async def process_upstream() -> AsyncIterator[VoiceAgentEvent]:
        """
        Process upstream events, yielding them while sending text to Cartesia.

        This async generator serves two purposes:
        1. Pass through all upstream events (stt_chunk, stt_output, agent_chunk)
           so downstream consumers can observe the full event stream.
        2. Buffer agent_chunk text and send to Cartesia when agent_end arrives.
           This ensures the full response is sent at once for better TTS quality.
        """

        buffer: list[str] = []
        async for event in event_stream:
            # Pass through all events to downstream consumers
            yield event
            # Buffer agent text chunks
            if isinstance(event, AgentChunkEvent):
                buffer.append(event.text)
            elif isinstance(event, AgentEndEvent):
                await tts.send_text("".join(buffer))
                buffer = []

    try:
        # Merge the processed upstream events with TTS audio events
        # Both streams run concurrently, yielding events as they arrive
        async for stream_event in merge_async_iters(
            process_upstream(), tts.receive_events()
        ):
            yield stream_event
    finally:
        await tts.close()
