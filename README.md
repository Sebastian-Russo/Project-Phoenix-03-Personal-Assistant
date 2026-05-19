# Phoenix 03 — Personal Assistant

A self-hosted AI personal assistant that connects to your apps and services
via natural language. One interface for messaging, calendar, music, code,
and more — powered by Claude as the reasoning engine.

## Architecture
User message → Router (Claude classifies intent)
→ Specialist Agent (messaging, calendar, media, vision, briefing)
→ Connector (Slack, Google, Spotify, GitHub, Discord, ACRCloud)
→ Tool Registry (routes tool calls)
→ Response

For unknown or multi-step intents, the Orchestrator runs an agentic loop
directly with Claude + all registered tools until the task is complete.

## Connectors

| Service | Method | Auth | Status |
|---|---|---|---|
| Slack | Native API | Bot token (xoxb-) | ✅ Active |
| Google Calendar | Google API | OAuth2 | ✅ Active |
| Google Drive | Google API | OAuth2 | ✅ Active |
| Spotify | Native API | OAuth2 + manual code | ✅ Active |
| GitHub | Native API | Personal Access Token | ✅ Active |
| Discord | Native API | Bot token | ✅ Active |
| ACRCloud | Native API | HMAC-SHA1 | ✅ Active |
| Jira | Atlassian API | API token | ⏳ Credentials pending |
| Confluence | Atlassian API | API token | ⏳ Credentials pending |
| Reddit | Native API | Password flow | ⏳ Approval pending |

## Agents

| Agent | Handles | Connectors used |
|---|---|---|
| MessagingAgent | Read/summarize/send Slack messages | Slack |
| CalendarAgent | Read events, create events, check availability | Google Calendar |
| MediaAgent | Play/pause/skip/volume Spotify | Spotify |
| VisionAgent | Analyze images, extract data, route to Drive or local | Google Drive |
| BriefingAgent | Morning briefing — calendar + messages synthesized | Calendar + Slack + Spotify |
| Orchestrator | Multi-step and unknown intents via agentic loop | All registered tools |

## Setup

### 1. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
sudo apt-get install portaudio19-dev  # for ACRCloud mic recording
```

### 2. Configure .env
```bash
# Anthropic
ANTHROPIC_API_KEY=

# Slack
SLACK_BOT_TOKEN=          # xoxb- token from OAuth & Permissions
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_SIGNING_SECRET=
SLACK_ACCESS_TOKEN=       # xoxe- config token (optional)
SLACK_REFRESH_TOKEN=      # config token refresh

# Google
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_TOKEN_PATH=certs/google_token.json
TIMEZONE=America/New_York

# Spotify
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_TOKEN_PATH=certs/spotify_token.json

# GitHub
GITHUB_TOKEN=
GITHUB_USERNAME=

# Discord
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=

# ACRCloud
ACRCLOUD_ACCESS_KEY=
ACRCLOUD_ACCESS_SECRET=
ACRCLOUD_HOST=identify-us-west-2.acrcloud.com

# Atlassian (deferred)
ATLASSIAN_EMAIL=
ATLASSIAN_API_TOKEN=
ATLASSIAN_DOMAIN=

# Flask
FLASK_PORT=5000
FLASK_DEBUG=true
```

### 3. First run — OAuth flows
Google and Spotify require a one-time browser authorization:

**Google** — runs automatically on first start, opens browser consent screen.

**Spotify** — runs automatically, opens browser, you approve, then paste
the redirect URL from the address bar into the terminal when prompted.

### 4. Run
```bash
python app.py
```

Open `http://localhost:5000`.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/chat` | Send a message, get a response |
| POST | `/api/vision` | Upload an image for analysis |
| GET | `/api/briefing` | Trigger morning briefing |
| POST | `/api/reset` | Clear conversation history |
| GET | `/api/status` | Active agents and registered tools |
| GET | `/api/health` | Liveness check |

## Example prompts
- morning briefing
- what's on my calendar today?
- check my unread Slack messages
- summarize #general
- play something chill on Spotify
- skip this song
- what's playing?
- list my GitHub repos
- check open issues in my-project
- read messages in #frontend on Discord
- what song is this?  (+ attach image or use mic)

## Deferred / Pending

- **Reddit** — app submitted, awaiting approval
- **Atlassian (Jira/Confluence)** — connector built, credentials needed
- **Teams + M365** — Phoenix 03 work extension (future)
- **ACRCloud mic** — requires `pyaudio` + `portaudio` system dependency
- **PSECU** — Teller enrollment token expired (Phoenix 02)
- **Merrill Lynch** — not in Teller institution list (Phoenix 02)