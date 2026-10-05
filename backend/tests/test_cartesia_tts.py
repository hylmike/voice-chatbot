"""Unit tests for Cartesia TTS service."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptEvent,
    SpeechStartedEvent,
    TTSChunkEvent,
)
from api.services.cartesia_tts import CartesiaTTS, tts_stream


def test_cartesia_init_missing_key() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValueError, match="Cartesia API key is required"),
    ):
        CartesiaTTS(api_key=None)


def test_generate_context_id() -> None:
    tts = CartesiaTTS(api_key="test_key")
    ctx1 = tts._generate_context_id()
    ctx2 = tts._generate_context_id()
    assert ctx1.startswith("ctx_")
    assert ctx2.startswith("ctx_")
    assert ctx1 != ctx2
    assert tts._context_counter == 2


def test_parse_message() -> None:
    raw_audio = b"pcm_audio_sample_bytes"
    encoded = base64.b64encode(raw_audio).decode("ascii")

    # Valid audio message
    event = CartesiaTTS._parse_message({"data": encoded})
    assert isinstance(event, TTSChunkEvent)
    assert event.audio == raw_audio

    # Missing or empty data
    assert CartesiaTTS._parse_message({"data": ""}) is None
    assert CartesiaTTS._parse_message({}) is None
    assert CartesiaTTS._parse_message({"data": 1234}) is None


async def test_cartesia_cancel() -> None:
    tts = CartesiaTTS(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None
    tts._ws = mock_ws

    await tts.cancel()
    mock_ws.close.assert_awaited_once()
    assert tts._ws is None


async def test_cartesia_close() -> None:
    tts = CartesiaTTS(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None
    tts._ws = mock_ws

    await tts.close()
    mock_ws.close.assert_awaited_once()
    assert tts._ws is None
    assert tts._close_signal.is_set()


async def test_ensure_connection_after_close() -> None:
    tts = CartesiaTTS(api_key="test_key")
    await tts.close()
    with pytest.raises(RuntimeError, match="after it was closed"):
        await tts._ensure_connection()


async def test_send_text_empty() -> None:
    tts = CartesiaTTS(api_key="test_key")
    with patch.object(tts, "_ensure_connection") as mock_ensure:
        await tts.send_text(None)
        await tts.send_text("")
        await tts.send_text("   ")
        mock_ensure.assert_not_called()


async def test_send_text_valid() -> None:
    tts = CartesiaTTS(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None

    with patch.object(tts, "_ensure_connection", return_value=mock_ws):
        await tts.send_text("Hello there")
        mock_ws.send.assert_awaited_once()


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

    with patch("api.services.cartesia_tts.CartesiaTTS", return_value=mock_tts_instance):
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
