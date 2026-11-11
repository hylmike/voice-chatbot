"""Unit tests for Deepgram Flux STT service (/v2/listen)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import ConnectionClosed

from api.schemas.events import (
    InterruptEvent,
    SpeechStartedEvent,
    STTChunkEvent,
    STTOutputEvent,
)
from api.services.deepgram_stt import DeepgramFluxSTT, DeepgramSTT, stt_stream


def test_deepgram_stt_init_missing_key() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValueError, match="Deepgram API key is required"),
    ):
        DeepgramFluxSTT(api_key=None)


def test_alias_is_deepgram_flux_stt() -> None:
    assert DeepgramSTT is DeepgramFluxSTT


def test_build_url_parameters() -> None:
    stt = DeepgramFluxSTT(
        api_key="test_key",
        model="flux-general-en",
        sample_rate=16000,
        eot_threshold=0.75,
        eager_eot_threshold=0.4,
        eot_timeout_ms=4000,
    )
    url = stt._build_url()
    assert url.startswith("wss://api.deepgram.com/v2/listen?")
    assert "model=flux-general-en" in url
    assert "encoding=linear16" in url
    assert "sample_rate=16000" in url
    assert "eot_threshold=0.75" in url
    assert "eager_eot_threshold=0.4" in url
    assert "eot_timeout_ms=4000" in url


def test_parse_messages_start_of_turn() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")

    # StartOfTurn with initial transcript emits both SpeechStartedEvent and STTChunkEvent
    events = stt._parse_messages(
        {
            "type": "TurnInfo",
            "event": "StartOfTurn",
            "turn_index": 0,
            "transcript": "Hi I",
        }
    )
    assert len(events) == 2
    assert isinstance(events[0], SpeechStartedEvent)
    assert isinstance(events[1], STTChunkEvent)
    assert events[1].transcript == "Hi I"

    # Single-event helper returns SpeechStartedEvent first
    single = stt._parse_message({"type": "TurnInfo", "event": "StartOfTurn"})
    assert isinstance(single, SpeechStartedEvent)


def test_parse_messages_non_turn_ignored() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")
    assert stt._parse_messages({"type": "Connected"}) == []
    assert stt._parse_messages({"type": "Warning", "code": "WARN"}) == []
    assert stt._parse_messages({"type": "TurnInfo"}) == []
    assert stt._parse_messages({"type": "TurnInfo", "event": "UnknownEvent"}) == []
    assert stt._parse_message({"type": "Connected"}) is None


def test_parse_messages_update_and_eager_events() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")

    # Empty Update is ignored
    assert stt._parse_messages({"event": "Update", "transcript": "   "}) == []

    # Non-empty Update, EagerEndOfTurn, and TurnResumed emit STTChunkEvent
    for evt_name in ("Update", "EagerEndOfTurn", "TurnResumed"):
        res = stt._parse_messages(
            {"type": "TurnInfo", "event": evt_name, "transcript": "Hello world"}
        )
        assert len(res) == 1
        assert isinstance(res[0], STTChunkEvent)
        assert res[0].transcript == "Hello world"


def test_parse_messages_end_of_turn_and_deduplication() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")

    # Empty EndOfTurn ignored
    assert stt._parse_messages({"event": "EndOfTurn", "transcript": ""}) == []

    # First EndOfTurn for turn_index 0
    out1 = stt._parse_messages(
        {
            "type": "TurnInfo",
            "event": "EndOfTurn",
            "turn_index": 0,
            "transcript": "Cancel my subscription.",
            "trigger": "model",
        }
    )
    assert len(out1) == 1
    assert isinstance(out1[0], STTOutputEvent)
    assert out1[0].transcript == "Cancel my subscription."

    # Duplicate turn_index 0 is ignored
    dup = stt._parse_messages(
        {
            "type": "TurnInfo",
            "event": "EndOfTurn",
            "turn_index": 0,
            "transcript": "Cancel my subscription.",
            "trigger": "model",
        }
    )
    assert dup == []

    # Next turn_index 1 succeeds
    out2 = stt._parse_messages(
        {
            "type": "TurnInfo",
            "event": "EndOfTurn",
            "turn_index": 1,
            "transcript": "Thank you.",
            "trigger": "model",
        }
    )
    assert len(out2) == 1
    assert isinstance(out2[0], STTOutputEvent)
    assert out2[0].transcript == "Thank you."


async def test_deepgram_stt_force_end_turn_and_close() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None
    stt._ws = mock_ws

    await stt.force_end_turn()
    mock_ws.send.assert_awaited_once_with(json.dumps({"type": "ForceEndTurn"}))

    await stt.close()
    mock_ws.close.assert_awaited_once()
    assert stt._ws is None
    assert stt._close_signal.is_set()


async def test_ensure_connection_and_after_close() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None

    with patch(
        "api.services.deepgram_stt.connect", AsyncMock(return_value=mock_ws)
    ) as mock_connect:
        ws = await stt._ensure_connection()
        assert ws is mock_ws
        mock_connect.assert_awaited_once()
        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs["additional_headers"] == {"Authorization": "Token test_key"}

        # Calling again reuses open connection
        ws2 = await stt._ensure_connection()
        assert ws2 is mock_ws
        assert mock_connect.await_count == 1

    await stt.close()
    with pytest.raises(RuntimeError, match="after it was closed"):
        await stt._ensure_connection()


async def test_send_audio() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None

    with patch.object(stt, "_ensure_connection", return_value=mock_ws) as mock_ensure:
        await stt.send_audio(b"")
        mock_ensure.assert_not_called()

        await stt.send_audio(b"pcm_audio_bytes")
        mock_ws.send.assert_awaited_once_with(b"pcm_audio_bytes")


async def test_receive_events_loop() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")

    class FakeWS:
        close_code = None

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield b"ignored_binary"
            yield "not_json"
            yield json.dumps(
                {
                    "type": "TurnInfo",
                    "event": "StartOfTurn",
                    "turn_index": 0,
                    "transcript": "Hello",
                }
            )
            yield json.dumps(
                {
                    "type": "TurnInfo",
                    "event": "EndOfTurn",
                    "turn_index": 0,
                    "transcript": "Hello there.",
                }
            )
            yield json.dumps({"type": "Error", "description": "stream closed"})

        async def send(self, _data):
            pass

        async def close(self):
            self.close_code = 1000

    stt._ws = FakeWS()  # type: ignore[assignment]
    stt._connection_signal.set()

    received = []
    async for evt in stt.receive_events():
        received.append(evt)
        if len(received) == 3:
            await stt.close()
            break

    assert len(received) == 3
    assert isinstance(received[0], SpeechStartedEvent)
    assert isinstance(received[1], STTChunkEvent)
    assert isinstance(received[2], STTOutputEvent)


async def test_receive_events_connection_closed() -> None:
    stt = DeepgramFluxSTT(api_key="test_key")

    class ClosedWS:
        close_code = None

        def __aiter__(self):
            return self

        async def __anext__(self):
            await stt.close()
            raise ConnectionClosed(None, None)

        async def send(self, _data):
            pass

        async def close(self):
            self.close_code = 1000

    stt._ws = ClosedWS()  # type: ignore[assignment]
    stt._connection_signal.set()

    events = [evt async for evt in stt.receive_events()]
    assert events == []


async def test_stt_stream_passthrough_and_events() -> None:
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
        await asyncio.sleep(0.01)

    with patch(
        "api.services.deepgram_stt.DeepgramFluxSTT", return_value=mock_stt_instance
    ):
        events = [event async for event in stt_stream(input_stream())]

        types = [e.type for e in events]
        assert "speech_started" in types
        assert "interrupt" in types
        assert "stt_chunk" in types
        assert "stt_output" in types
        assert mock_stt_instance.send_audio.await_count == 2
        mock_stt_instance.close.assert_awaited()
