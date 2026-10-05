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
    STTOutputEvent,
    ToolCallEvent,
    ToolResultEvent,
    VoiceAgentEvent,
)
from ..services.assemblyai_stt import stt_stream
from ..services.cartesia_prompts import CARTESIA_TTS_SYSTEM_PROMPT
from ..services.cartesia_tts import tts_stream
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


async def agent_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """Transform stream: Voice Events → Voice Events (with Agent Responses)

    This function takes a stream of upstream voice agent events and processes them.
    When a stt_output event arrives, it passes the transcript to the LangChain agent.
    The agent streams back its response tokens as agent_chunk events.
    Tool calls and results are also emitted as separate events.
    All others upstream events are passed through unchanged.

    The passthrough pattern ensures downstream stages (like TTS) can observe all
    events in the pipeline, not just the ones this stage produces. This enables
    features like displaying partial transcripts while the agent is thinking.

    Args:
        event_stream: An async iterator of upstream voice agent events

    Yields:
        All upstream events plus agent_chunk, tool_call, and tool_result events
    """
    # Generate a unique thread ID for this conversation session
    # This allows the agent to maintain conversation context across multiple turns
    # using the checkpointer (InMemorySaver) configured in the agent
    thread_id = str(uuid4())

    # Process each event as it arrives from the upstream STT stage
    async for event in event_stream:
        # Pass through all events to downstream consumers
        yield event

        # When we receive a final transcript, invoke the agent
        if isinstance(event, STTOutputEvent):
            # Stream the agent's response using LangChain's astream method.
            # stream_mode="messages" yields message chunks as they're generated.
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            stream = agent.astream(
                {"messages": [HumanMessage(content=event.transcript)]},
                config=config,
                stream_mode="messages",
            )

            # Iterate through the agent's streaming response. The stream yields
            # tuples of (message, metadata), but we only need the message.
            async for message, _metadata in stream:
                # Emit agent chunks (AI messages)
                if isinstance(message, AIMessage):
                    # Extract and yield the text content from each message chunk
                    if message.text:
                        yield AgentChunkEvent.create(message.text)
                    # Emit tool calls if present
                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_id = tool_call.get("id") or str(uuid4())
                            tool_name = tool_call.get("name") or "unknown"
                            tool_args = tool_call.get("args") or {}
                            yield ToolCallEvent.create(
                                tool_id=str(tool_id),
                                name=str(tool_name),
                                args=tool_args if isinstance(tool_args, dict) else {},
                            )

                # Emit tool results (tool messages)
                if isinstance(message, ToolMessage):
                    yield ToolResultEvent.create(
                        tool_call_id=getattr(message, "tool_call_id", None) or "",
                        name=getattr(message, "name", None) or "unknown",
                        result=str(message.content) if message.content else "",
                    )

            # Signal that the agent has finished responding for this turn
            yield AgentEndEvent.create()


pipeline = (
    RunnableGenerator(stt_stream)
    | RunnableGenerator(agent_stream)
    | RunnableGenerator(tts_stream)
)
