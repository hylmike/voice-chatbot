"""Unit tests for schemas: events and chat."""

import base64

import pytest

from api.schemas.chat import ChatRequest, ChatResponse
from api.schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    BaseEvent,
    InterruptEvent,
    SpeechStartedEvent,
    STTChunkEvent,
    STTOutputEvent,
    ToolCallEvent,
    ToolResultEvent,
    TTSChunkEvent,
    UserInputEvent,
    event_to_dict,
)


def test_chat_request_and_response() -> None:
    req = ChatRequest(user_message="Hello", thread_id="t-123")
    assert req.user_message == "Hello"
    assert req.thread_id == "t-123"

    res = ChatResponse(response="Hi there!", thread_id="t-123")
    assert res.response == "Hi there!"
    assert res.thread_id == "t-123"


def test_event_factories_and_attributes() -> None:
    # UserInputEvent
    audio_data = b"\x00\x01\x02\x03"
    u_evt = UserInputEvent.create(audio_data)
    assert u_evt.type == "user_input"
    assert u_evt.audio == audio_data
    assert isinstance(u_evt.ts, int)

    # SpeechStartedEvent
    sp_evt = SpeechStartedEvent.create()
    assert sp_evt.type == "speech_started"
    assert isinstance(sp_evt.ts, int)

    # InterruptEvent
    int_evt = InterruptEvent.create()
    assert int_evt.type == "interrupt"
    assert isinstance(int_evt.ts, int)

    # STTChunkEvent
    chunk_evt = STTChunkEvent.create("thinking about")
    assert chunk_evt.type == "stt_chunk"
    assert chunk_evt.transcript == "thinking about"

    # STTOutputEvent
    out_evt = STTOutputEvent.create("weather in Paris")
    assert out_evt.type == "stt_output"
    assert out_evt.transcript == "weather in Paris"

    # AgentChunkEvent
    ag_chunk = AgentChunkEvent.create("It is sunny")
    assert ag_chunk.type == "agent_chunk"
    assert ag_chunk.text == "It is sunny"

    # AgentEndEvent
    ag_end = AgentEndEvent.create()
    assert ag_end.type == "agent_end"

    # ToolCallEvent
    tool_call = ToolCallEvent.create(
        tool_id="call_1", name="tavily_search", args={"query": "Paris weather"}
    )
    assert tool_call.type == "tool_call"
    assert tool_call.id == "call_1"
    assert tool_call.name == "tavily_search"
    assert tool_call.args == {"query": "Paris weather"}

    # ToolResultEvent
    tool_res = ToolResultEvent.create(
        tool_call_id="call_1", name="tavily_search", result="Sunny 22C"
    )
    assert tool_res.type == "tool_result"
    assert tool_res.tool_call_id == "call_1"
    assert tool_res.name == "tavily_search"
    assert tool_res.result == "Sunny 22C"

    # TTSChunkEvent
    pcm_audio = b"\xff\x00\xee\x11"
    tts_chunk = TTSChunkEvent.create(pcm_audio)
    assert tts_chunk.type == "tts_chunk"
    assert tts_chunk.audio == pcm_audio


def test_event_to_dict_serialization() -> None:
    # UserInputEvent
    u_dict = event_to_dict(UserInputEvent.create(b"123"))
    assert u_dict["type"] == "user_input"
    assert "ts" in u_dict

    # SpeechStartedEvent
    sp_dict = event_to_dict(SpeechStartedEvent.create())
    assert sp_dict == {"type": "speech_started", "ts": sp_dict["ts"]}

    # InterruptEvent
    int_dict = event_to_dict(InterruptEvent.create())
    assert int_dict == {"type": "interrupt", "ts": int_dict["ts"]}

    # STTChunkEvent
    sc_dict = event_to_dict(STTChunkEvent.create("hello"))
    assert sc_dict["type"] == "stt_chunk"
    assert sc_dict["transcript"] == "hello"

    # STTOutputEvent
    so_dict = event_to_dict(STTOutputEvent.create("hello world"))
    assert so_dict["type"] == "stt_output"
    assert so_dict["transcript"] == "hello world"

    # AgentChunkEvent
    ac_dict = event_to_dict(AgentChunkEvent.create("chunk"))
    assert ac_dict["type"] == "agent_chunk"
    assert ac_dict["text"] == "chunk"

    # AgentEndEvent
    ae_dict = event_to_dict(AgentEndEvent.create())
    assert ae_dict["type"] == "agent_end"

    # ToolCallEvent
    tc_dict = event_to_dict(
        ToolCallEvent.create(tool_id="t1", name="search", args={"q": "hi"})
    )
    assert tc_dict["type"] == "tool_call"
    assert tc_dict["toolId"] == "t1"
    assert tc_dict["name"] == "search"
    assert tc_dict["args"] == {"q": "hi"}

    # ToolResultEvent
    tr_dict = event_to_dict(
        ToolResultEvent.create(tool_call_id="t1", name="search", result="ok")
    )
    assert tr_dict["type"] == "tool_result"
    assert tr_dict["toolCallId"] == "t1"
    assert tr_dict["name"] == "search"
    assert tr_dict["result"] == "ok"

    # TTSChunkEvent
    raw_bytes = b"sample_pcm_audio"
    tts_dict = event_to_dict(TTSChunkEvent.create(raw_bytes))
    assert tts_dict["type"] == "tts_chunk"
    assert tts_dict["audio"] == base64.b64encode(raw_bytes).decode("ascii")


def test_event_to_dict_invalid_type() -> None:
    class DummyEvent(BaseEvent):
        pass

    with pytest.raises(TypeError, match="Unknown event type"):
        event_to_dict(DummyEvent(type="custom"))  # type: ignore[arg-type]
