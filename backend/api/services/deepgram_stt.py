"""Deepgram Flux Real-Time Conversational STT Transform

Connects to Deepgram's Flux (/v2/listen) WebSocket API for low-latency
conversational speech-to-text and model-integrated turn detection.

Reference:
- https://developers.deepgram.com/docs/stt/getting-started
- https://developers.deepgram.com/docs/flux/quickstart
- https://developers.deepgram.com/docs/flux/state

Input: PCM 16-bit audio buffer (bytes) or VoiceAgentEvent (passthrough)
Output: STT events (speech_started for StartOfTurn barge-in, stt_chunk for partials,
        stt_output for finalized EndOfTurn transcripts)
"""

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from ..schemas.events import (
    BaseEvent,
    SpeechStartedEvent,
    STTChunkEvent,
    STTEvent,
    STTOutputEvent,
    VoiceAgentEvent,
)


class DeepgramFluxSTT:
    """Real-time streaming STT client using Deepgram Flux (/v2/listen)."""

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        api_key: str | None = None,
        model: str | None = None,
        encoding: str = "linear16",
        sample_rate: int = 16000,
        eot_threshold: float = 0.7,
        eager_eot_threshold: float | None = None,
        eot_timeout_ms: int = 5000,
        base_url: str = "wss://api.deepgram.com/v2/listen",
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("Deepgram API key is required (DEEPGRAM_API_KEY)")

        self.model = model or os.getenv("DEEPGRAM_STT_MODEL", "flux-general-en")
        self.encoding = encoding
        self.sample_rate = sample_rate
        self.eot_threshold = eot_threshold
        self.eager_eot_threshold = eager_eot_threshold
        self.eot_timeout_ms = eot_timeout_ms
        self.base_url = base_url or os.getenv(
            "DEEPGRAM_STT_URL", "wss://api.deepgram.com/v2/listen"
        )

        self._ws: ClientConnection | None = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._last_completed_turn_index: int | None = None

    def _parse_messages(self, message: dict[str, Any]) -> list[STTEvent]:
        """Parse a Deepgram Flux /v2/listen JSON message into pipeline STTEvent items."""
        msg_type = message.get("type")
        event_name = message.get("event")
        if msg_type in {"Connected", "Warning", "Error"} or not event_name:
            return []

        transcript = str(message.get("transcript") or "").strip()
        turn_index = message.get("turn_index")
        events: list[STTEvent] = []

        # StartOfTurn is Flux's native barge-in signal and guarantees initial speech
        if event_name == "StartOfTurn":
            events.append(SpeechStartedEvent.create())
            if transcript:
                events.append(STTChunkEvent.create(transcript))
        elif event_name in {"Update", "EagerEndOfTurn", "TurnResumed"}:
            if transcript:
                events.append(STTChunkEvent.create(transcript))
        elif event_name == "EndOfTurn" and transcript:
            if turn_index is None or turn_index != self._last_completed_turn_index:
                if turn_index is not None:
                    self._last_completed_turn_index = int(turn_index)
                events.append(STTOutputEvent.create(transcript))

        return events

    def _parse_message(self, message: dict[str, Any]) -> STTEvent | None:
        """Return the primary STTEvent for a Flux message (used by single-event callers)."""
        events = self._parse_messages(message)
        return events[0] if events else None

    async def receive_events(self) -> AsyncIterator[STTEvent]:
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
                            continue
                        try:
                            message = json.loads(raw_message)
                            if message.get("type") == "Error" or "error" in message:
                                err = message.get("description") or message.get("error")
                                print(f"Deepgram Flux STT error: {err}")
                                break

                            for event in self._parse_messages(message):
                                yield event
                        except json.JSONDecodeError as e:
                            print(f"[DEBUG] Deepgram Flux STT JSON decode error: {e}")
                            continue
                except ConnectionClosed:
                    print("Deepgram Flux STT: WebSocket connection closed")

    async def send_audio(self, audio_chunk: bytes) -> None:
        if not audio_chunk:
            return
        ws = await self._ensure_connection()
        await ws.send(audio_chunk)

    async def force_end_turn(self) -> None:
        """Send ForceEndTurn control message to finalize the active turn immediately."""
        if self._ws is not None and self._ws.close_code is None:
            await self._ws.send(json.dumps({"type": "ForceEndTurn"}))

    async def close(self) -> None:
        if self._ws is not None and self._ws.close_code is None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            await self._ws.close()
        self._ws = None
        self._last_completed_turn_index = None
        self._close_signal.set()

    def _build_url(self) -> str:
        query_params: dict[str, Any] = {
            "model": self.model,
            "encoding": self.encoding,
            "sample_rate": self.sample_rate,
            "eot_threshold": self.eot_threshold,
            "eot_timeout_ms": self.eot_timeout_ms,
        }
        if self.eager_eot_threshold is not None:
            query_params["eager_eot_threshold"] = self.eager_eot_threshold
        return f"{self.base_url}?{urlencode(query_params)}"

    async def _ensure_connection(self) -> ClientConnection:
        if self._close_signal.is_set():
            raise RuntimeError(
                "DeepgramFluxSTT tried establishing a connection after it was closed"
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


DeepgramSTT = DeepgramFluxSTT


async def stt_stream(
    audio_stream: AsyncIterator[bytes | VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Audio / Control Events → Voice Events

    Connects to Deepgram Flux (/v2/listen) streaming WebSocket with native turn detection.
    - Yields SpeechStartedEvent when user speech starts (StartOfTurn barge-in).
    - Yields STTChunkEvent for partial transcripts during speaking.
    - Yields STTOutputEvent for finalized conversation turns (EndOfTurn).
    - Passes through non-audio control events (e.g. InterruptEvent) concurrently.
    """
    stt = DeepgramFluxSTT(
        sample_rate=16000,
        model=os.getenv("DEEPGRAM_STT_MODEL", "flux-general-en"),
    )
    out_queue: asyncio.Queue[VoiceAgentEvent | object] = asyncio.Queue()
    sentinel = object()

    async def send_audio_producer() -> None:
        try:
            async for item in audio_stream:
                if isinstance(item, bytes):
                    await stt.send_audio(item)
                elif isinstance(item, BaseEvent):
                    await out_queue.put(item)
        finally:
            await stt.close()

    async def receive_transcripts_consumer() -> None:
        try:
            async for event in stt.receive_events():
                await out_queue.put(event)
        finally:
            await out_queue.put(sentinel)

    send_task = asyncio.create_task(send_audio_producer())
    recv_task = asyncio.create_task(receive_transcripts_consumer())

    try:
        while True:
            item = await out_queue.get()
            if item is sentinel:
                break
            yield item  # type: ignore[misc]
    finally:
        send_task.cancel()
        recv_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await send_task
        with contextlib.suppress(asyncio.CancelledError):
            await recv_task
        await stt.close()
