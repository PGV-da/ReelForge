# ReelForge Architecture

> System architecture, data flow, FSM state diagram, and FFmpeg filter breakdown.

---

## System Architecture Overview

```mermaid
graph TB
    subgraph Telegram["Telegram Client"]
        A[Admin User]
    end

    subgraph Bot["ReelForge"]
        B[aiogram Dispatcher]
        C[Admin Middleware]
        D[URL Router]
        E[FSM State Machine]
        
        subgraph Pipeline["Processing Pipeline"]
            F["yt-dlp<br/>Downloader"]
            G["faster-whisper<br/>Transcriber"]
            H["FFmpeg<br/>Video Editor"]
            I["LLM Service<br/>Caption AI"]
        end
        
        J[Verification Handler]
        K["Instagram Publisher<br/>Graph API Client"]
    end

    subgraph External["External Services"]
        L["Instagram CDN<br/>(Source Video)"]
        M["LLM API<br/>(Groq/Gemini/Ollama)"]
        N["Meta Graph API<br/>(Publishing)"]
        O["rupload.facebook.com<br/>(Binary Upload)"]
    end

    A -->|"Instagram URL"| B
    B --> C
    C -->|"Authorized"| D
    D --> F
    F -->|"Download MP4"| L
    F -->|"source.mp4 + metadata"| G
    G -->|"subtitles.srt + transcript"| H
    H -->|"processed.mp4 + thumbnail"| I
    I -->|"caption JSON"| M
    I -->|"Generated Caption"| J
    J -->|"Preview + Buttons"| A
    A -->|"✅ Approve"| K
    K -->|"Init Container"| N
    K -->|"Upload Binary"| O
    K -->|"Publish"| N
    K -->|"Permalink"| A
    E -.->|"State Management"| J
```

---

## Data Flow Sequence

```mermaid
sequenceDiagram
    participant Admin as Telegram Admin
    participant Bot as ReelForge Bot
    participant YT as yt-dlp
    participant W as faster-whisper
    participant FF as FFmpeg
    participant LLM as LLM API
    participant IG as Instagram Graph API
    participant RU as rupload.facebook.com

    Admin->>Bot: Send Instagram Reel URL
    Bot->>Bot: Validate URL & Create Job
    Bot->>Admin: "⏳ Step 1/4: Downloading..."

    Bot->>YT: Download video
    YT-->>Bot: source.mp4 + metadata.json
    Bot->>Admin: "✅ Step 1 ⏳ Step 2/4: Transcribing..."

    Bot->>FF: Extract audio (WAV)
    FF-->>Bot: audio.wav
    Bot->>W: Transcribe audio
    W-->>Bot: subtitles.srt + transcript text
    Bot->>Admin: "✅ Step 2 ⏳ Step 3/4: Processing..."

    Bot->>FF: Process video (crop, speed, subs, watermark, EQ)
    FF-->>Bot: processed.mp4
    Bot->>FF: Extract thumbnail
    FF-->>Bot: thumbnail.jpg
    Bot->>Admin: "✅ Step 3 ⏳ Step 4/4: Generating caption..."

    Bot->>LLM: Generate caption (transcript + metadata)
    LLM-->>Bot: {hook, body, CTA, hashtags}

    Bot->>Admin: Video preview + caption + [Approve | Edit | Regenerate | Thumbnail | Discard]

    alt Approve
        Admin->>Bot: ✅ Approve & Publish
        Bot->>IG: POST /media (init resumable upload)
        IG-->>Bot: container_id + upload_uri
        Bot->>RU: POST binary MP4
        RU-->>Bot: Upload complete
        loop Poll until FINISHED
            Bot->>IG: GET /container?fields=status_code
            IG-->>Bot: status_code
        end
        Bot->>IG: POST /media_publish
        IG-->>Bot: media_id
        Bot->>IG: GET /media?fields=permalink
        IG-->>Bot: permalink URL
        Bot->>Admin: "✅ Published! [permalink]"
    else Edit Caption
        Admin->>Bot: ✏️ Edit Caption
        Bot->>Admin: "Send new caption text"
        Admin->>Bot: Custom caption text
        Bot->>Admin: Updated preview + buttons
    else Regenerate
        Admin->>Bot: 🔄 Regenerate
        Bot->>LLM: New caption prompt
        LLM-->>Bot: Fresh caption
        Bot->>Admin: Updated preview + buttons
    else Discard
        Admin->>Bot: ❌ Discard
        Bot->>Bot: Cleanup /tmp/reelforge/job_id/
        Bot->>Admin: "🗑️ Job discarded"
    end
```

---

## FSM State Diagram

```mermaid
stateDiagram-v2
    [*] --> Idle: Bot starts

    Idle --> Downloading: Instagram URL received
    Downloading --> Transcribing: Download complete
    Transcribing --> ProcessingVideo: Transcription complete
    ProcessingVideo --> GeneratingCaption: Video processed
    GeneratingCaption --> WaitingApproval: Caption generated

    WaitingApproval --> EditingCaption: "✏️ Edit Caption" pressed
    WaitingApproval --> WaitingApproval: "🔄 Regenerate" pressed
    WaitingApproval --> EditingThumbnail: "🖼️ Set Thumbnail" pressed
    WaitingApproval --> Publishing: "✅ Approve" pressed
    WaitingApproval --> Discarded: "❌ Discard" pressed

    EditingCaption --> WaitingApproval: Caption text received
    EditingCaption --> WaitingApproval: "↩️ Cancel" pressed

    EditingThumbnail --> WaitingApproval: Timestamp received
    EditingThumbnail --> WaitingApproval: Photo uploaded
    EditingThumbnail --> WaitingApproval: "↩️ Cancel" pressed

    Publishing --> Published: Graph API success
    Publishing --> WaitingApproval: Graph API error (retry)

    Published --> [*]: Cleanup complete
    Discarded --> [*]: Cleanup complete
```

---

## FFmpeg Transformation Pipeline

### Video Filter Chain

```
Input (any resolution/fps)
    │
    ├── setpts=0.9803*PTS          ← +2% speed increase
    │
    ├── scale=1112:1978             ← ~3% zoom (overshoot target)
    │   force_original_aspect_ratio=increase
    │
    ├── crop=1080:1920              ← Center-crop to exact 9:16
    │
    ├── fps=30                      ← Normalize framerate
    │
    ├── subtitles='subtitles.srt'   ← Burn-in (if speech detected)
    │   force_style='Fontname=Montserrat,Fontsize=18,...,MarginV=75'
    │
    └── drawtext=text='@handle'     ← Watermark overlay
        fontsize=36, y=110, white@0.85, box=black@0.4
```

### Audio Filter Chain

```
Input Audio
    │
    ├── atempo=1.02                 ← Match +2% video speed
    │
    ├── highpass=f=65               ← Remove sub-bass rumble
    │
    ├── lowpass=f=15500             ← Remove ultra-high frequencies
    │
    └── equalizer=f=3000            ← Subtle mid-range boost
        width_type=h, width=200, g=1.5
```

### Encoding Parameters

| Parameter | Value | Purpose |
| :--- | :--- | :--- |
| `-c:v libx264` | H.264 | Universal compatibility |
| `-crf 22` | Constant Rate Factor | Quality/size balance |
| `-preset fast` | Encoding speed | Good speed/compression ratio |
| `-pix_fmt yuv420p` | Pixel format | Maximum device compatibility |
| `-profile:v high` | H.264 profile | Modern device support |
| `-c:a aac` | AAC audio | Instagram-compatible |
| `-b:a 128k` | Audio bitrate | Good quality at small size |
| `-ar 48000` | Sample rate | Standard for video |
| `-map_metadata -1` | Strip metadata | Remove source fingerprints |
| `-movflags +faststart` | Fast start | Progressive streaming |

### Why These Transforms Matter

1. **Speed Shift (+2%):** Alters every frame timestamp and audio sample, generating a unique media fingerprint that differs from the source
2. **Scale + Crop (3% zoom):** Changes pixel data across every frame, preventing pixel-perfect hash matching
3. **Audio EQ:** Modifies the frequency spectrum imperceptibly to human ears but creates a distinct audio fingerprint
4. **Metadata Stripping:** Removes all container-level metadata that could link back to the source
5. **Subtitle Burn-In:** Adds visual data to every frame in the subtitle regions
6. **Watermark:** Identifies your brand and further differentiates the pixel content

---

## Instagram Graph API Resumable Upload Flow

```mermaid
sequenceDiagram
    participant Bot as ReelForge Bot
    participant GA as graph.facebook.com
    participant RU as rupload.facebook.com

    Note over Bot,GA: Step 1: Initialize Container
    Bot->>GA: POST /{ig_user_id}/media<br/>media_type=REELS<br/>upload_type=resumable<br/>caption=...
    GA-->>Bot: {id: container_id, uri: upload_uri}

    Note over Bot,RU: Step 2: Upload Binary
    Bot->>RU: POST {upload_uri}<br/>Authorization: OAuth {token}<br/>offset: 0<br/>file_size: {bytes}<br/>[raw MP4 binary]
    RU-->>Bot: 200 OK

    Note over Bot,GA: Step 3: Poll Status
    loop Every 10-30s (exponential backoff)
        Bot->>GA: GET /{container_id}?fields=status_code,status
        GA-->>Bot: {status_code: "IN_PROGRESS" | "FINISHED" | "ERROR"}
    end

    Note over Bot,GA: Step 4: Publish
    Bot->>GA: POST /{ig_user_id}/media_publish<br/>creation_id={container_id}
    GA-->>Bot: {id: media_id}

    Note over Bot,GA: Step 5: Get Permalink
    Bot->>GA: GET /{media_id}?fields=permalink
    GA-->>Bot: {permalink: "https://instagram.com/reel/..."}
```
