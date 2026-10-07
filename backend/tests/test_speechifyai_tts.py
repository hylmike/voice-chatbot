"""Unit tests for Speechify AI TTS service."""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptEvent,
    SpeechStartedEvent,
    TTSChunkEvent,
)
from api.services.speechifyai_tts import SpeechifyAITTS, SpeechifyTTS, tts_stream


def test_speechify_init_missing_key() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValueError, match="Speechify API key is required"),
    ):
        SpeechifyTTS(api_key=None)


def test_alias_is_speechify_tts() -> None:
    assert SpeechifyAITTS is SpeechifyTTS


def test_generate_request_and_context_id() -> None:
    tts = SpeechifyTTS(api_key="test_key")
    req1 = tts._generate_request_id()
    req2 = tts._generate_context_id()
    assert req1.startswith("req_")
    assert req2.startswith("req_")
    assert req1 != req2
    assert tts._request_counter == 2


def test_parse_chunk() -> None:
    raw_audio = b"pcm_audio_sample_bytes"
    event = SpeechifyTTS._parse_chunk(raw_audio)
    assert isinstance(event, TTSChunkEvent)
    assert event.audio == raw_audio

    assert SpeechifyTTS._parse_chunk(None) is None
    assert SpeechifyTTS._parse_chunk(b"") is None


def test_parse_message() -> None:
    raw_audio = b"pcm_audio_sample_bytes"
    encoded = base64.b64encode(raw_audio).decode("ascii")

    # Valid dict with base64 data
    event = SpeechifyTTS._parse_message({"data": encoded})
    assert isinstance(event, TTSChunkEvent)
    assert event.audio == raw_audio

    # Valid dict with audio key
    event2 = SpeechifyTTS._parse_message({"audio": encoded})
    assert isinstance(event2, TTSChunkEvent)
    assert event2.audio == raw_audio

    # Valid direct bytes
    event3 = SpeechifyTTS._parse_message(raw_audio)
    assert isinstance(event3, TTSChunkEvent)
    assert event3.audio == raw_audio

    # Invalid base64 string
    assert SpeechifyTTS._parse_message({"data": "invalid_base64!!!"}) is None

    # Missing or empty data
    assert SpeechifyTTS._parse_message({"data": ""}) is None
    assert SpeechifyTTS._parse_message({}) is None
    assert SpeechifyTTS._parse_message({"data": 1234}) is None


async def test_speechify_cancel() -> None:
    tts = SpeechifyTTS(api_key="test_key")
    mock_response = AsyncMock()
    tts._active_response = mock_response

    await tts.cancel()
    mock_response.aclose.assert_awaited_once()
    assert tts._active_response is None
    assert tts._cancel_signal.is_set()


async def test_speechify_close() -> None:
    tts = SpeechifyTTS(api_key="test_key")
    mock_response = AsyncMock()
    mock_client = AsyncMock()
    mock_client.is_closed = False
    tts._active_response = mock_response
    tts._client = mock_client

    await tts.close()
    mock_response.aclose.assert_awaited_once()
    mock_client.aclose.assert_awaited_once()
    assert tts._active_response is None
    assert tts._client is None
    assert tts._close_signal.is_set()


async def test_ensure_client_after_close() -> None:
    tts = SpeechifyTTS(api_key="test_key")
    await tts.close()
    with pytest.raises(RuntimeError, match="after it was closed"):
        await tts._ensure_client()


async def test_send_text_empty() -> None:
    tts = SpeechifyTTS(api_key="test_key")
    with patch.object(tts, "_ensure_client") as mock_ensure:
        await tts.send_text(None)
        await tts.send_text("")
        await tts.send_text("   ")
        mock_ensure.assert_not_called()


async def test_send_text_after_close() -> None:
    tts = SpeechifyTTS(api_key="test_key")
    await tts.close()
    with pytest.raises(RuntimeError, match="after it was closed"):
        await tts.send_text("Hello")


async def test_send_text_valid() -> None:
    tts = SpeechifyTTS(api_key="test_key", language="en-US")
    mock_client = AsyncMock()
    mock_client.build_request = MagicMock()
    mock_response = AsyncMock()
    mock_client.send = AsyncMock(return_value=mock_response)

    with patch.object(tts, "_ensure_client", return_value=mock_client):
        await tts.send_text("Hello Speechify")
        mock_client.build_request.assert_called_once()
        call_kwargs = mock_client.build_request.call_args.kwargs
        assert call_kwargs["json"]["input"] == "Hello Speechify"
        assert call_kwargs["json"]["model"] == "simba-3.2"
        assert call_kwargs["json"]["voice_id"] == "geffen_32"
        assert call_kwargs["json"]["output_format"] == "pcm_24000"
        assert call_kwargs["json"]["language"] == "en-US"
        assert "Speechify-Request-Id" in call_kwargs["headers"]
        mock_client.send.assert_awaited_once()
        assert tts._active_response is mock_response
        assert tts._connection_signal.is_set()


async def test_receive_events_streaming() -> None:
    tts = SpeechifyTTS(api_key="test_key", chunk_size=8)

    mock_response = AsyncMock()
    mock_response.is_error = False

    async def mock_aiter_bytes():
        yield b"chunk_"
        yield b"01chunk_"
        yield b"02"

    mock_response.aiter_bytes = mock_aiter_bytes
    tts._active_response = mock_response
    tts._connection_signal.set()

    received = []
    async for event in tts.receive_events():
        received.append(event)
        if len(received) == 2:
            break

    await tts.close()
    assert len(received) == 2
    assert received[0].audio == b"chunk_01"
    assert received[1].audio == b"chunk_02"


async def test_receive_events_trailing_buffer() -> None:
    tts = SpeechifyTTS(api_key="test_key", chunk_size=8)

    mock_response = AsyncMock()
    mock_response.is_error = False

    async def mock_aiter_bytes():
        # 11 bytes: 8 bytes full chunk + 3 bytes remainder (rounded down to 2 bytes for 16-bit PCM)
        yield b"12345678abc"

    mock_response.aiter_bytes = mock_aiter_bytes
    tts._active_response = mock_response
    tts._connection_signal.set()

    received = []
    async for event in tts.receive_events():
        received.append(event)
        if len(received) == 2:
            break

    await tts.close()
    assert len(received) == 2
    assert received[0].audio == b"12345678"
    assert received[1].audio == b"ab"


async def test_receive_events_error_response() -> None:
    tts = SpeechifyTTS(api_key="test_key")

    mock_response = AsyncMock()
    mock_response.is_error = True
    mock_response.status_code = 400
    mock_response.aread = AsyncMock(return_value=b'{"error": "bad request"}')
    tts._active_response = mock_response
    tts._connection_signal.set()

    events = []

    async def run_receive():
        async for event in tts.receive_events():
            events.append(event)

    task = asyncio.create_task(run_receive())
    await asyncio.sleep(0.01)
    await tts.close()
    await task

    assert len(events) == 0


async def test_receive_events_stream_closed_during_cancellation() -> None:
    tts = SpeechifyTTS(api_key="test_key", chunk_size=8)

    mock_response = AsyncMock()
    mock_response.is_error = False

    async def mock_aiter_bytes():
        yield b"chunk_01"
        await tts.cancel()
        raise httpx.StreamClosed()

    mock_response.aiter_bytes = mock_aiter_bytes
    tts._active_response = mock_response
    tts._connection_signal.set()

    received = []

    async def run_receive():
        async for event in tts.receive_events():
            received.append(event)

    task = asyncio.create_task(run_receive())
    await asyncio.sleep(0.01)
    await tts.close()
    await task

    assert len(received) == 1
    assert received[0].audio == b"chunk_01"


async def test_receive_events_unexpected_stream_error_uncancelled() -> None:
    tts = SpeechifyTTS(api_key="test_key", chunk_size=8)

    mock_response = AsyncMock()
    mock_response.is_error = False

    async def mock_aiter_bytes():
        yield b"chunk_01"
        raise httpx.ReadError("Network connection abruptly dropped")

    mock_response.aiter_bytes = mock_aiter_bytes
    tts._active_response = mock_response
    tts._connection_signal.set()

    received = []

    async def run_receive():
        async for event in tts.receive_events():
            received.append(event)

    task = asyncio.create_task(run_receive())
    await asyncio.sleep(0.01)
    await tts.close()
    await task

    assert len(received) == 1
    assert received[0].audio == b"chunk_01"


async def test_tts_stream_buffering_and_interruption() -> None:
    mock_tts_instance = MagicMock()
    mock_tts_instance.send_text = AsyncMock()
    mock_tts_instance.cancel = AsyncMock()
    mock_tts_instance.close = AsyncMock()

    async def mock_receive_events():
        yield TTSChunkEvent.create(b"audio1")

    mock_tts_instance.receive_events = mock_receive_events

    async def input_events():
        # First turn: normal chunks and end
        yield AgentChunkEvent.create("Hello ")
        yield AgentChunkEvent.create("world!")
        yield AgentEndEvent.create()
        # Second turn: interrupted mid-stream
        yield AgentChunkEvent.create("Should be cancelled")
        yield InterruptEvent.create()
        # Third turn: speech started barge-in
        yield AgentChunkEvent.create("Another cancelled")
        yield SpeechStartedEvent.create()

    with patch(
        "api.services.speechifyai_tts.SpeechifyTTS", return_value=mock_tts_instance
    ):
        events = [e async for e in tts_stream(input_events())]

        types = [e.type for e in events]
        assert "tts_chunk" in types
        assert "agent_chunk" in types
        assert "agent_end" in types
        assert "interrupt" in types
        assert "speech_started" in types

        # verify first turn sent merged text
        mock_tts_instance.send_text.assert_awaited_once_with("Hello world!")
        # verify cancel was called on interrupt and speech_started
        assert mock_tts_instance.cancel.await_count == 2
        mock_tts_instance.close.assert_awaited_once()


async def test_merge_async_iters_with_speechify_stream_closed_on_interrupt() -> None:
    tts = SpeechifyTTS(api_key="test_key", chunk_size=8)

    mock_client = AsyncMock()
    mock_client.build_request = MagicMock()
    mock_response = AsyncMock()
    mock_response.is_error = False

    async def mock_aiter_bytes():
        yield b"chunk_01"
        while not tts._cancel_signal.is_set():
            await asyncio.sleep(0.001)
        raise httpx.StreamClosed()

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_client.send = AsyncMock(return_value=mock_response)

    async def mock_ensure():
        return mock_client

    tts._ensure_client = mock_ensure

    async def input_events():
        yield AgentChunkEvent.create("Hello")
        yield AgentEndEvent.create()
        await asyncio.sleep(0.01)
        yield SpeechStartedEvent.create()

    events = []
    with patch("api.services.speechifyai_tts.SpeechifyTTS", return_value=tts):
        async for e in tts_stream(input_events()):
            events.append(e)
            if isinstance(e, SpeechStartedEvent):
                break

    types = [e.type for e in events]
    assert "agent_chunk" in types
    assert "agent_end" in types
    assert "tts_chunk" in types
    assert "speech_started" in types
