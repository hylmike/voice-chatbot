"""Unit tests for agent streaming and turn cancellation."""

import asyncio
from unittest.mock import MagicMock, patch

from langchain.messages import AIMessage, ToolMessage

from api.schemas.events import (
    AgentChunkEvent,
    InterruptEvent,
    SpeechStartedEvent,
    STTChunkEvent,
    STTOutputEvent,
    ToolCallEvent,
    ToolResultEvent,
    UserInputEvent,
)
from api.voice_agent.agent import agent_stream


async def test_agent_stream_passthrough_events() -> None:
    async def input_events():
        yield UserInputEvent.create(b"sample_pcm")
        yield STTChunkEvent.create("partial words")

    events = [e async for e in agent_stream(input_events())]
    assert len(events) == 2
    assert events[0].type == "user_input"
    assert events[1].type == "stt_chunk"


async def test_agent_stream_execution_and_tool_events() -> None:
    ai_msg_with_tool = AIMessage(
        content="Let me look up the weather.",
        tool_calls=[
            {"id": "call_abc", "name": "tavily_search", "args": {"query": "weather"}}
        ],
    )

    tool_msg = ToolMessage(
        tool_call_id="call_abc",
        name="tavily_search",
        content="Sunny and 24 degrees.",
    )

    ai_final = AIMessage(content="It is sunny and 24 degrees outside.")

    async def mock_astream(*args, **kwargs):
        yield ai_msg_with_tool, {}
        yield tool_msg, {}
        yield ai_final, {}

    mock_agent = MagicMock()
    mock_agent.astream = mock_astream

    async def input_events():
        yield STTOutputEvent.create("What is the weather?")

    with patch("api.voice_agent.agent.agent", mock_agent):
        events = [e async for e in agent_stream(input_events())]

        types = [e.type for e in events]
        assert "stt_output" in types
        assert "agent_chunk" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "agent_end" in types

        # Find tool call event
        tc = next(e for e in events if isinstance(e, ToolCallEvent))
        assert tc.id == "call_abc"
        assert tc.name == "tavily_search"

        # Find tool result event
        tr = next(e for e in events if isinstance(e, ToolResultEvent))
        assert tr.tool_call_id == "call_abc"
        assert tr.result == "Sunny and 24 degrees."

        # Find chunks
        chunks = [e.text for e in events if isinstance(e, AgentChunkEvent)]
        assert "Let me look up the weather." in chunks
        assert "It is sunny and 24 degrees outside." in chunks


async def test_agent_stream_cancellation_on_interrupt() -> None:
    # Test that when agent is generating slowly, an interrupt event cancels the generation
    cancelled = False

    async def slow_astream(*args, **kwargs):
        nonlocal cancelled
        try:
            yield AIMessage(content="Starting response..."), {}
            await asyncio.sleep(0.5)
            yield AIMessage(content="Should not reach here"), {}
        except asyncio.CancelledError:
            cancelled = True
            raise

    mock_agent = MagicMock()
    mock_agent.astream = slow_astream

    async def input_events():
        yield STTOutputEvent.create("Hello")
        await asyncio.sleep(0.05)
        yield InterruptEvent.create()

    with patch("api.voice_agent.agent.agent", mock_agent):
        events = [e async for e in agent_stream(input_events())]

        types = [e.type for e in events]
        assert "stt_output" in types
        assert "interrupt" in types
        assert cancelled is True


async def test_agent_stream_cancellation_on_speech_started() -> None:
    cancelled = False

    async def slow_astream(*args, **kwargs):
        nonlocal cancelled
        try:
            yield AIMessage(content="Beginning to speak..."), {}
            await asyncio.sleep(0.5)
            yield AIMessage(content="Should be cut off"), {}
        except asyncio.CancelledError:
            cancelled = True
            raise

    mock_agent = MagicMock()
    mock_agent.astream = slow_astream

    async def input_events():
        yield STTOutputEvent.create("Question 1")
        await asyncio.sleep(0.05)
        # User starts speaking again
        yield SpeechStartedEvent.create()

    with patch("api.voice_agent.agent.agent", mock_agent):
        events = [e async for e in agent_stream(input_events())]

        types = [e.type for e in events]
        assert "stt_output" in types
        assert "speech_started" in types
        assert cancelled is True
