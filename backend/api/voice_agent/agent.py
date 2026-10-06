import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableGenerator
from langgraph.checkpoint.memory import InMemorySaver

from ..schemas.events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptEvent,
    SpeechStartedEvent,
    STTOutputEvent,
    ToolCallEvent,
    ToolResultEvent,
    VoiceAgentEvent,
)
from ..services.assemblyai_stt import stt_stream
from ..services.cartesia_prompts import CARTESIA_TTS_SYSTEM_PROMPT
from ..services.speechifyai_tts import tts_stream
from .tools import tavily_search

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)
load_dotenv()

system_prompt = f"""
You are Lingxi AI, a helpful, conversational text and voice AI assistant. Your goal is to answer user questions clearly, naturally, and concisely.

You have access to the `tavily_search` web search tool to find current information, recent news, real-time facts, weather, sports scores, stock prices, and up-to-date data.
- Use `tavily_search` whenever answering questions that require real-time, recent, or specific verifiable information.
- Answer directly using your own general knowledge and reasoning for common questions, explanations, brainstorming, or casual conversation.
- Keep your spoken responses concise and conversational (typically 1 to 3 sentences) unless the user specifically asks for more detail.
- Speak in plain text suitable for both voice output and screen display. Do not use markdown formatting (such as bolding, asterisks, bullet points, or headers), never include raw XML or SSML tags (such as <break .../>, <speed .../>, or <spell>), and never read raw URLs out loud. Rely on standard punctuation (commas, periods) for natural pauses.

{CARTESIA_TTS_SYSTEM_PROMPT}
"""

agent = create_agent(
    model="google_genai:gemini-3.7-flash",
    tools=[tavily_search],
    system_prompt=system_prompt,
    checkpointer=InMemorySaver(),
)


async def agent_stream(  # noqa: PLR0915
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Voice Events → Voice Events (with Agent Responses)

    Runs event reading concurrently with agent generation to enable instant
    interruption (barge-in) and turn cancellation.
    - When SpeechStartedEvent arrives (user starts speaking), any active agent
      generation is cancelled immediately.
    - When InterruptEvent arrives (user interrupts), active agent generation is cancelled.
    - When STTOutputEvent arrives, active generation is cancelled and the new turn begins.
    """
    thread_id = str(uuid4())
    out_queue: asyncio.Queue[VoiceAgentEvent | object] = asyncio.Queue()
    sentinel = object()
    active_agent_task: asyncio.Task | None = None

    async def run_agent(transcript: str) -> None:
        try:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            stream = agent.astream(
                {"messages": [HumanMessage(content=transcript)]},
                config=config,
                stream_mode="messages",
            )

            async for message, _metadata in stream:
                if isinstance(message, AIMessage):
                    if message.text:
                        await out_queue.put(AgentChunkEvent.create(message.text))
                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_id = tool_call.get("id") or str(uuid4())
                            tool_name = tool_call.get("name") or "unknown"
                            tool_args = tool_call.get("args") or {}
                            await out_queue.put(
                                ToolCallEvent.create(
                                    tool_id=str(tool_id),
                                    name=str(tool_name),
                                    args=tool_args
                                    if isinstance(tool_args, dict)
                                    else {},
                                )
                            )

                if isinstance(message, ToolMessage):
                    await out_queue.put(
                        ToolResultEvent.create(
                            tool_call_id=getattr(message, "tool_call_id", None) or "",
                            name=getattr(message, "name", None) or "unknown",
                            result=str(message.content) if message.content else "",
                        )
                    )

            await out_queue.put(AgentEndEvent.create())
        except asyncio.CancelledError:
            # Turn was interrupted mid-generation
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] Agent execution error: {e}")
            await out_queue.put(AgentEndEvent.create())

    async def cancel_active_agent() -> None:
        nonlocal active_agent_task
        if active_agent_task and not active_agent_task.done():
            active_agent_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active_agent_task
        active_agent_task = None

    async def process_upstream_events() -> None:
        nonlocal active_agent_task
        try:
            async for event in event_stream:
                # Barge-in or explicit interrupt: cancel active agent generation immediately
                if isinstance(event, (SpeechStartedEvent, InterruptEvent)):
                    await cancel_active_agent()
                    await out_queue.put(event)
                    continue

                # Pass through all other events downstream
                await out_queue.put(event)

                # When a final user transcript arrives, cancel any leftover task & start new response
                if isinstance(event, STTOutputEvent):
                    await cancel_active_agent()
                    active_agent_task = asyncio.create_task(run_agent(event.transcript))
        finally:
            if active_agent_task and not active_agent_task.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await active_agent_task
            await out_queue.put(sentinel)

    process_task = asyncio.create_task(process_upstream_events())

    try:
        while True:
            item = await out_queue.get()
            if item is sentinel:
                break
            yield item  # type: ignore[misc]
    finally:
        process_task.cancel()
        await cancel_active_agent()
        with contextlib.suppress(asyncio.CancelledError):
            await process_task


pipeline = (
    RunnableGenerator(stt_stream)
    | RunnableGenerator(agent_stream)
    | RunnableGenerator(tts_stream)
)
