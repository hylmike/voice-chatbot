# Deepgram Flux Voice Agent — Detailed System Design Document

## 1. Executive Summary

This document defines the architecture, data flow, protocol contracts, state machines, and operational characteristics of the **Deepgram Flux Voice Agent** (`deepgram_voice_agent`). The system is a full-duplex, real-time conversational voice and text AI application combining a [React](https://react.dev/) + [Vite](https://vite.dev/) Web Audio frontend with a [FastAPI](https://fastapi.tiangolo.com/) and [LangChain](https://python.langchain.com/) backend powered by:

- **Speech-to-Text (STT) & Native Turn Detection**: [Deepgram Flux STT (`/v2/listen`)](https://developers.deepgram.com/docs/flux/quickstart) using the English conversational speech model (`flux-general-en`, [Models & Languages Overview](https://developers.deepgram.com/docs/models-languages-overview)) and model-integrated turn-taking ([Understanding the Flux State Machine](https://developers.deepgram.com/docs/flux/state)).
- **Conversational Agent & Reasoning**: [Google Gemini 3.7 Flash](https://ai.google.dev/gemini-api/docs) orchestrated via [LangGraph](https://langchain-ai.github.io/langgraph/) with stateful in-memory thread checkpointing (`InMemorySaver`) and real-time web search via [Tavily Search](https://tavily.com/).
- **Text-to-Speech (TTS) & Conversational Synthesis**: [Deepgram Flux TTS (`/v2/speak`)](https://developers.deepgram.com/docs/flux-tts/overview) using the English conversational voice model (`flux-haley-en`, [Flux TTS Voices & Languages](https://developers.deepgram.com/docs/flux-tts/voices)) with token-level streaming, cross-turn prosody persistence, and instant barge-in interruption ([Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages)).

---

## 2. End-to-End System Architecture

### 2.1 High-Level Topology

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Frontend (React + Vite + Web Audio)                  │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌────────────────────┐  │
│  │ Mic Audio Capture    │  │ Live UI & Transcript │  │ 24kHz PCM Audio    │  │
│  │ 16kHz 16-bit Mono PCM│  │ + Tool Call Inspector│  │ Playback Engine    │  │
│  └──────────┬───────────┘  └──────────▲───────────┘  └─────────▲──────────┘  │
└─────────────┼─────────────────────────┼────────────────────────┼─────────────┘
              │ Binary PCM / Interrupt  │ JSON Events            │ Base64 PCM
              ▼                         │                        │
┌───────────────────────────────────────┴────────────────────────┴─────────────┐
│                     Backend FastAPI Server (api/server.py)                   │
│                         WebSocket (/ws) & REST (/chat)                       │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                 LangChain RunnableGenerator Pipeline                   │  │
│  │                 pipeline = stt_stream | agent_stream | tts_stream      │  │
│  │                                                                        │  │
│  │  ┌────────────────────┐   ┌────────────────────┐   ┌────────────────┐  │  │
│  │  │ DeepgramFluxSTT    │──▶│ Gemini 3.7 Flash   │──▶│ DeepgramFluxTTS│  │  │
│  │  │ (deepgram_stt.py)  │   │ + Tavily Search    │   │(deepgram_tts.py│  │  │
│  │  └─────────▲──────────┘   └────────────────────┘   └────────▲───────┘  │  │
│  └────────────┼────────────────────────────────────────────────┼──────────┘  │
└───────────────┼────────────────────────────────────────────────┼─────────────┘
                │ wss://api.deepgram.com/v2/listen               │ wss://api.deepgram.com/v2/speak
                │ (model=flux-general-en, 16kHz linear16)        │ (model=flux-haley-en, 24kHz linear16)
                ▼                                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Deepgram Flux Cloud Runtime                         │
│   - TurnInfo State Machine (StartOfTurn, Update, EagerEndOfTurn, EndOfTurn)  │
│   - Conversational TTS Turn Loop (Speak, Flush, Interrupt, SpeechMetadata)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Core Architectural Principles

1. **Unmodified Frontend & Transport Contract**: The browser client connects to `ws://localhost:3100/ws` for voice streaming and `POST http://localhost:3100/chat` for text fallback. All frontend event schemas (`speech_started`, `stt_chunk`, `stt_output`, `agent_chunk`, `agent_end`, `tool_call`, `tool_result`, `tts_chunk`, `interrupt`) remain identical to the original `voice_chatbot` contract.
2. **Unified Deepgram Flux Speech Stack**: Replacing separate legacy STT and TTS vendors with [Deepgram Flux STT](https://developers.deepgram.com/docs/flux/quickstart) and [Deepgram Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart) consolidates authentication under a single `DEEPGRAM_API_KEY` (`Authorization: Token <DEEPGRAM_API_KEY>`) and pairs conversation-native turn detection (`~260ms` end-of-turn latency, [Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)) with streaming-first speech synthesis ([Flux TTS Overview](https://developers.deepgram.com/docs/flux-tts/overview)).
3. **Concurrent Async Generator Pipeline**: The backend voice pipeline chains three `RunnableGenerator` stages (`stt_stream | agent_stream | tts_stream`). Each stage runs producer/consumer tasks concurrently via `asyncio.Queue` and `merge_async_iters`, ensuring that upstream barge-in events (`SpeechStartedEvent` or `InterruptEvent`) immediately cancel in-flight LLM generation and interrupt active TTS synthesis without head-of-line blocking.

---

## 3. Component Design

### 3.1 Deepgram Flux STT Service (`backend/api/services/deepgram_stt.py`)

#### Connection & Audio Format Specification
Per [Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart) and [Getting Started with Speech to Text](https://developers.deepgram.com/docs/stt/getting-started), Flux STT is served exclusively on the `/v2/listen` WebSocket endpoint (`/v1/listen` does not support Flux models):

| Parameter | Configured Value | Specification & Purpose |
| :--- | :--- | :--- |
| **Endpoint** | `wss://api.deepgram.com/v2/listen` | Dedicated v2 conversational STT WebSocket endpoint ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |
| **Authentication** | `Authorization: Token <DEEPGRAM_API_KEY>` | HTTP upgrade header using the project's Deepgram API token ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |
| **`model`** | `flux-general-en` | English conversational STT model with integrated end-of-turn detection ([Models & Languages Overview](https://developers.deepgram.com/docs/models-languages-overview)). |
| **`encoding`** | `linear16` | Uncontainerized 16-bit little-endian signed PCM audio ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |
| **`sample_rate`** | `16000` | 16kHz mono audio matching the Web Audio microphone capture graph ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |
| **`eot_threshold`** | `0.7` (default, range `0.5 - 1.0`) | Confidence threshold required to fire an `EndOfTurn` event ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |
| **`eager_eot_threshold`** | `None` (optional, range `0.3 - 0.9`) | Optional threshold to enable speculative `EagerEndOfTurn` and `TurnResumed` events ([Optimize Voice Agent Latency with Eager End of Turn](https://developers.deepgram.com/docs/flux/voice-agent-eager-eot)). |
| **`eot_timeout_ms`** | `5000` (default, range `500 - 60000`) | Maximum silence duration in milliseconds before forcing an `EndOfTurn` ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |

#### Flux State Machine & Event Mapping
As documented in [Understanding the Flux State Machine](https://developers.deepgram.com/docs/flux/state), Deepgram Flux emits `TurnInfo` JSON frames carrying an `event` discriminator, `turn_index`, `transcript`, `words`, and `end_of_turn_confidence`. `DeepgramFluxSTT._parse_messages()` maps these state transitions into internal `VoiceAgentEvent` instances:

```text
Deepgram Flux /v2/listen Event          Internal Pipeline Event(s)                 Downstream Effect
──────────────────────────────────────  ─────────────────────────────────────────  ──────────────────────────────────────────────────────────
{"event": "StartOfTurn", ...}       ─▶  SpeechStartedEvent + STTChunkEvent         Cancels active LLM task, sends Interrupt to TTS, halts UI playback, shows initial words
{"event": "Update", ...}            ─▶  STTChunkEvent(transcript)                  Updates live interim transcript preview in UI (~250ms cadence)
{"event": "EagerEndOfTurn", ...}    ─▶  STTChunkEvent(transcript)                  Updates interim transcript preview at medium EOT confidence
{"event": "TurnResumed", ...}       ─▶  STTChunkEvent(transcript)                  Continues interim transcript preview when user keeps speaking
{"event": "EndOfTurn", ...}         ─▶  STTOutputEvent(transcript)                 Deduplicates by turn_index and triggers Gemini agent turn
```

- **Native Barge-In (`StartOfTurn`)**: Per [Understanding the Flux State Machine](https://developers.deepgram.com/docs/flux/state), `StartOfTurn` is Deepgram's recommended barge-in signal because every `StartOfTurn` is guaranteed to correspond to actual decoded speech rather than transient background noise. When `StartOfTurn` arrives, `DeepgramFluxSTT` immediately emits `SpeechStartedEvent` followed by an `STTChunkEvent` containing the initial decoded words.
- **Turn Deduplication (`turn_index`)**: `EndOfTurn` increments `turn_index` after each completed turn ([Understanding the Flux State Machine](https://developers.deepgram.com/docs/flux/state)). `DeepgramFluxSTT` tracks `_last_completed_turn_index` to guarantee each user turn triggers the LLM agent at most once.
- **Manual Turn Override (`ForceEndTurn`) & Graceful Shutdown (`CloseStream`)**: `DeepgramFluxSTT.force_end_turn()` supports sending `{"type": "ForceEndTurn"}` to finalize an in-progress turn on demand ([Force End Turn](https://developers.deepgram.com/docs/flux/force-end-turn)), and `close()` sends `{"type": "CloseStream"}` before closing the WebSocket.

---

### 3.2 Conversational Agent & Tooling (`backend/api/voice_agent/agent.py`)

- **Model & Checkpointing**: Uses `create_agent` with `google_genai:gemini-3.7-flash` ([Google Gemini API Docs](https://ai.google.dev/gemini-api/docs)) and `InMemorySaver` ([LangGraph Documentation](https://langchain-ai.github.io/langgraph/)) keyed by `thread_id` so multi-turn voice sessions retain conversational memory.
- **Voice-First System Prompt (`deepgram_prompts.py`)**: Incorporates `DEEPGRAM_TTS_SYSTEM_PROMPT` aligned with [Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart) and [Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages) text-handling rules (plain text only, no markdown or raw SSML/XML tags, standard sentence punctuation for server-managed clause flushing, and natural English text normalization).
- **Concurrent Interruption Handling**: `agent_stream` reads upstream events in a background task while `run_agent(transcript)` streams `AIMessage` and `ToolMessage` updates into `out_queue`. If `SpeechStartedEvent` or `InterruptEvent` arrives while Gemini is generating tokens or executing `tavily_search`, `cancel_active_agent()` cancels the running `asyncio.Task` immediately and forwards the interruption event downstream to `tts_stream` and the browser client.

---

### 3.3 Deepgram Flux TTS Service (`backend/api/services/deepgram_tts.py`)

#### Connection & Audio Format Specification
Per [Flux TTS Overview](https://developers.deepgram.com/docs/flux-tts/overview) and [Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart), Flux TTS is served on the `/v2/speak` WebSocket endpoint (`/v1/speak` serves legacy Aura voices and does not serve `flux-*` models):

| Parameter | Configured Value | Specification & Purpose |
| :--- | :--- | :--- |
| **Endpoint** | `wss://api.deepgram.com/v2/speak` | Dedicated v2 conversational streaming TTS WebSocket endpoint ([Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart)). |
| **Authentication** | `Authorization: Token <DEEPGRAM_API_KEY>` | HTTP upgrade header using the Deepgram API token ([Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart)). |
| **`model`** | `flux-haley-en` | Featured American English conversational voice model (`flux-{voice}-{language}`, [Flux TTS Voices & Languages](https://developers.deepgram.com/docs/flux-tts/voices)). |
| **`encoding`** | `linear16` | Raw 16-bit signed little-endian PCM output stream ([Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart)). |
| **`sample_rate`** | `24000` | 24kHz output sample rate matching the frontend Web Audio playback pipeline ([Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart)). |
| **`speed`** | `1.0` (configurable `0.5 - 1.5`) | Speech-rate multiplier in `0.05` increments, adjustable mid-session via `Configure` ([Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages)). |
| **`expressivity`** | `0` (configurable `-2` to `2`) | Delivery register from calm (`-2`) to animated (`2`) ([Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart)). |

#### Token-Level Streaming & Turn Lifecycle
Unlike traditional TTS pipelines that buffer an entire LLM response before synthesizing audio, [Deepgram Flux TTS (`/v2/speak`)](https://developers.deepgram.com/docs/flux-tts/client-messages) is streaming-first and manages flush boundaries at sentence and clause boundaries internally:

```text
agent_stream                     tts_stream / DeepgramFluxTTS                Deepgram /v2/speak Server
────────────                     ────────────────────────────                ─────────────────────────
AgentChunkEvent("Sure, ")    ─▶  send_text("Sure, ")                     ─▶  {"type": "Speak", "text": "Sure, "}
                                                                         ◀─  {"type": "SpeechStarted", "speech_id": "..."}
AgentChunkEvent("I can ")    ─▶  send_text("I can ")                     ─▶  {"type": "Speak", "text": "I can "}
AgentChunkEvent("help.")     ─▶  send_text("help.")                      ─▶  {"type": "Speak", "text": "help."}
                                 yield TTSChunkEvent(pcm_bytes)          ◀─  [Binary 24kHz linear16 PCM frames]
AgentEndEvent                ─▶  flush()                                 ─▶  {"type": "Flush"}
                                 yield TTSChunkEvent(remaining_pcm)      ◀─  [Binary 24kHz linear16 PCM frames]
                                                                         ◀─  {"type": "Flushed", "speech_id": "..."}
                                                                         ◀─  {"type": "SpeechMetadata", "speech_id": "..."}
```

1. **Streaming `Speak` Frames**: As `AgentChunkEvent` tokens arrive from Gemini, `tts_stream` forwards each chunk immediately via `{"type": "Speak", "text": chunk_text}`. Per [Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages), the server concatenates successive `Speak` messages verbatim; if two separate LLM generations are stitched without whitespace (e.g., before and after a tool call), `tts_stream` inserts a single leading space to prevent sentence-boundary artifacts.
2. **Turn Completion (`Flush`)**: When `AgentEndEvent` arrives, `tts_stream` calls `tts.flush()`, sending `{"type": "Flush"}` ([Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages)). The server synthesizes any remaining buffered text, emits `Flushed` and `SpeechMetadata`, and preserves cross-turn prosody state on the open WebSocket for the next turn.
3. **Barge-In & Interruption (`Interrupt`)**: When `SpeechStartedEvent` or `InterruptEvent` arrives, `tts.cancel()` sets `_discard_audio = True` (immediately dropping any in-flight binary audio frames) and sends `{"type": "Interrupt"}` over `/v2/speak` ([Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages)). Unlike closing and reconnecting the socket, sending `Interrupt` stops synthesis and clears the server buffer while keeping the WebSocket connection warm and preserving voice consistency across turns.
4. **16-Bit Sample Alignment**: `DeepgramFluxTTS._parse_audio_chunk()` ensures every binary frame emitted in `TTSChunkEvent` is aligned to an even byte count (2 bytes per 16-bit PCM sample) before base64 serialization to the browser.

---

## 4. WebSocket & REST API Contracts (`backend/api/server.py`)

### 4.1 WebSocket Endpoint (`WS /ws`)

- **Client $\rightarrow$ Server Messages**:
  - **Binary Frames**: Raw 16-bit signed integer, 16kHz mono PCM audio chunks captured from the browser microphone.
  - **Text Control Frames**: `{"type": "interrupt"}` JSON string when the user clicks the UI interrupt button.
- **Server $\rightarrow$ Client Events (`VoiceAgentEvent`)**:

| Event Type | JSON Payload Schema | Description |
| :--- | :--- | :--- |
| `speech_started` | `{"type": "speech_started", "ts": 1762742400000}` | Fired immediately on Deepgram Flux `StartOfTurn` to halt client playback and trigger barge-in. |
| `stt_chunk` | `{"type": "stt_chunk", "transcript": "...", "ts": ...}` | Partial user transcript from Flux `StartOfTurn`, `Update`, `EagerEndOfTurn`, or `TurnResumed`. |
| `stt_output` | `{"type": "stt_output", "transcript": "...", "ts": ...}` | Finalized user transcript emitted on Flux `EndOfTurn`. |
| `agent_chunk` | `{"type": "agent_chunk", "text": "...", "ts": ...}` | Streaming text token from Gemini 3.7 Flash. |
| `tool_call` | `{"type": "tool_call", "toolId": "...", "name": "tavily_search", "args": {...}, "ts": ...}` | Notification that the agent invoked a tool. |
| `tool_result` | `{"type": "tool_result", "toolCallId": "...", "name": "tavily_search", "result": "...", "ts": ...}` | Output returned by the tool execution. |
| `agent_end` | `{"type": "agent_end", "ts": ...}` | Signals completion of the agent's text generation for the turn (`Flush` sent to Flux TTS). |
| `tts_chunk` | `{"type": "tts_chunk", "audio": "<base64_24khz_pcm>", "ts": ...}` | Base64-encoded 24kHz 16-bit mono linear PCM audio chunk from Deepgram Flux TTS. |
| `interrupt` | `{"type": "interrupt", "ts": ...}` | Confirms explicit client interruption and cancels active agent/TTS tasks. |

### 4.2 REST Endpoints

- **`GET /health`**: Returns `{"status": "ok"}` for container and load-balancer health probes.
- **`POST /chat`**: Accepts `{"user_message": "...", "thread_id": "..."}` and invokes the stateful Gemini agent synchronously, stripping any residual XML/SSML tags and returning `{"response": "...", "thread_id": "..."}`.

---

## 5. Configuration, Deployment & Testing

### 5.1 Environment Configuration (`backend/.env`)

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `DEEPGRAM_API_KEY` | Yes | — | Deepgram API key authenticating both `/v2/listen` and `/v2/speak` ([Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)). |
| `GOOGLE_API_KEY` | Yes | — | Google AI Studio API key for Gemini 3.7 Flash ([Google Gemini API Docs](https://ai.google.dev/gemini-api/docs)). |
| `TAVILY_API_KEY` | Yes | — | Tavily API key for real-time web search ([Tavily](https://tavily.com/)). |
| `DEEPGRAM_STT_MODEL` | No | `flux-general-en` | Deepgram Flux STT model identifier ([Models & Languages Overview](https://developers.deepgram.com/docs/models-languages-overview)). |
| `DEEPGRAM_TTS_MODEL` | No | `flux-haley-en` | Deepgram Flux TTS voice model identifier ([Flux TTS Voices & Languages](https://developers.deepgram.com/docs/flux-tts/voices)). |

### 5.2 Verification & Test Suite (`backend/tests/`)

- `tests/test_deepgram_stt.py`: Verifies `/v2/listen` URL construction, `Token` header authentication, `StartOfTurn` barge-in event emission, `Update` / `EagerEndOfTurn` / `TurnResumed` partial transcript handling, `EndOfTurn` finalization and `turn_index` deduplication, `ForceEndTurn` control frames, and `stt_stream` concurrency.
- `tests/test_deepgram_tts.py`: Verifies `/v2/speak` URL construction, binary `linear16` PCM chunk parsing and 16-bit alignment, `Speak` token streaming, sentence-boundary space insertion, `Flush` turn completion, `Interrupt` barge-in handling, `Configure` speed updates, and `tts_stream` cancellation.
- `tests/test_agent.py`, `tests/test_server.py`, `tests/test_schemas.py`, `tests/test_utils.py`: Validate end-to-end agent streaming, tool call events, barge-in task cancellation, FastAPI REST/WebSocket endpoints, and async iterator merging.
