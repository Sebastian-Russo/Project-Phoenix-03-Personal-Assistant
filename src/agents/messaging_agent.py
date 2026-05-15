"""
Messaging agent — read, summarize, and respond to Slack messages.
Wraps the SlackConnector with Claude-powered summarization and
response drafting. The connector fetches raw data; this agent
decides what's important and what to say back.

Think of it as a smart inbox manager — it reads everything,
surfaces what matters, and drafts responses in your voice.
"""

import os
from typing import Any

import anthropic

from src.models import AgentRequest, AgentResponse, AgentType, MessageSummary, MessagePlatform
from src.connectors.slack_connector import SlackConnector


CLAUDE_MODEL = "claude-sonnet-4-20250514"


class MessagingAgent:

    def __init__(self, slack_connector: SlackConnector):
        self._slack  = slack_connector
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        Route to the correct messaging action based on intent parameters.
        request.parameters expected:
            action       — "read", "summarize", "send", "reply", "unread"
            channel      — channel name (for read/send/reply)
            message      — message text (for send/reply)
            thread_ts    — thread timestamp (for reply)
            limit        — number of messages to read (default 10)
        """
        action = request.parameters.get("action", "summarize")

        handlers = {
            "read":      self._read,
            "summarize": self._summarize,
            "send":      self._send,
            "reply":     self._reply,
            "unread":    self._get_unread,
        }

        handler = handlers.get(action)
        if not handler:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response=f"Unknown action: {action}. Valid actions: {list(handlers.keys())}",
                errors=[f"Unknown action: {action}"],
            )

        return handler(request)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _read(self, request: AgentRequest) -> AgentResponse:
        """Read raw messages from a channel."""
        channel = request.parameters.get("channel")
        limit   = request.parameters.get("limit", 10)

        if not channel:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response="Please specify a channel to read.",
                errors=["Missing channel parameter"],
            )

        try:
            messages = self._slack.execute_tool("slack_read_messages", {
                "channel": channel,
                "limit":   limit,
            })

            if not messages:
                return AgentResponse(
                    success=True,
                    agent=AgentType.MESSAGING,
                    response=f"No messages found in #{channel}.",
                    data=[],
                )

            # Format messages for display
            formatted = "\n".join([
                f"[{m.timestamp.strftime('%H:%M')}] {m.sender}: {m.content}"
                for m in messages
            ])

            return AgentResponse(
                success=True,
                agent=AgentType.MESSAGING,
                response=f"Last {len(messages)} messages in #{channel}:\n\n{formatted}",
                data=messages,
                actions_taken=[f"Read {len(messages)} messages from #{channel}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response=f"Failed to read #{channel}: {e}",
                errors=[str(e)],
            )

    def _summarize(self, request: AgentRequest) -> AgentResponse:
        """
        Read messages and use Claude to summarize them.
        Surfaces action items and important context.
        """
        channel = request.parameters.get("channel")
        limit   = request.parameters.get("limit", 20)

        if not channel:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response="Please specify a channel to summarize.",
                errors=["Missing channel parameter"],
            )

        try:
            messages = self._slack.execute_tool("slack_read_messages", {
                "channel": channel,
                "limit":   limit,
            })

            if not messages:
                return AgentResponse(
                    success=True,
                    agent=AgentType.MESSAGING,
                    response=f"No messages to summarize in #{channel}.",
                    data=None,
                )

            # Format messages for Claude
            transcript = "\n".join([
                f"{m.sender} [{m.timestamp.strftime('%H:%M')}]: {m.content}"
                for m in messages
            ])

            summary = self._claude_summarize(channel, transcript)

            return AgentResponse(
                success=True,
                agent=AgentType.MESSAGING,
                response=summary,
                data=messages,
                actions_taken=[f"Summarized {len(messages)} messages from #{channel}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response=f"Failed to summarize #{channel}: {e}",
                errors=[str(e)],
            )

    def _send(self, request: AgentRequest) -> AgentResponse:
        """Send a message to a channel."""
        channel = request.parameters.get("channel")
        message = request.parameters.get("message")

        if not channel or not message:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response="Please specify both a channel and message to send.",
                errors=["Missing channel or message"],
            )

        try:
            result = self._slack.execute_tool("slack_send_message", {
                "channel": channel,
                "message": message,
            })

            return AgentResponse(
                success=True,
                agent=AgentType.MESSAGING,
                response=f"Message sent to #{channel}.",
                data=result,
                actions_taken=[f"Sent message to #{channel}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response=f"Failed to send message: {e}",
                errors=[str(e)],
            )

    def _reply(self, request: AgentRequest) -> AgentResponse:
        """Reply to a message in a thread."""
        channel   = request.parameters.get("channel")
        message   = request.parameters.get("message")
        thread_ts = request.parameters.get("thread_ts")

        if not all([channel, message, thread_ts]):
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response="Please specify channel, message, and thread_ts to reply.",
                errors=["Missing channel, message, or thread_ts"],
            )

        try:
            result = self._slack.execute_tool("slack_send_message", {
                "channel":   channel,
                "message":   message,
                "thread_ts": thread_ts,
            })

            return AgentResponse(
                success=True,
                agent=AgentType.MESSAGING,
                response="Reply sent.",
                data=result,
                actions_taken=[f"Replied in thread in #{channel}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response=f"Failed to reply: {e}",
                errors=[str(e)],
            )

    def _get_unread(self, request: AgentRequest) -> AgentResponse:
        """Get and summarize all unread messages across channels."""
        try:
            unread = self._slack.execute_tool("slack_get_unread", {})

            if not unread:
                return AgentResponse(
                    success=True,
                    agent=AgentType.MESSAGING,
                    response="No unread messages.",
                    data=[],
                )

            # Summarize each channel's unread messages
            summaries = []
            for ch in unread:
                transcript = "\n".join([
                    f"{m.sender}: {m.content}"
                    for m in ch["messages"]
                ])
                summary = self._claude_summarize(ch["channel"], transcript)
                summaries.append(f"**#{ch['channel']}** ({ch['unread_count']} unread)\n{summary}")

            response = "\n\n".join(summaries)

            return AgentResponse(
                success=True,
                agent=AgentType.MESSAGING,
                response=response,
                data=unread,
                actions_taken=[f"Checked {len(unread)} channels with unread messages"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MESSAGING,
                response=f"Failed to get unread messages: {e}",
                errors=[str(e)],
            )

    # ── Claude helpers ────────────────────────────────────────────────────────

    def _claude_summarize(self, channel: str, transcript: str) -> str:
        """Use Claude to summarize a message transcript."""
        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": f"""Summarize these Slack messages from #{channel}.
Be concise. Surface:
1. Key topics discussed
2. Any decisions made
3. Action items or things needing a response

Messages:
{transcript}

Keep the summary under 150 words."""
            }]
        )
        return resp.content[0].text.strip()

    def draft_reply(self, context: str, tone: str = "professional") -> str:
        """
        Draft a reply to a message using Claude.
        Called by the orchestrator when the user says "reply to that".
        context — the message being replied to + any user instructions
        """
        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": f"""Draft a {tone} reply to this Slack message.
Keep it concise and natural — like how the user would actually write.
Do not add subject lines or sign-offs.

Context:
{context}

Draft the reply only, no other text."""
            }]
        )
        return resp.content[0].text.strip()
