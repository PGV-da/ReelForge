# ReelForge 🎬

> Telegram-controlled Instagram Reels repurposing & publishing engine.

ReelForge automates the entire pipeline of downloading public Instagram Reels, transforming them for originality (watermark, subtitles, audio/video fingerprint alteration), generating AI-powered captions, and publishing directly to your Instagram Professional Account — all controlled through an interactive Telegram bot interface.

---

## ✨ Features

- **🔗 URL Ingestion** — Paste any public Instagram Reel/Post URL into Telegram
- **⬇️ Smart Download** — Highest-quality MP4 via yt-dlp with optional cookie support
- **🎤 Speech-to-Text** — Local transcription via faster-whisper (no cloud dependency)
- **📝 Auto Subtitles** — Burned-in subtitles optimized for vertical video readability
- **🎨 Originality Transforms** — Watermark, speed shift, crop/zoom, audio EQ fingerprinting
- **🤖 AI Captions** — Hook lines, value body, CTAs, and hashtags via Groq/Gemini/Ollama
- **🖼️ Smart Thumbnails** — Sharpest-frame detection or manual timestamp selection
- **✅ Interactive Verification** — Approve, edit, regenerate, or discard via Telegram buttons
- **📤 Direct Publishing (Optional)** — Meta Graph API Resumable Upload (or save/download directly in Telegram without Instagram credentials)
- **🔒 Admin-Only Access** — Whitelist-based Telegram user authorization

---

## 📋 Prerequisites

### System Requirements
- **Python 3.11+**
- **FFmpeg** (with libx264 and AAC support)
- **Redis** (optional, recommended for FSM state persistence)

### Accounts & APIs
- **Telegram Bot** (Required) — Create via [@BotFather](https://t.me/BotFather)
- **LLM API Key** (Required) — Groq, Google Gemini, or local Ollama instance
- **Instagram Professional Account** (Optional) — Only needed if you want automatic direct publishing to Instagram. If omitted, the bot runs in local repurposing mode, delivering high-resolution transformed videos and AI captions directly to you in Telegram.

> 📖 See [docs/META_API_SETUP.md](docs/META_API_SETUP.md) for step-by-step Instagram API setup when you are ready to enable auto-publishing.

---

## 🚀 Quickstart

### Option A: Local Virtualenv

```bash
# 1. Clone the repo
git clone https://github.com/your-org/ReelForge.git
cd ReelForge

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install system dependencies
# Ubuntu/Debian:
sudo apt update && sudo apt install -y ffmpeg fonts-liberation

# macOS (Homebrew):
brew install ffmpeg

# 5. Download the Montserrat font
# Download from: https://fonts.google.com/specimen/Montserrat
# Place Montserrat-Bold.ttf in: assets/fonts/

# 6. Configure environment
cp .env.example .env
# Edit .env with your actual credentials

# 7. Run the bot
python -m app.main
```

### Option B: Docker Compose

```bash
# 1. Clone and configure
git clone https://github.com/your-org/ReelForge.git
cd ReelForge
cp .env.example .env
# Edit .env with your credentials

# 2. Download font (place in assets/fonts/Montserrat-Bold.ttf)

# 3. Build and run
docker-compose up -d --build

# View logs
docker-compose logs -f bot

# Stop
docker-compose down
```

---

## 🤖 Telegram Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Welcome message and feature overview |
| `/help` | Detailed usage instructions |
| `/status` | Bot operational status and configuration |
| `/token_health` | Check Instagram API token validity and expiry |

### Interactive Workflow

1. **Send an Instagram URL** → Bot starts processing
2. **Watch real-time progress** → Download → Transcribe → Process → Caption
3. **Review the preview** → Video + thumbnail + generated caption
4. **Use inline buttons:**

| Button | Action |
| :--- | :--- |
| ✅ Approve & Publish | Upload to Instagram via Graph API |
| ✏️ Edit Caption | Enter your own custom caption text |
| 🔄 Regenerate Caption | Get a fresh AI-generated caption |
| 🖼️ Set Thumbnail | Pick a frame by timestamp or upload a cover photo |
| ❌ Discard | Cancel the job and purge all temp files |

---

## 🏗️ Architecture

```
Telegram Admin
    │
    ▼ (Instagram URL)
┌─────────────────────────────────────┐
│         ReelForge               │
│                                     │
│  ┌─────────┐    ┌──────────────┐   │
│  │ yt-dlp   │───▶│ faster-whisper│  │
│  │ Download │    │ Transcribe   │   │
│  └────┬─────┘    └──────┬───────┘   │
│       │                 │           │
│       ▼                 ▼           │
│  ┌──────────────────────────┐       │
│  │        FFmpeg            │       │
│  │  • 1080x1920 crop/scale  │       │
│  │  • +2% speed shift       │       │
│  │  • Subtitle burn-in      │       │
│  │  • Watermark overlay     │       │
│  │  • Audio EQ fingerprint  │       │
│  └────────────┬─────────────┘       │
│               │                     │
│               ▼                     │
│  ┌──────────────────────────┐       │
│  │   LLM Caption Generator  │       │
│  │   (Groq/Gemini/Ollama)   │       │
│  └────────────┬─────────────┘       │
│               │                     │
│               ▼                     │
│  ┌──────────────────────────┐       │
│  │  Telegram Verification   │       │
│  │  (Preview + Buttons)     │       │
│  └────────────┬─────────────┘       │
│               │ [Approve]           │
│               ▼                     │
│  ┌──────────────────────────┐       │
│  │  Instagram Graph API     │       │
│  │  Resumable Upload        │       │
│  └──────────────────────────┘       │
└─────────────────────────────────────┘
    │
    ▼
Instagram (Published Reel)
```

> 📖 See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed data flow and FFmpeg filter breakdown.

---

## 🔧 Configuration

All configuration is managed via environment variables (`.env` file). See [.env.example](.env.example) for all available options.

### Required Variables

| Variable | Description |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `ADMIN_USER_IDS` | Comma-separated authorized Telegram user IDs |
| `IG_USER_ID` | Instagram Business Account numeric ID |
| `IG_ACCESS_TOKEN` | Long-lived Meta Graph API access token |

### Optional Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `WATERMARK_TEXT` | `@your_handle` | Username watermark text |
| `WHISPER_MODEL_SIZE` | `base` | faster-whisper model (tiny/base/small/medium/large-v3) |
| `LLM_PROVIDER` | `groq` | LLM API provider (groq/gemini/ollama) |
| `LLM_MODEL_NAME` | `llama-3.3-70b-versatile` | Model identifier |
| `REDIS_URL` | None | Redis URL for FSM persistence |

---

## 📁 Project Structure

```
ReelForge/
├── .env.example              # Environment variable template
├── Dockerfile                # Production container image
├── docker-compose.yml        # Bot + Redis services
├── pyproject.toml            # Project metadata & dependencies
├── requirements.txt          # Pinned production dependencies
├── README.md                 # This file
├── docs/
│   ├── ARCHITECTURE.md       # Detailed system architecture
│   └── META_API_SETUP.md     # Instagram API setup guide
├── assets/fonts/             # Subtitle & watermark fonts
└── app/
    ├── main.py               # Application entrypoint
    ├── config.py             # Pydantic settings configuration
    ├── models/job.py         # Data models (ReelJob, VideoMetadata)
    ├── bot/
    │   ├── states.py         # FSM state definitions
    │   ├── keyboards.py      # Inline keyboard builders
    │   ├── middlewares.py     # Admin-only access control
    │   └── handlers/
    │       ├── start.py      # /start, /help, /status commands
    │       ├── ingest.py     # URL detection & pipeline orchestration
    │       └── verification.py  # Approve, Edit, Regenerate, Discard
    ├── services/
    │   ├── downloader.py     # yt-dlp async wrapper
    │   ├── transcriber.py    # faster-whisper STT & SRT generation
    │   ├── video_editor.py   # FFmpeg transformation pipeline
    │   ├── caption_ai.py     # LLM caption generator (Groq/Gemini/Ollama)
    │   └── instagram_api.py  # Meta Graph API Resumable Upload client
    └── utils/
        ├── temp_manager.py   # Job directory lifecycle management
        ├── time_parser.py    # Timestamp parsing utilities
        └── logger.py         # Loguru configuration
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
