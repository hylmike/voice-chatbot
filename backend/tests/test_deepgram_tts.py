"""Unit tests for Deepgram Flux TTS service (/v2/speak)."""

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import ConnectionClosed

from api.schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptEvent,
    SpeechStartedEvent,
    TTSChunkEvent,
)
from api.services.deepgram_tts import DeepgramFluxTTS, DeepgramTTS, tts_stream


def test_deepgram_tts_init_missing_key() -> None:
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValueError, match="Deepgram API key is required"),
    ):
        DeepgramFluxTTS(api_key=None)


def test_alias_is_deepgram_flux_tts() -> None:
    assert DeepgramTTS is DeepgramFluxTTS


def test_build_url() -> None:
    tts = DeepgramFluxTTS(
        api_key="test_key",
        model="flux-wade-en",
        encoding="linear16",
        sample_rate=24000,
        speed=1.1,
        expressivity=1,
    )
    url = tts._build_url()
    assert url.startswith("wss://api.deepgram.com/v2/speak?")
    assert "model=flux-wade-en" in url
    assert "encoding=linear16" in url
    assert "sample_rate=24000" in url
    assert "speed=1.1" in url
    assert "expressivity=1" in url


def test_parse_audio_chunk_and_messages() -> None:
    tts = DeepgramFluxTTS(api_key="test_key")

    # Even-length PCM binary frame
    raw_pcm = b"\x01\x02\x03\x04"
    evt = tts._parse_message(raw_pcm)
    assert isinstance(evt, TTSChunkEvent)
    assert evt.audio == raw_pcm

    # Odd-length PCM binary frame is aligned to 16-bit boundary
    odd_pcm = b"\x01\x02\x03\x04\x05"
    evt_odd = tts._parse_message(odd_pcm)
    assert isinstance(evt_odd, TTSChunkEvent)
    assert evt_odd.audio == b"\x01\x02\x03\x04"

    # Single byte or empty is ignored
    assert tts._parse_message(b"\x01") is None
    assert tts._parse_message(b"") is None
    assert tts._parse_message(None) is None

    # Lifecycle messages update state and return None
    tts._discard_audio = True
    assert tts._parse_message({"type": "SpeechStarted", "speech_id": "s1"}) is None
    assert tts._discard_audio is False
    assert tts._turn_active is True

    assert tts._parse_message({"type": "SpeechMetadata", "speech_id": "s1"}) is None
    assert tts._turn_active is False

    assert tts._parse_message({"type": "Error", "description": "bad model"}) is None

    # Base64 JSON fallback
    encoded = base64.b64encode(raw_pcm).decode("ascii")
    evt_b64 = tts._parse_message({"data": encoded})
    assert isinstance(evt_b64, TTSChunkEvent)
    assert evt_b64.audio == raw_pcm
    assert tts._parse_message({"data": "!!!not_base64!!!"}) is None

    # Discarded when _discard_audio is True
    tts._discard_audio = True
    assert tts._parse_message(raw_pcm) is None


async def test_send_text_flush_configure_and_cancel() -> None:
    tts = DeepgramFluxTTS(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None

    with patch.object(tts, "_ensure_connection", return_value=mock_ws) as mock_ensure:
        # Empty text does not open connection
        await tts.send_text(None)
        await tts.send_text("   ")
        mock_ensure.assert_not_called()

        # Valid Speak message
        await tts.send_text("Hello world")
        mock_ws.send.assert_awaited_once_with(
            json.dumps({"type": "Speak", "text": "Hello world"})
        )
        assert tts._turn_active is True

        # Empty text with flush=True when turn is active flushes
        tts._ws = mock_ws
        await tts.send_text("", flush=True)
        assert mock_ws.send.call_args.args[0] == json.dumps({"type": "Flush"})

        # Configure mid-stream speed
        await tts.configure(1.15)
        assert mock_ws.send.call_args.args[0] == json.dumps(
            {"type": "Configure", "speed": 1.15}
        )

        # Cancel sends Interrupt when turn is active
        await tts.cancel()
        assert tts._discard_audio is True
        assert tts._turn_active is False
        assert mock_ws.send.call_args.args[0] == json.dumps({"type": "Interrupt"})


async def test_send_text_with_flush_flag() -> None:
    tts = DeepgramFluxTTS(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None
    tts._ws = mock_ws

    with patch.object(tts, "_ensure_connection", return_value=mock_ws):
        await tts.send_text("Done.", flush=True)
        assert mock_ws.send.await_count == 2
        assert mock_ws.send.call_args_list[0].args[0] == json.dumps(
            {"type": "Speak", "text": "Done."}
        )
        assert mock_ws.send.call_args_list[1].args[0] == json.dumps({"type": "Flush"})


async def test_ensure_connection_and_close() -> None:
    tts = DeepgramFluxTTS(api_key="test_key")
    mock_ws = AsyncMock()
    mock_ws.close_code = None

    with patch(
        "api.services.deepgram_tts.connect", AsyncMock(return_value=mock_ws)
    ) as mock_connect:
        ws = await tts._ensure_connection()
        assert ws is mock_ws
        mock_connect.assert_awaited_once()
        assert mock_connect.call_args.kwargs["additional_headers"] == {
            "Authorization": "Token test_key"
        }

        # Reuse active connection
        ws2 = await tts._ensure_connection()
        assert ws2 is mock_ws
        assert mock_connect.await_count == 1

    await tts.close()
    mock_ws.close.assert_awaited_once()
    assert tts._ws is None
    assert tts._close_signal.is_set()

    with pytest.raises(RuntimeError, match="after it was closed"):
        await tts._ensure_connection()


async def test_receive_events_binary_and_json() -> None:
    tts = DeepgramFluxTTS(api_key="test_key")

    class FakeSpeakWS:
        close_code = None

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield json.dumps({"type": "SpeechStarted", "speech_id": "turn_1"})
            yield b"\x10\x20\x30\x40"
            yield "invalid_json"
            yield json.dumps({"type": "Flushed", "speech_id": "turn_1"})
            yield json.dumps({"type": "SpeechMetadata", "speech_id": "turn_1"})

        async def send(self, _data):
            pass

        async def close(self):
            self.close_code = 1000

    tts._ws = FakeSpeakWS()  # type: ignore[assignment]
    tts._connection_signal.set()

    received = []
    async for evt in tts.receive_events():
        received.append(evt)
        if len(received) == 1:
            await tts.close()
            break

    assert len(received) == 1
    assert received[0].audio == b"\x10\x20\x30\x40"


async def test_receive_events_connection_closed() -> None:
    tts = DeepgramFluxTTS(api_key="test_key")

    class ClosedSpeakWS:
        close_code = 1006

        def __aiter__(self):
            return self

        async def __anext__(self):
            await tts.close()
            raise ConnectionClosed(None, None)

        async def send(self, _data):
            pass

        async def close(self):
            pass

    tts._ws = ClosedSpeakWS()  # type: ignore[assignment]
    tts._ws.close_code = None  # type: ignore[attr-defined]
    tts._connection_signal.set()

    events = [evt async for evt in tts.receive_events()]
    assert events == []


async def test_tts_stream_token_streaming_and_interruption() -> None:
    mock_tts_instance = MagicMock()
    mock_tts_instance.send_text = AsyncMock()
    mock_tts_instance.flush = AsyncMock()
    mock_tts_instance.cancel = AsyncMock()
    mock_tts_instance.close = AsyncMock()

    async def mock_receive_events():
        yield TTSChunkEvent.create(b"\x01\x02\x03\x04")

    mock_tts_instance.receive_events = mock_receive_events

    async def input_events():
        # First turn: streaming chunks and flush on AgentEndEvent
        yield AgentChunkEvent.create("Hello world.")
        yield AgentChunkEvent.create("How are you?")
        yield AgentEndEvent.create()
        # Second turn: interrupted mid-stream
        yield AgentChunkEvent.create("Should be interrupted")
        yield InterruptEvent.create()
        # Third turn: speech started barge-in
        yield AgentChunkEvent.create("Another interrupted")
        yield SpeechStartedEvent.create()
        await asyncio.sleep(0.01)

    with patch(
        "api.services.deepgram_tts.DeepgramFluxTTS", return_value=mock_tts_instance
    ):
        events = [e async for e in tts_stream(input_events())]

        types = [e.type for e in events]
        assert "tts_chunk" in types
        assert "agent_chunk" in types
        assert "agent_end" in types
        assert "interrupt" in types
        assert "speech_started" in types

        # First chunk sent verbatim, second chunk prefixed with a space for sentence-boundary safety
        sent_texts = [
            call.args[0] for call in mock_tts_instance.send_text.call_args_list
        ]
        assert sent_texts[0] == "Hello world."
        assert sent_texts[1] == " How are you?"
        mock_tts_instance.flush.assert_awaited_once()
        assert mock_tts_instance.cancel.await_count == 2
        mock_tts_instance.close.assert_awaited_once()
