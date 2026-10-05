"""Voice Agent Event Types

Python implementation of the voice agent event system.
All events in the pipeline share common properties to enable
consistent handling, logging, and debugging across the system.

This module defines Pydantic models for all events that flow through
the voice agent pipeline, from user audio input through STT, agent
processing, and TTS output.
"""

import base64
import time
from typing import Literal

from pydantic import BaseModel, Field

from .chat import ChatRequest, ChatResponse


def _now_ms() -> int:
    """Returns the current time in milliseconds."""
    return int(time.time() * 1000)


class BaseEvent(BaseModel):
    """Base model for all voice agent events."""

    type: str = Field(description="Event type identifier.")
    ts: int = Field(
        default_factory=_now_ms,
        description="Unix timestamp (milliseconds since epoch) when the event was created.",
    )


class UserInputEvent(BaseEvent):
    """Event emitted when raw audio data is received from the user.

    This is the entry point of the voice agent pipeline. Audio should be
    in PCM format (16-bit, mono, 16kHz) for optimal processing by the STT stage.
    """

    type: Literal["user_input"] = Field(
        default="user_input",
        description="Event type identifier.",
    )
    audio: bytes = Field(
        ...,
        description=(
            "Raw PCM audio bytes from the user's microphone.\n"
            "Expected format: 16-bit signed integer, mono channel, 16kHz sample rate."
        ),
    )

    @classmethod
    def create(cls, audio: bytes) -> "UserInputEvent":
        """Factory method to create UserInputEvent from raw audio with current timestamp."""
        return cls(type="user_input", audio=audio, ts=_now_ms())


class SpeechStartedEvent(BaseEvent):
    """Event emitted by STT Voice Activity Detection (VAD) when user speech begins.

    This signal is fired immediately when the user begins speaking, allowing
    downstream consumers (agent, TTS, and frontend playback) to detect barge-in
    and interrupt ongoing speech without waiting for a completed transcript.
    """

    type: Literal["speech_started"] = Field(
        default="speech_started",
        description="Event type identifier.",
    )

    @classmethod
    def create(cls) -> "SpeechStartedEvent":
        """Factory method to create SpeechStartedEvent with current timestamp."""
        return cls(type="speech_started", ts=_now_ms())


class InterruptEvent(BaseEvent):
    """Event emitted when an active assistant response is interrupted.

    Triggered either by user speech barge-in (SpeechStarted) or an explicit
    interrupt action from the client.
    """

    type: Literal["interrupt"] = Field(
        default="interrupt",
        description="Event type identifier.",
    )

    @classmethod
    def create(cls) -> "InterruptEvent":
        """Factory method to create InterruptEvent with current timestamp."""
        return cls(type="interrupt", ts=_now_ms())


class STTChunkEvent(BaseEvent):
    """Event emitted during speech-to-text processing for partial transcription results.

    STT services often provide incremental results as they process audio.
    These chunks allow for real-time display of transcription progress to the user,
    improving perceived responsiveness even before the final transcript is ready.
    """

    type: Literal["stt_chunk"] = Field(
        default="stt_chunk",
        description="Event type identifier.",
    )
    transcript: str = Field(
        ...,
        description=(
            "Partial transcript text from the STT service.\n"
            "This may be revised as more audio context becomes available.\n"
            "Not guaranteed to be the final transcription."
        ),
    )

    @classmethod
    def create(cls, transcript: str) -> "STTChunkEvent":
        """Factory method to create STTChunkEvent from raw audio bytes."""
        return cls(type="stt_chunk", transcript=transcript, ts=_now_ms())


class STTOutputEvent(BaseEvent):
    """Event emitted when speech-to-text processing completes for a turn.

    This represents the final, formatted transcription of the user's speech.
    Unlike STTChunkEvent, this is the complete and finalized transcript that will
    be sent to the agent for processing.
    """

    type: Literal["stt_output"] = Field(
        default="stt_output",
        description="Event type identifier.",
    )
    transcript: str = Field(
        ...,
        description=(
            "Final, complete transcript of the user's speech for this turn.\n"
            "This is the text that will be processed by the LLM agent."
        ),
    )

    @classmethod
    def create(cls, transcript: str) -> "STTOutputEvent":
        """Factory method to create STTOutputEvent from raw audio bytes."""
        return cls(type="stt_output", transcript=transcript, ts=_now_ms())


STTEvent = SpeechStartedEvent | STTChunkEvent | STTOutputEvent


class AgentChunkEvent(BaseEvent):
    """Event emitted during agent response generation for streaming text chunks.

    As the LLM generates its response, it streams tokens incrementally.
    These chunks enable real-time display of the agent's response and allow
    the TTS stage to begin synthesis before the complete response is generated,
    reducing overall latency.
    """

    type: Literal["agent_chunk"] = Field(
        default="agent_chunk",
        description="Event type identifier.",
    )
    text: str = Field(
        ...,
        description=(
            "Partial text chunk from the agent's streaming response.\n"
            "Multiple chunks combine to form the complete agent output."
        ),
    )

    @classmethod
    def create(cls, text: str) -> "AgentChunkEvent":
        """Factory method to create AgentChunkEvent from raw audio bytes with current timestamp."""
        return cls(type="agent_chunk", text=text, ts=_now_ms())


class AgentEndEvent(BaseEvent):
    """Event emitted when the agent has finished generating its response for a turn.

    This signals downstream consumers (like TTS) that no more text is coming
    for this turn, and they should flush any buffered content."""

    type: Literal["agent_end"] = Field(
        default="agent_end",
        description="Event type identifier.",
    )

    @classmethod
    def create(cls) -> "AgentEndEvent":
        """Factory method to create AgentEndEvent with current timestamp."""
        return cls(type="agent_end", ts=_now_ms())


class ToolCallEvent(BaseEvent):
    """Event emitted when the agent invokes a tool.

    This event provides visibility into the agent's decision-making process,
    showing which tools are being called and with what arguments."""

    type: Literal["tool_call"] = Field(
        default="tool_call",
        description="Event type identifier.",
    )

    id: str = Field(
        description="Unique identifier for this tool invocation.",
    )

    name: str = Field(
        description="Name of the tool being invoked.",
    )

    args: dict = Field(
        description="Arguments passed to the tool call.",
    )

    @classmethod
    def create(cls, tool_id: str, name: str, args: dict) -> "ToolCallEvent":
        """Factory method to create ToolCallEvent with current timestamp."""
        return cls(type="tool_call", id=tool_id, name=name, args=args, ts=_now_ms())


class ToolResultEvent(BaseEvent):
    """Event emitted when a tool completes execution and returns a result.

    This event contains the output from the tool, allowing tracking of
    the full tool execution lifecycle."""

    type: Literal["tool_result"] = Field(
        default="tool_result",
        description="Event type identifier.",
    )

    tool_call_id: str = Field(
        description="The tool call ID this result corresponds to.",
    )

    name: str = Field(
        description="Name of the tool being invoked.",
    )

    result: str = Field(
        description="Result returned by the tool.",
    )

    @classmethod
    def create(cls, tool_call_id: str, name: str, result: str) -> "ToolResultEvent":
        """Factory method to create ToolResultEvent with current timestamp."""
        return cls(
            type="tool_result",
            tool_call_id=tool_call_id,
            name=name,
            result=result,
            ts=_now_ms(),
        )


"""
Union type of all agent-related events.

This type encompasses all events emitted during agent processing, including
streaming text chunks, tool invocations, and completion signals. It enables
type-safe handling of the various stages of agent response generation.
"""
AgentEvent = AgentChunkEvent | AgentEndEvent | ToolCallEvent | ToolResultEvent


class TTSChunkEvent(BaseEvent):
    """Event emitted during text-to-speech synthesis for streaming audio chunks.

    As the TTS service synthesizes speech, it streams audio incrementally.
    These chunks enable real-time playback of the agent's response, allowing
    audio to begin playing before the complete synthesis is finished, which
    significantly improves perceived responsiveness.
    """

    type: Literal["tts_chunk"] = Field(
        default="tts_chunk",
        description="Event type identifier.",
    )

    audio: bytes = Field(
        description="""PCM audio bytes synthesized from the agent's text response.
    Format: 16-bit signed integer, mono channel, 24kHz sample rate.
    Encoded as base64 when serialized to JSON for transmission.
    Can be played immediately as it arrives for low-latency audio output.
    """,
    )

    @classmethod
    def create(cls, audio: bytes) -> "TTSChunkEvent":
        """Factory method to create TTSChunkEvent with current timestamp."""
        return cls(type="tts_chunk", audio=audio, ts=_now_ms())


VoiceAgentEvent = UserInputEvent | STTEvent | AgentEvent | TTSChunkEvent | InterruptEvent


def event_to_dict(event: VoiceAgentEvent) -> dict:
    """Convert a VoiceAgentEvent to a JSON-serializable dictionary."""
    match event:
        case (
            UserInputEvent(type=t, ts=ts)
            | AgentEndEvent(type=t, ts=ts)
            | SpeechStartedEvent(type=t, ts=ts)
            | InterruptEvent(type=t, ts=ts)
        ):
            return {"type": t, "ts": ts}
        case (
            STTChunkEvent(type=t, transcript=transcript, ts=ts)
            | STTOutputEvent(type=t, transcript=transcript, ts=ts)
        ):
            return {"type": t, "transcript": transcript, "ts": ts}
        case AgentChunkEvent(type=t, text=text, ts=ts):
            return {"type": t, "text": text, "ts": ts}
        case ToolCallEvent(type=t, id=tool_id, name=name, args=args, ts=ts):
            return {
                "type": t,
                "toolId": tool_id,
                "name": name,
                "args": args,
                "ts": ts,
            }
        case ToolResultEvent(
            type=t, tool_call_id=tool_call_id, name=name, result=result, ts=ts
        ):
            return {
                "type": t,
                "toolCallId": tool_call_id,
                "name": name,
                "result": result,
                "ts": ts,
            }
        case TTSChunkEvent(type=t, audio=audio, ts=ts):
            return {
                "type": t,
                "audio": base64.b64encode(audio).decode("ascii"),
                "ts": ts,
            }
        case _:
            raise TypeError(f"Unknown event type: {type(event)}")


__all__ = [
    "AgentChunkEvent",
    "AgentEndEvent",
    "AgentEvent",
    "BaseEvent",
    "ChatRequest",
    "ChatResponse",
    "InterruptEvent",
    "STTChunkEvent",
    "STTEvent",
    "STTOutputEvent",
    "SpeechStartedEvent",
    "TTSChunkEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "UserInputEvent",
    "VoiceAgentEvent",
    "event_to_dict",
]
