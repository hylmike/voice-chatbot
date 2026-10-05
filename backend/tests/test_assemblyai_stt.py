"""Unit tests for AssemblyAI STT service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.schemas.events import (
    InterruptEvent,
    SpeechStartedEvent,
    STTChunkEvent,
    STTOutputEvent,
)
from api.services.assemblyai_stt import AssemblyAISTT, stt_stream


def test_assemblyai_init_missing_key() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValueError, match="AssemblyAI API key is required"),
    ):
        AssemblyAISTT(api_key=None)


def test_parse_message_speech_started() -> None:
    stt = AssemblyAISTT(api_key="test_key")
    event = stt._parse_message({"type": "SpeechStarted", "timestamp": 1234})
    assert isinstance(event, SpeechStartedEvent)
    assert event.type == "speech_started"


def test_parse_message_non_turn_ignored() -> None:
    stt = AssemblyAISTT(api_key="test_key")
    assert stt._parse_message({"type": "SessionBegins"}) is None
    assert stt._parse_message({"type": "OtherEvent"}) is None


def test_parse_message_empty_transcript() -> None:
    stt = AssemblyAISTT(api_key="test_key")
    assert stt._parse_message({"type": "Turn", "transcript": ""}) is None
    assert stt._parse_message({"type": "Turn", "transcript": "   "}) is None


def test_parse_message_stt_chunk() -> None:
    stt = AssemblyAISTT(api_key="test_key", format_turns=True)

    # In-progress turn
    chunk1 = stt._parse_message(
        {"type": "Turn", "transcript": "Hello world", "end_of_turn": False}
    )
    assert isinstance(chunk1, STTChunkEvent)
    assert chunk1.transcript == "Hello world"

    # End of turn but not formatted yet
    chunk2 = stt._parse_message(
        {
            "type": "Turn",
            "transcript": "Hello world",
            "end_of_turn": True,
            "turn_is_formatted": False,
        }
    )
    assert isinstance(chunk2, STTChunkEvent)
    assert chunk2.transcript == "Hello world"


def test_parse_message_stt_output_and_deduplication() -> None:
    stt = AssemblyAISTT(api_key="test_key", format_turns=True)

    # Completed turn
    out1 = stt._parse_message(
        {
            "type": "Turn",
            "transcript": "Hello world.",
            "end_of_turn": True,
            "turn_is_formatted": True,
            "turn_order": 1,
        }
    )
    assert isinstance(out1, STTOutputEvent)
    assert out1.transcript == "Hello world."

    # Duplicate turn_order
    dup = stt._parse_message(
        {
            "type": "Turn",
            "transcript": "Hello world.",
            "end_of_turn": True,
            "turn_is_formatted": True,
            "turn_order": 1,
        }
    )
    assert dup is None

    # Next turn
    out2 = stt._parse_message(
        {
            "type": "Turn",
            "transcript": "How are you?",
            "end_of_turn": True,
            "turn_is_formatted": True,
            "turn_order": 2,
        }
    )
    assert isinstance(out2, STTOutputEvent)
    assert out2.transcript == "How are you?"


async def test_assemblyai_close() -> None:
    stt = AssemblyAISTT(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None
    stt._ws = mock_ws

    await stt.close()
    mock_ws.close.assert_awaited_once()
    assert stt._ws is None
    assert stt._close_signal.is_set()


async def test_ensure_connection_after_close() -> None:
    stt = AssemblyAISTT(api_key="test_key")
    await stt.close()
    with pytest.raises(RuntimeError, match="after it was closed"):
        await stt._ensure_connection()


async def test_send_audio() -> None:
    stt = AssemblyAISTT(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None

    with patch.object(stt, "_ensure_connection", return_value=mock_ws):
        await stt.send_audio(b"audio_bytes")
        mock_ws.send.assert_awaited_once_with(b"audio_bytes")


async def test_stt_stream_passthrough_and_events() -> None:
    # Test that stt_stream receives control events and passes them through,
    # and forwards STT events from AssemblyAISTT.
    mock_stt_instance = MagicMock()
    mock_stt_instance.send_audio = AsyncMock()
    mock_stt_instance.close = AsyncMock()

    async def mock_receive_events():
        yield SpeechStartedEvent.create()
        yield STTChunkEvent.create("testing")
        yield STTOutputEvent.create("testing finalized")

    mock_stt_instance.receive_events = mock_receive_events

    async def input_stream():
        yield b"chunk1"
        yield InterruptEvent.create()
        yield b"chunk2"

    with patch(
        "api.services.assemblyai_stt.AssemblyAISTT", return_value=mock_stt_instance
    ):
        events = [event async for event in stt_stream(input_stream())]

        types = [e.type for e in events]
        assert "speech_started" in types
        assert "interrupt" in types
        assert "stt_chunk" in types
        assert "stt_output" in types
        assert mock_stt_instance.send_audio.await_count == 2
