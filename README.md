# Lingxi AI - Real-Time Voice & Text Chatbot

A full-duplex, real-time conversational voice and text AI application powered by **Google Gemini 3.7 Flash**, **AssemblyAI Streaming STT**, **Cartesia Sonic TTS**, and **Tavily Web Search**.

---

## Architecture Overview

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          Frontend (React + Vite)                       │
│  - Web Audio API (16kHz PCM capture, 24kHz Cartesia playback)          │
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
│  │ AssemblyAI STT v3│ -> │ Gemini 3.7 Flash│ -> │  Cartesia Sonic  │   │
│  │ Streaming Turns  │    │ + Tavily Search │    │  TTS (24kHz PCM) │   │
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
- **AssemblyAI v3 WebSocket STT**: Intelligent speech endpointing (`universal-3-6-pro`) with VAD `SpeechStarted` barge-in detection, semantic silence thresholds, and turn deduplication.
- **Gemini 3.7 Flash Agent with Memory**: LangChain agent with `InMemorySaver` checkpointer for stateful multi-turn conversation threads.
- **Real-Time Web Search Tool**: Integrated `tavily_search` tool enabling the agent to fetch up-to-date facts, news, and live data.
- **Cartesia Sonic TTS**: Ultra-low latency voice synthesis streaming 24kHz PCM chunks directly to the client, with instant mid-stream cancellation.
- **REST `/chat` Endpoint**: Fallback text-based request/response endpoint with thread context tracking.

---

## Project Structure

```text
voice_chatbot/
├── .github/
│   └── workflows/
│       └── ci.yml                # GitHub Actions CI workflow (lint, build, tests)
├── backend/
│   ├── api/
│   │   ├── schemas/              # Pydantic models (chat & event schemas)
│   │   ├── services/             # AssemblyAI STT & Cartesia TTS clients
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
   - [AssemblyAI](https://www.assemblyai.com/) (`ASSEMBLYAI_API_KEY`)
   - [Cartesia](https://cartesia.ai/) (`CARTESIA_API_KEY`)
   - [Tavily](https://tavily.com/) (`TAVILY_API_KEY`)

---

## Installation & Setup

### 1. Clone the Repository
```bash
git clone git@github.com:hylmike/voice-chatbot.git
cd voice_chatbot
```

### 2. Configure Backend Environment
Copy the example environment file and fill in your API keys:
```bash
cp backend/env.example backend/.env
```

Edit `backend/.env`:
```env
GOOGLE_API_KEY=your_gemini_api_key
ASSEMBLYAI_API_KEY=your_assemblyai_api_key
CARTESIA_API_KEY=your_cartesia_api_key
TAVILY_API_KEY=your_tavily_api_key
```

### 3. Install Dependencies

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

## Testing Locally

### 1. Backend Health Check
Verify the backend is active:
```bash
curl http://localhost:3100/health
# Expected output: {"status":"ok"}
```

### 2. Test Text Chat Endpoint
Send a test message to the REST endpoint:
```bash
curl -X POST http://localhost:3100/chat \
  -H "Content-Type: application/json" \
  -d '{"user_message": "Hello, who are you?"}'
```
*Expected response: JSON containing `response` and `thread_id`.*

### 3. Test Full-Duplex Voice Mode (Browser)
1. Open `http://localhost:3000` in Google Chrome or a modern browser.
2. Ensure the bottom status panel shows **Backend Connected**.
3. In the input console, click the **Microphone** icon to switch to **Voice Mode**.
4. Allow browser microphone access when prompted.
5. Speak into your microphone (e.g., *"What is the capital of France?"*).
6. Observe:
   - The purple/blue dynamic waveform pulses with your voice volume.
   - The interim transcript displays your speech live.
   - Upon completing your question, the agent processes the turn, displays the transcribed user message, streams its response, and synthesizes audio playback via Cartesia TTS.
   - Click the **Interrupt** button during playback, or speak into the microphone to verify instant barge-in and audio cutoff.

### 4. Test Web Search Tool
Ask a real-time question requiring search (e.g., *"What is the latest stock price of Apple?"* or *"What was yesterday's score in the Premier League?"*):
- Look for the collapsible **Web Search: "..."** badge in the assistant's message bubble.
- Click to expand and inspect the raw search query results returned by Tavily.

### 5. Run Linting & Production Build
- **Backend Linting & Formatting**:
  ```bash
  cd backend
  uv run ruff check .
  uv run ruff format --check .
  ```
- **Frontend Linting & Production Build**:
  ```bash
  cd frontend
  yarn lint
  yarn build
  ```

---

## Automated Unit Tests & Coverage

Both backend and frontend contain full test suites configured for >80% code coverage.

### Backend Unit Tests (`pytest` + `pytest-cov`)
```bash
cd backend
uv run pytest --cov=api --cov-report=term-missing
```

### Frontend Unit Tests (`vitest` + `@testing-library/react`)
```bash
cd frontend
yarn test:coverage
```

---

## Continuous Integration (CI)

A GitHub Actions workflow is located at [`.github/workflows/ci.yml`](.github/workflows/ci.yml). On every push or pull request to `main`:
- **Backend CI**: Runs `ruff format --check`, `ruff check`, and `pytest --cov=api`.
- **Frontend CI**: Runs `oxlint`, TypeScript compiler `tsc -b`, Vite production `build`, and Vitest test coverage.
