"""
Flask entry point for Phoenix 03.
Initializes all connectors, registers them with the tool registry,
wires up specialist agents, and exposes the orchestrator over HTTP.

Startup sequence:
    1. Validate credentials per connector
    2. Authenticate each available connector
    3. Register tools with the registry
    4. Wire agents with their connectors
    5. Start Flask
"""

import os
import base64
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

from config import Config
from src.tools.tool_registry import ToolRegistry
from src.agents.orchestrator import Orchestrator
from src.agents.messaging_agent import MessagingAgent
from src.agents.calendar_agent import CalendarAgent
from src.agents.media_agent import MediaAgent
from src.agents.vision_agent import VisionAgent
from src.agents.briefing_agent import BriefingAgent

# ── Connectors ────────────────────────────────────────────────────────────────
# Import all — instantiate only if credentials available
from src.connectors.slack_connector import SlackConnector
from src.connectors.google_calendar_connector import GoogleCalendarConnector
from src.connectors.google_drive_connector import GoogleDriveConnector
from src.connectors.spotify_connector import SpotifyConnector
from src.connectors.github_connector import GitHubConnector
from src.connectors.jira_connector import JiraConnector
from src.connectors.confluence_connector import ConfluenceConnector


app  = Flask(__name__, static_folder="static")
CORS(app)

# ── Bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap() -> Orchestrator:
    """
    Initialize connectors, register tools, wire agents.
    Returns a fully configured Orchestrator.
    """
    available = Config.available_connectors()
    missing   = Config.validate()

    print("\n── Phoenix 03 Startup ──────────────────────────────")
    if missing:
        for connector, keys in missing.items():
            print(f"  ⚠ {connector}: missing {keys} — skipping")
    print(f"  ✓ Available: {available}")
    print("────────────────────────────────────────────────────\n")

    if "anthropic" not in available:
        raise RuntimeError("ANTHROPIC_API_KEY is required — cannot start without it.")

    registry = ToolRegistry()

    # ── Slack ─────────────────────────────────────────────────────────────────
    slack = None
    if "slack" in available:
        slack = SlackConnector()
        if slack.authenticate():
            registry.register("slack", slack)
        else:
            print("[app] Slack authentication failed — skipping.")
            slack = None

    # ── Google ────────────────────────────────────────────────────────────────
    calendar = None
    drive    = None
    if "google" in available:
        calendar = GoogleCalendarConnector()
        if calendar.authenticate():
            registry.register("google_calendar", calendar)
        else:
            print("[app] Google Calendar authentication failed — skipping.")
            calendar = None

        drive = GoogleDriveConnector()
        if drive.authenticate():
            registry.register("google_drive", drive)
        else:
            print("[app] Google Drive authentication failed — skipping.")
            drive = None

    # ── Spotify ───────────────────────────────────────────────────────────────
    spotify = None
    if "spotify" in available:
        spotify = SpotifyConnector()
        if spotify.authenticate():
            registry.register("spotify", spotify)
        else:
            print("[app] Spotify authentication failed — skipping.")
            spotify = None

    # ── GitHub ────────────────────────────────────────────────────────────────
    if "github" in available:
        github = GitHubConnector()
        if github.authenticate():
            registry.register("github", github)

    # ── Atlassian ─────────────────────────────────────────────────────────────
    if "atlassian" in available:
        jira = JiraConnector()
        if jira.authenticate():
            registry.register("jira", jira)

        confluence = ConfluenceConnector()
        if confluence.authenticate():
            registry.register("confluence", confluence)

    # ── Wire agents ───────────────────────────────────────────────────────────
    messaging = MessagingAgent(slack)          if slack    else None
    cal_agent = CalendarAgent(calendar)        if calendar else None
    media     = MediaAgent(spotify)            if spotify  else None
    vision    = VisionAgent(drive)
    briefing  = BriefingAgent(
        calendar_connector=calendar,
        slack_connector=slack,
        spotify_connector=spotify,
    ) if calendar else None

    orchestrator = Orchestrator(
        registry=registry,
        messaging_agent=messaging,
        calendar_agent=cal_agent,
        media_agent=media,
        vision_agent=vision,
        briefing_agent=briefing,
    )

    print(f"\n  Active agents: {orchestrator.active_agents}")
    print(f"  Registered tools: {list(registry.list_registered().keys())}\n")

    return orchestrator


# Initialize at startup
orchestrator = bootstrap()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Main chat endpoint — text messages."""
    data       = request.get_json()
    message    = data.get("message", "").strip()
    session_id = data.get("session_id", "default")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        result = orchestrator.chat(message, session_id=session_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/vision", methods=["POST"])
def vision():
    """
    Vision endpoint — accepts image upload + optional message.
    Multipart form: image file + message text.
    """
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400

    file      = request.files["image"]
    message   = request.form.get("message", "What do you see in this image?")
    mime_type = file.content_type or "image/jpeg"
    session_id = request.form.get("session_id", "default")

    # Encode image as base64
    image_b64 = base64.standard_b64encode(file.read()).decode("utf-8")

    try:
        result = orchestrator.chat(
            message=message,
            session_id=session_id,
            image_b64=image_b64,
            mime_type=mime_type,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/briefing", methods=["GET"])
def briefing():
    """Trigger morning briefing directly."""
    session_id = request.args.get("session_id", "default")
    try:
        result = orchestrator.chat("morning briefing", session_id=session_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/reset", methods=["POST"])
def reset():
    """Clear conversation history for a session."""
    data       = request.get_json()
    session_id = data.get("session_id", "default")
    orchestrator._context.clear(session_id)
    return jsonify({"status": "reset"})


@app.route("/api/status", methods=["GET"])
def status():
    """Return active agents and registered tools."""
    return jsonify({
        "active_agents":    orchestrator.active_agents,
        "registered_tools": orchestrator._registry.list_registered(),
        "available_connectors": Config.available_connectors(),
    })


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG,
    )

# The bootstrap sequence is the key design decision here
# — connectors that fail authentication are skipped gracefully
# rather than crashing the whole app. If Atlassian isn't set up yet,
# Jira and Confluence just don't register. Everything else still works.
# The /api/status endpoint lets you see exactly what's active at any time.
