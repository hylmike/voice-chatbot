"""AssemblyAI Real-Time Streaming STT Transform

Connects to AssemblyAI's Streaming v3 WebSocket API for speech-to-text,
VAD (Voice Activity Detection), and semantic turn detection.

Input: PCM 16-bit audio buffer (bytes) or VoiceAgentEvent (passthrough)
Output: STT events (speech_started for VAD barge-in, stt_chunk for partials, stt_output for final transcripts)
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


class AssemblyAISTT:
    def __init__(  # noqa: PLR0913, PLR0917
        self,
        api_key: str | None = None,
        sample_rate: int = 16000,
        format_turns: bool = True,
        speech_model: str = "universal-3-6-pro",
        min_turn_silence: int = 200,
        max_turn_silence: int = 1000,
    ) -> None:
        self.api_key = api_key or os.getenv("ASSEMBLYAI_API_KEY")
        if not self.api_key:
            raise ValueError("AssemblyAI API key is required")

        self.sample_rate = sample_rate
        self.format_turns = format_turns
        self.speech_model = speech_model
        self.min_turn_silence = min_turn_silence
        self.max_turn_silence = max_turn_silence
        self._ws: ClientConnection | None = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._last_completed_turn_order: int | None = None

    def _parse_message(self, message: dict[str, Any]) -> STTEvent | None:
        msg_type = message.get("type")

        # Instant VAD signal when user starts speaking (barge-in trigger)
        if msg_type == "SpeechStarted":
            return SpeechStartedEvent.create()

        if msg_type != "Turn":
            return None

        transcript = str(message.get("transcript") or "").strip()
        if not transcript:
            return None

        end_of_turn = bool(message.get("end_of_turn", False))
        turn_is_formatted = bool(message.get("turn_is_formatted", False))
        turn_order = message.get("turn_order")

        # In-progress speech or awaiting final formatting
        if not end_of_turn or (self.format_turns and not turn_is_formatted):
            return STTChunkEvent.create(transcript)

        # Completed turn: deduplicate against the last completed turn order
        if turn_order is not None and turn_order == self._last_completed_turn_order:
            return None

        if turn_order is not None:
            self._last_completed_turn_order = turn_order
        return STTOutputEvent.create(transcript)

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
                        try:
                            message = json.loads(raw_message)
                            if "error" in message:
                                print(f"AssemblyAI STT error: {message['error']}")
                                break

                            event = self._parse_message(message)
                            if event is not None:
                                yield event
                        except json.JSONDecodeError as e:
                            print(f"[DEBUG] AssemblyAI STT JSON decode error: {e}")
                            continue
                except ConnectionClosed:
                    print("AssemblyAI STT: WebSocket connection closed")

    async def send_audio(self, audio_chunk: bytes) -> None:
        ws = await self._ensure_connection()
        await ws.send(audio_chunk)

    async def close(self) -> None:
        if self._ws is not None and self._ws.close_code is None:
            await self._ws.close()
        self._ws = None
        self._last_completed_turn_order = None
        self._close_signal.set()

    async def _ensure_connection(self) -> ClientConnection:
        if self._close_signal.is_set():
            raise RuntimeError(
                "AssemblyAI STT tried establishing a connection after it was closed"
            )
        if self._ws is not None and self._ws.close_code is None:
            return self._ws

        params = urlencode(
            {
                "speech_model": self.speech_model,
                "sample_rate": self.sample_rate,
                "format_turns": str(self.format_turns).lower(),
                "min_turn_silence": self.min_turn_silence,
                "max_turn_silence": self.max_turn_silence,
            }
        )
        url = f"wss://streaming.assemblyai.com/v3/ws?{params}"
        ws = await connect(url, additional_headers={"Authorization": self.api_key})
        self._ws = ws
        self._connection_signal.set()
        return ws


async def stt_stream(
    audio_stream: AsyncIterator[bytes | VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Audio / Control Events → Voice Events

    Connects to AssemblyAI v3 streaming WebSocket with VAD and turn detection.
    - Yields SpeechStartedEvent when user voice activity begins (barge-in).
    - Yields STTChunkEvent for partial transcripts during speaking.
    - Yields STTOutputEvent for finalized conversation turns.
    - Passes through non-audio control events (e.g. InterruptEvent) concurrently.
    """
    stt = AssemblyAISTT(
        sample_rate=16000,
        speech_model="universal-3-6-pro",
        min_turn_silence=200,
        max_turn_silence=1000,
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
