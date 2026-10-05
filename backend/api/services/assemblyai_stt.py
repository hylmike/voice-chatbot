"""AssemblyAI Real-Time Streaming STT Transform

Python implementation that mirrors the TypeScript AssemblyAISTTTransform.
Connects to AssemblyAI's v3 WebSocket API for streaming speech-to-text.

Input: PCM 16-bit audio buffer (bytes)
Output: STT events (stt_chunk for partials, stt_output for final transcripts)
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

from ..schemas.events import STTChunkEvent, STTEvent, STTOutputEvent, VoiceAgentEvent


class AssemblyAISTT:
    def __init__(
        self,
        api_key: str | None = None,
        sample_rate: int = 16000,
        format_turns: bool = True,
    ) -> None:
        self.api_key = api_key or os.getenv("ASSEMBLYAI_API_KEY")
        if not self.api_key:
            raise ValueError("AssemblyAI API key is required")

        self.sample_rate = sample_rate
        self.format_turns = format_turns
        self._ws: ClientConnection | None = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._last_completed_turn_order: int | None = None

    def _parse_message(self, message: dict[str, Any]) -> STTEvent | None:
        if message.get("type") != "Turn":
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
                "sample_rate": self.sample_rate,
                "format_turns": str(self.format_turns).lower(),
            }
        )
        url = f"wss://streaming.assemblyai.com/v3/ws?{params}"
        ws = await connect(url, additional_headers={"Authorization": self.api_key})
        self._ws = ws
        self._connection_signal.set()
        return ws


async def stt_stream(
    audio_stream: AsyncIterator[bytes],
) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Audio (Bytes) → Voice Events (VoiceAgentEvent)

    This function takes a stream of audio chunks and sends them to AssemblyAI for STT.

    It uses a producer-consumer pattern where:
    - Producer: A background task reads audio chunks from audio_stream and sends
      them to AssemblyAI via WebSocket. This runs concurrently with the consumer,
      allowing transcription to begin before all audio has arrived.
    - Consumer: The main coroutine receives transcription events from AssemblyAI
      and yields them downstream. Events include both partial results (stt_chunk)
      and final transcripts (stt_output).

    Args:
        audio_stream: Async iterator of PCM audio bytes (16-bit, mono, 16kHz)

    Yields:
        STT events (stt_chunk for partials, stt_output for final transcripts)
    """

    stt = AssemblyAISTT(sample_rate=16000)

    async def send_audio():
        """
        Background task that pumps audio chunks to AssemblyAI.

        This runs concurrently with the main coroutine, continuously reading
        audio chunks from the input stream and forwarding them to AssemblyAI.
        When the input stream ends, it signals completion by closing the
        WebSocket connection.
        """

        try:
            # stream each audio chunk to AssemblyAI as it arrives
            async for audio_chunk in audio_stream:
                await stt.send_audio(audio_chunk)
        finally:
            await stt.close()

    # Launch the audio sending task in the background
    # This allows us to simultaneously receive transcripts in the main coroutine
    send_task = asyncio.create_task(send_audio())

    try:
        # Consumer loop: receive and yield transcription events as they arrive
        # from AssemblyAI. The receive_events() method listens on the WebSocket
        # for transcript events and yields them as they become available.
        async for event in stt.receive_events():
            yield event
    finally:
        # Cleanup: ensure the background task is canceled and awaited
        with contextlib.suppress(asyncio.CancelledError):
            send_task.cancel()
            await send_task
        # Ensure the websocket connection is closed
        await stt.close()
