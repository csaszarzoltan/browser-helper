# Browser Helper 🦎

Remote Chrome control proxy — connects to your local Chrome via CDP and exposes a fast REST API + WebSocket GUI dashboard.

## Why?

A Hermes AI agent (on a remote server) needs to control your browser through an SSH tunnel. Every CDP operation over the tunnel is slow because of large data transfers (snapshots, screenshots).

**Browser Helper** runs on **your Windows machine**, next to Chrome. Hermes calls small REST commands over the tunnel, while all heavy work (page parsing, screenshot compression) happens locally.

## Architecture

```
Windows (your PC)                         Linux (Hermes server)
┌────────────────────────┐               ┌────────────────────┐
│ Chrome (port 9555)     │               │   Hermes Agent     │
│    └── CDP WebSocket   │               │      ↓             │
│    └── Browser Helper  │──SSH tunnel──→│  REST API calls    │
│        FastAPI :8000   │   (Bitvise)   │  (small JSON)      │
│        + GUI Dashboard │               │                    │
└────────────────────────┘               └────────────────────┘
```

## Install & Run

```bash
# On your Windows machine:
pip install fastapi uvicorn websockets httpx Pillow python-multipart
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Or with Docker:
```bash
docker build -t browser-helper .
docker run -d --network host -e PORT=8000 --name browser-helper browser-helper
```

Then open http://localhost:8000 in your browser for the GUI dashboard.

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | GUI Dashboard (HTML) |
| GET | `/status` | Connection status |
| POST | `/connect` | Connect to Chrome CDP |
| POST | `/disconnect` | Disconnect |
| POST | `/navigate?url=...` | Navigate to URL |
| POST | `/eval` | Execute JavaScript `{"js": "..."}` |
| POST | `/click` | Click element `{"selector": "..."}` |
| POST | `/type` | Type text `{"selector": "...", "text": "..."}` |
| POST | `/screenshot` | Take screenshot (returns base64 JPEG) |
| GET | `/tabs` | List open tabs |
| POST | `/switch_tab/{tab_id}` | Switch to tab |
| POST | `/get_text` | Get page text |
| WS | `/ws` | Real-time status updates |

## Performance

- **Navigate:** ~50-200ms (vs 500ms+ with tunnel snapshot)
- **Click/Type:** ~20-50ms (vs 100-300ms)
- **Screenshot:** ~100-300ms (vs 500ms+ full size)
- **Eval:** ~10-30ms (vs 100ms+ CDP round-trip)

## Development

```bash
# Setup
cd browser-helper
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Test
pytest
```

## License

MIT
