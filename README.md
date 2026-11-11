# Lingxi AI - Deepgram Flux Real-Time Voice & Text Agent

A full-duplex, real-time conversational voice and text AI application powered by **Google Gemini 3.7 Flash**, **[Deepgram Flux STT (`/v2/listen`)](https://developers.deepgram.com/docs/flux/quickstart)**, **[Deepgram Flux TTS (`/v2/speak`)](https://developers.deepgram.com/docs/flux-tts/overview)**, and **[Tavily Web Search](https://tavily.com/)**.

For the full architectural specification, protocol state machines, and sequence diagrams, see the **[System Design Document](docs/system_design.md)**.

---

## Architecture Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          Frontend (React + Vite)                       │
│  - Web Audio API (16kHz PCM capture, 24kHz linear16 PCM playback)      │
│  - Duplex Voice Mode & Text Input                                      │
│  - Audio Visualizer & Waveform Meter                                   │
│  - Multi-Thread Storage (localStorage) & Tool Call Inspector           │
└───────────────────▲────────────────────────────────▲───────────────────┘
                    │ WebSocket (/ws)                │ HTTP POST (/chat)
                    ▼                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI + LangChain)                   │
│                                                                        │
│  ┌──────────────────┐    ┌─────────────────┐    ┌──────────────────┐   │
│  │ Deepgram Flux STT│ -> │ Gemini 3.7 Flash│ -> │ Deepgram Flux TTS│   │
│  │ (/v2/listen)     │    │ + Tavily Search │    │ (/v2/speak 24kHz)│   │
│  └──────────────────┘    └─────────────────┘    └──────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Major Features

### Frontend UI (`frontend/`)
- **Real-Time Duplex Voice Mode**: Streams 16-bit mono 16kHz PCM audio over a persistent WebSocket (`/ws`) directly to the backend.
- **Echo-Free Audio Capture**: Microphones are connected via a zero-gain routing graph in the Web Audio API, preventing speaker feedback loops while streaming audio.
- **Live Interim Speech Preview**: Displays real-time interim transcription (`stt_chunk`) as you speak, before turn endpointing commits the message.
- **Audio Waveform & Activity Visualizer**: Real-time volume level indicators and animated frequency bars reacting to both user speech and assistant playback.
- **Instant Speech Interruption & Barge-In**: Interrupt button and automatic voice barge-in halt active audio playback immediately and drop in-flight audio chunks.
- **Transparent Tool Call Visibility**: Real-time inspection of background agent tool executions (e.g. Tavily web search queries and results) with collapsible detail cards.
- **Conversation Thread Management**: Create, rename, delete, and clear chat sessions, persisted locally via `localStorage`.
- **Text Chat Fallback**: Full markdown-rendered text chat using the `/chat` REST endpoint.

### Backend Agent (`backend/`)
- **FastAPI WebSocket Streaming Pipeline**: Chained generator pipeline (`stt_stream | agent_stream | tts_stream`) yielding structured JSON events (`speech_started`, `stt_chunk`, `stt_output`, `agent_chunk`, `agent_end`, `tts_chunk`, `interrupt`, `tool_call`, `tool_result`).
- **Deepgram Flux STT (`/v2/listen`)**: Conversational speech recognition (`flux-general-en`, [Getting Started with Flux](https://developers.deepgram.com/docs/flux/quickstart)) with model-integrated end-of-turn detection (`EndOfTurn`), native `StartOfTurn` barge-in detection ([Understanding the Flux State Machine](https://developers.deepgram.com/docs/flux/state)), and `turn_index` deduplication.
- **Gemini 3.7 Flash Agent with Memory**: LangChain agent with `InMemorySaver` checkpointer for stateful multi-turn conversation threads.
- **Real-Time Web Search Tool**: Integrated `tavily_search` tool enabling the agent to fetch up-to-date facts, news, and live data.
- **Deepgram Flux TTS (`/v2/speak`)**: Conversation-native streaming speech synthesis (`flux-haley-en`, [Getting Started with Flux TTS](https://developers.deepgram.com/docs/flux-tts/quickstart)) streaming LLM tokens via `Speak` and `Flush` frames into 24kHz `linear16` PCM audio chunks with instant `Interrupt` barge-in cancellation ([Client Messages](https://developers.deepgram.com/docs/flux-tts/client-messages)).
- **REST `/chat` Endpoint**: Fallback text-based request/response endpoint with thread context tracking.

---

## Project Structure

```text
deepgram_voice_agent/
├── .github/
│   └── workflows/
│       └── ci.yml                # GitHub Actions CI workflow (lint, build, tests)
├── docs/
│   └── system_design.md          # Detailed system design & protocol specification
├── backend/
│   ├── api/
│   │   ├── schemas/              # Pydantic models (chat & event schemas)
│   │   ├── services/             # Deepgram Flux STT (/v2/listen) & Flux TTS (/v2/speak)
│   │   ├── voice_agent/          # LangChain Gemini agent & Tavily search tool
│   │   └── server.py             # FastAPI HTTP & WebSocket server
│   ├── tests/                    # Backend unit test suite (pytest)
│   ├── Dockerfile
│   ├── docker-compose.yaml
│   ├── env.example
│   └── pyproject.toml            # Python dependencies and tool configs (uv)
├── frontend/
│   ├── src/
│   │   ├── components/           # ChatCanvas, InputConsole, Sidebar
│   │   ├── hooks/                # useChatStore (threads, messages, tools)
│   │   ├── services/             # Web Audio API manager & API/WS client
│   │   ├── App.tsx               # Main voice & chat coordinator
│   │   └── types.ts              # TypeScript event & message definitions
│   ├── package.json
│   └── vite.config.ts            # Vite & Vitest configuration
├── package.json                  # Root monorepo workspace configuration
└── README.md
```

---

## Prerequisites

1. **Node.js**: `v20+` and **Yarn** (`v4+` or `npm`)
2. **Python**: `3.12+` with [`uv`](https://docs.astral.sh/uv/) installed (or Docker & Docker Compose)
3. **API Keys**:
   - [Google AI Studio](https://aistudio.google.com/) (`GOOGLE_API_KEY`)
   - [Deepgram](https://console.deepgram.com/) (`DEEPGRAM_API_KEY`)
   - [Tavily](https://tavily.com/) (`TAVILY_API_KEY`)

---

## Installation & Setup

### 1. Configure Backend Environment
Copy the example environment file and fill in your API keys:
```bash
cp backend/env.example backend/.env
```

Edit `backend/.env`:
```env
GOOGLE_API_KEY=your_gemini_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
TAVILY_API_KEY=your_tavily_api_key
DEEPGRAM_STT_MODEL=flux-general-en
DEEPGRAM_TTS_MODEL=flux-haley-en
```

### 2. Install Dependencies

#### Backend
```bash
cd backend
uv sync
cd ..
```

#### Frontend
```bash
cd frontend
yarn install
cd ..
```

---

## Running Locally

### Option A: Local Development (Recommended)

1. **Start the Backend Server** (Port `3100`):
   ```bash
   cd backend
   uv run python api/server.py
   ```
   *The server starts on `http://localhost:3100` with Swagger docs at `http://localhost:3100/docs`.*

2. **Start the Frontend Dev Server** (Port `3000`):
   In a separate terminal:
   ```bash
   cd frontend
   yarn dev
   ```
   *Access the web app at `http://localhost:3000`.*

---

### Option B: Run Backend with Docker Compose

If you prefer running the backend in Docker:
```bash
cd backend
docker compose up --build
```
Then start the frontend locally:
```bash
cd frontend
yarn dev
```

---

## Testing & Linting

### Backend Linting & Unit Tests (`ruff` + `pytest`)
```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=api --cov-report=term-missing
```

### Frontend Linting & Unit Tests (`oxlint` + `vitest`)
```bash
cd frontend
yarn lint
yarn build
yarn test:coverage
```
