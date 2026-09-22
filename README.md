# Pharmacy ADK - Multi-Agent Medical Assistant

A conversational AI system for pharmacy and medical assistance built with Google's Agent Development Kit (ADK). Routes user requests intelligently across specialized agents for care operations, commerce, appointments, and merchant management.

## Features

- **Multi-Agent Architecture**: Specialized agents for Care, Commerce, Appointment, and Merchant domains
- **Dual-Mode Interface**: Text chat and real-time voice (Gemini Live API)
- **Smart Routing**: Multi-layer request classification (fast path → regex patterns → LLM routing)
- **Multi-Language Support**: Tamil, Telugu, Hindi, Kannada, Malayalam, Bengali, and more (including Tanglish)
- **Prescription Management**: Upload, track, and manage prescriptions with refill support
- **Shopping & Cart**: Product search, availability checks, cart management, and checkout
- **Doctor Appointments**: Search, book, reschedule, and track appointments
- **Merchant Dashboard**: Inventory and order management for merchants
- **Observability**: Comprehensive turn-based metrics and logging
- **SQLite Backend**: Durable, persistent data storage

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Vanilla JS)                    │
│              Text Chat + Voice WebSocket UI                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                ┌────▼─────────────────────────────────────┐
                │      FastAPI Server (main.py)            │
                │  /chat, /voice/ws, /cart, /products      │
                └────┬────────────────────────────────────┘
                     │
        ┌────────────┴──────────────────┐
        │                               │
   ┌────▼──────────────┐        ┌──────▼──────────────┐
   │   RouterLayer     │        │  Voice Agent (Live) │
   │  (Text Mode)      │        │   (Streaming)       │
   │                   │        │                     │
   │ • Fast Path       │        │ • Multi-language    │
   │ • Regex Routes    │        │ • Direct tools      │
   │ • LLM Router      │        │ • First-audio track │
   └────┬──────────────┘        └──────┬──────────────┘
        │                               │
        └───────────────┬───────────────┘
                        │
        ┌───────────────┴───────────────────────┐
        │                                       │
   ┌────▼─────────┐  ┌────▼──────────┐  ┌──────▼────────┐  ┌───────▼────┐
   │ Care Agent   │  │Commerce Agent │  │Appointment Ag.│  │Merchant Ag.│
   │              │  │               │  │               │  │            │
   │ • Rx tools   │  │• Search       │  │• Doctor search│  │• Analytics │
   │ • Refills    │  │• Cart         │  │• Booking      │  │• Inventory │
   │ • Household  │  │• Checkout     │  │• Reschedule   │  │• Orders    │
   │ • Emergency  │  │• Pharmacy ops │  │• Track status │  │            │
   └──────────────┘  └───────────────┘  └───────────────┘  └────────────┘
        │                 │                    │                │
        └─────────────────┴────────────────────┴────────────────┘
                          │
                ┌─────────▼────────────┐
                │ SQLiteRepository     │
                │ (pharmacy.db)        │
                │                      │
                │ • users              │
                │ • products           │
                │ • prescriptions      │
                │ • orders             │
                │ • appointments       │
                │ • inventory          │
                └──────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Google Gemini API key
- pip or conda

### Installation

1. **Clone and setup**
   ```bash
   cd pharmacy_adk
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings:
   # - GEMINI_API_KEY (required)
   # - DATABASE_URL (optional, defaults to SQLite)
   # - Model names (optional, defaults provided)
   ```

4. **Run the server**
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
   ```

5. **Open frontend**
   ```bash
   # Open frontend/index.html in your browser
   # Or serve with: python -m http.server 3000 --directory frontend
   ```

---

## API Endpoints

### Text Chat
```bash
POST /chat
Content-Type: application/json

{
  "user_id": "user_001",
  "session_id": "user_001",
  "message": "What's in my cart?"
}
```

**Response:**
```json
{
  "success": true,
  "user_id": "user_001",
  "session_id": "user_001",
  "response": "Your cart is empty."
}
```

### Voice WebSocket
```
WS ws://127.0.0.1:8001/voice/ws?user_id=user_001&session_id=user_001
```

**Message types:**
- `{"bytes": <audio_data>}` - PCM audio (16kHz)
- `{"type": "text", "text": "..."}` - Text input
- Server responds with: `user_transcript`, `assistant_text`, `assistant_transcript`, audio bytes, `turn_complete`

### Cart Endpoint
```bash
GET /cart?user_id=user_001

{
  "success": true,
  "item_count": 2,
  "items": [
    {"id": "prod_1", "name": "Aspirin", "quantity": 2, "price": 5.99}
  ]
}
```

### Products Endpoint
```bash
GET /products

{
  "success": true,
  "products": [
    {
      "id": "prod_1",
      "name": "Aspirin",
      "generic_name": "acetylsalicylic acid",
      "category": "pain_relief",
      "price": 5.99,
      "requires_prescription": false,
      "stock": 100,
      "in_stock": true
    }
  ]
}
```

### Health Check
```bash
GET /health

{
  "status": "ok",
  "service": "pharmacy-api"
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API key |
| `DATABASE_URL` | `sqlite:///./data/pharmacy.db` | SQLite database path |
| `SMALL_MODEL` | `gemini-3.6-flash` | Fast model for simple tasks |
| `LARGE_MODEL` | `gemini-3.6-flash` | Capable model for routing |
| `LIVE_MODEL` | `gemini-3.8-live` | Live-API capable model (voice) |
| `DEFAULT_USER_ID` | `user_001` | Default user for unauthenticated requests |
| `DEFAULT_MERCHANT_ID` | `merchant_001` | Default merchant account |

---

## Routing Logic

### Layer 1: Simple Greetings
Fast-path for common greetings without LLM:
```
"hello", "hi", "thanks", "help", "bye", etc.
```

### Layer 2: Fast Routes (Regex)
Explicit operational requests matched by keyword:
- **Care**: "prescription", "refill", "rx"
- **Commerce**: "cart", "shop", "buy", "order", "price"
- **Appointments**: "doctor", "booking", "reschedule"

### Layer 3: Intent Routing
Multi-turn regex patterns for complex queries (e.g., "add X to cart", "remove Y from cart")

### Layer 4: LLM Router
When no pattern matches, the router LLM decides:
```json
{
  "agents": ["care", "commerce"],
  "response": ""
}
```
- If `"main"` → answer directly as medical assistant
- If specialist agent(s) → delegate to that agent

---

## Agent Responsibilities

### Care Agent
- Prescription records and retrieval
- Prescription upload and reading
- Refill operations
- Household care tracking
- Emergency information
- Prescription-based commerce preparation (delegates cart to Commerce)

### Commerce Agent
- Product search (by name, brand, category)
- Availability checks
- Pharmacy information
- Cart operations (add, remove, clear, view)
- Checkout and order placement
- Order tracking and returns

### Appointment Agent
- Doctor search and filtering
- Availability checking
- Booking and rescheduling
- Cancellation
- Appointment status tracking

### Merchant Agent
- Merchant-specific inventory management
- Fulfillment operations
- Order analytics
- Merchant catalog management

---

## File Structure

```
pharmacy_adk/
├── app/
│   ├── main.py                 # FastAPI server, endpoints, WebSocket
│   ├── agent.py                # Root agent entrypoint
│   ├── router.py               # RouterLayer, routing logic, voice_agent
│   ├── intent_routing.py       # Regex-based fast routing patterns
│   ├── fast_path.py            # Direct tool dispatch for fast routes
│   ├── lang_detect.py          # Language detection, Tanglish support
│   ├── turn_metrics.py         # Observability, turn tracking
│   │
│   ├── config/
│   │   └── settings.py         # Environment config
│   │
│   ├── database/
│   │   └── repository.py       # SQLite backend
│   │
│   ├── models/
│   │   └── schemas.py          # Pydantic models
│   │
│   ├── tools/
│   │   └── common.py           # Tool utilities
│   │
│   ├── care/
│   │   ├── agent.py            # Care Agent definition
│   │   ├── prompts.py          # Care domain prompts
│   │   └── tools.py            # Care tools (Rx, refills, etc.)
│   │
│   ├── commerce/
│   │   ├── agent.py            # Commerce Agent definition
│   │   ├── prompts.py          # Commerce domain prompts
│   │   └── tools.py            # Commerce tools (search, cart, etc.)
│   │
│   ├── appointment/
│   │   ├── agent.py            # Appointment Agent definition
│   │   ├── prompts.py          # Appointment domain prompts
│   │   └── tools.py            # Appointment tools
│   │
│   ├── merchant/
│   │   ├── agent.py            # Merchant Agent definition
│   │   ├── prompts.py          # Merchant domain prompts
│   │   └── tools.py            # Merchant tools
│   │
│   └── voice/
│       └── session.py          # Voice session tracking
│
├── frontend/
│   ├── index.html              # Main UI
│   ├── app.js                  # Chat/voice client
│   └── style.css               # Styles
│
├── data/
│   └── pharmacy.db             # SQLite database (created at runtime)
│
├── logs/
│   └── server.log              # Application logs
│
├── pyproject.toml              # Project metadata
├── requirements.txt            # Dependencies
├── .env.example                # Environment template
├── .gitignore                  # Git ignore rules
└── README.md                   # This file
```

---

## Logging

All application logs are written to `logs/server.log` with format:
```
TIMESTAMP | LEVEL | LOGGER_NAME | MESSAGE
```

### Key Log Markers

- `[CHAT_REQUEST]` - Chat API call received
- `[CHAT_RESPONSE]` - Chat API response sent
- `[VOICE_CONNECTED]` - WebSocket voice connection established
- `[VOICE_DISCONNECTED]` - WebSocket voice connection closed
- `[ROUTER]` - Routing decision (fast_path, regex, or LLM)
- `[TOOL_START]` / `[TOOL_END]` - Tool execution
- `[AGENT_FLOW]` - Agent orchestration summary

---

## Multi-Language Support

The system detects and responds in the user's language:

**Supported Languages:**
- Tamil (ta), Telugu (te), Kannada (kn), Malayalam (ml)
- Hindi (hi), Bengali (bn), Gujarati (gu), Punjabi (pa), Urdu (ur)
- English (en), Chinese (zh), Japanese (ja), Korean (ko), Russian (ru)
- **Tanglish** (ta-en): Natural Tamil-English code-switching

**Example:** User speaks Tamil → system responds in Tamil. User mixes English + Tamil → system responds in matching mixed style.

---

## Development & Testing

### Run Tests (when available)
```bash
pytest tests/ -v
```

### Enable Debug Logging
```python
# In app/main.py, change logging level:
logging.basicConfig(level=logging.DEBUG)
```

### Check Database Schema
```bash
sqlite3 data/pharmacy.db ".schema"
```

### Monitor Turns
Metrics are tracked in memory per turn (`turn_metrics.py`). Check logs for:
```
[TURN_COMPLETE] turn_id=... total_turn_time=...ms
```

---

## Performance Notes

- **Fast Path**: <50ms for regex-matched queries
- **Text Chat**: 1-3s (routing + agent + LLM)
- **Voice**: First-audio latency tracked per turn
- **Database**: SQLite with WAL mode for concurrent access
- **Session Management**: In-memory service (consider Redis for distributed)

---

## Security Considerations

⚠️ **Before Production:**
1. Add authentication/authorization
2. Enable HTTPS/WSS (not HTTP/WS)
3. Configure CORS for your domain (not localhost)
4. Add rate limiting and request size limits
5. Implement PII redaction in logs
6. Validate all user inputs
7. Use managed sessions (Redis, not in-memory)
8. Audit tool permissions per user/merchant

---

## Troubleshooting

### "GEMINI_API_KEY not found"
- Add your key to `.env` file
- Restart server
- Verify key is valid on [console.cloud.google.com](https://console.cloud.google.com)

### Database errors
- Check `data/` directory exists and is writable
- Verify SQLite3 is installed: `sqlite3 --version`
- Delete `data/pharmacy.db` to reset (data loss!)

### Voice WebSocket fails
- Check frontend CONFIG API and VOICE URLs match server address
- Verify server is running on port 8001
- Check browser console for connection errors

### Tanglish not recognized
- Verify `lang_detect.py` has Tamil script patterns
- Check `response_language_for()` in router.py
- Review logs for detected language vs expected

---

## Contributing

To add new features:
1. Create a new domain agent in `app/DOMAIN/`
2. Add tools in `app/DOMAIN/tools.py`
3. Update routing patterns in `intent_routing.py`
4. Test end-to-end through chat and voice

---

## License

*(Add your license here)*

---

## Support

For issues or questions:
- Check logs in `logs/server.log`
- Review routing logic in `app/router.py`
- Verify environment variables in `.env`
- Test individual agents with `/chat` endpoint

---

**Built with [Google ADK](https://ai.google.dev/adk) and [Gemini API](https://ai.google.dev/gemini)**
