"""
Orchestrator — the brain of Phoenix 03.
Receives every user message, consults the router for intent,
dispatches to the right agent, manages conversation history,
and handles multi-step requests that span multiple agents.

Think of it as an air traffic controller — it doesn't fly the planes
(agents do that), but it decides who goes where and in what order,
and makes sure everything lands cleanly.
"""

import json
import os
from typing import Optional

import anthropic

from src.models import (
    AgentRequest, AgentResponse, AgentType, IntentType
)
from src.router import Router
from src.memory.context_store import ContextStore
from src.tools.tool_registry import ToolRegistry
from src.agents.messaging_agent import MessagingAgent
from src.agents.calendar_agent import CalendarAgent
from src.agents.media_agent import MediaAgent
from src.agents.vision_agent import VisionAgent
from src.agents.briefing_agent import BriefingAgent


CLAUDE_MODEL = "claude-sonnet-4-20250514"


class Orchestrator:

    def __init__(
        self,
        registry:         ToolRegistry,
        messaging_agent:  Optional[MessagingAgent]  = None,
        calendar_agent:   Optional[CalendarAgent]   = None,
        media_agent:      Optional[MediaAgent]       = None,
        vision_agent:     Optional[VisionAgent]      = None,
        briefing_agent:   Optional[BriefingAgent]    = None,
    ):
        self._registry  = registry
        self._router    = Router()
        self._context   = ContextStore()
        self._client    = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        # Specialist agents — None if connector not authenticated
        self._agents = {
            AgentType.MESSAGING: messaging_agent,
            AgentType.CALENDAR:  calendar_agent,
            AgentType.MEDIA:     media_agent,
            AgentType.VISION:    vision_agent,
            AgentType.BRIEFING:  briefing_agent,
        }

    def chat(
        self,
        message:    str,
        session_id: str = "default",
        image_b64:  Optional[str] = None,
        mime_type:  str = "image/jpeg",
    ) -> dict:
        """
        Main entry point — process a user message and return a response.

        Returns:
            {
                "response":    str,        natural language response
                "agent_used":  str,        which agent handled it
                "tools_used":  list[str],  tools that were called
                "success":     bool,
            }
        """
        # Get conversation history for this session
        history = self._context.get_history(session_id)

        # Handle image input — route directly to vision agent
        if image_b64:
            return self._handle_image(
                message, image_b64, mime_type, session_id, history
            )

        # Classify intent and build request
        request = self._router.route(message, history)

        # Add user turn to context
        self._context.add_turn(session_id, "user", message)

        # Dispatch to specialist agent or handle directly
        response = self._dispatch(request, session_id)

        # Add assistant turn to context
        self._context.add_turn(
            session_id,
            "assistant",
            response.response,
            tools_used=response.actions_taken,
        )

        # Inject structured data into context for follow-up references
        if response.data:
            self._inject_data_context(session_id, request.intent, response.data)

        return {
            "response":   response.response,
            "agent_used": response.agent.value,
            "tools_used": response.actions_taken,
            "success":    response.success,
            "errors":     response.errors,
        }

    def _dispatch(self, request: AgentRequest, session_id: str) -> AgentResponse:
        """
        Route the request to the correct agent.
        Falls back to Claude direct if no specialist agent is available.
        """
        agent_type = self._router.get_agent_type(request.intent)
        agent      = self._agents.get(agent_type)

        # Specialist agent available — use it
        if agent:
            print(f"[orchestrator] Dispatching to {agent_type.value}")
            return agent.handle(request)

        # No specialist agent — handle with Claude + tool registry
        print(f"[orchestrator] No specialist agent for {agent_type.value} — using direct Claude")
        return self._handle_with_claude(request)

    def _handle_with_claude(self, request: AgentRequest) -> AgentResponse:
        """
        Handle a request directly with Claude using the tool registry.
        Used for intents without a specialist agent (e.g. GitHub, Confluence)
        and for complex multi-step requests.

        This is the agentic loop:
        1. Give Claude the user message + all available tools
        2. Claude decides which tools to call
        3. Execute the tools
        4. Feed results back to Claude
        5. Claude formulates final response
        6. Repeat if Claude wants more tool calls
        """
        tools   = self._registry.get_all_tools()
        history = request.context + [{"role": "user", "content": request.raw_input}]

        # System prompt that defines Claude's persona and capabilities
        system = """You are Phoenix, a personal AI assistant with access to the user's
apps and services. You can read and send Slack messages, manage Google Calendar,
control Spotify, search GitHub repos, read Jira issues, and search Confluence.

When the user asks you to do something:
1. Use the available tools to gather information or take action
2. Be concise in your final response — summarize what you did and found
3. If a task requires multiple steps, complete them all before responding
4. If something fails, explain what went wrong and what you tried

Always act on behalf of the user — don't just describe what you could do."""

        actions_taken = []
        max_iterations = 5  # prevent infinite loops

        for _ in range(max_iterations):
            resp = self._client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                system=system,
                tools=tools,
                messages=history,
            )

            # No tool calls — Claude has a final answer
            if resp.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in resp.content if hasattr(b, "text")),
                    "Done."
                )
                return AgentResponse(
                    success=True,
                    agent=AgentType.ORCHESTRATOR,
                    response=final_text,
                    actions_taken=actions_taken,
                )

            # Process tool calls
            if resp.stop_reason == "tool_use":
                tool_results = []

                for block in resp.content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input
                    print(f"[orchestrator] Tool call: {tool_name} {tool_input}")

                    try:
                        result = self._registry.execute(tool_name, tool_input)
                        result_text = json.dumps(result, default=str)
                        actions_taken.append(f"{tool_name}({tool_input})")
                    except Exception as e:
                        result_text = f"Error: {e}"
                        print(f"[orchestrator] Tool error: {e}")

                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result_text,
                    })

                # Add Claude's response and tool results to history
                history.append({"role": "assistant", "content": resp.content})
                history.append({"role": "user",      "content": tool_results})

            else:
                # Unexpected stop reason
                break

        return AgentResponse(
            success=True,
            agent=AgentType.ORCHESTRATOR,
            response="I completed the requested actions.",
            actions_taken=actions_taken,
        )

    def _handle_image(
        self,
        message:    str,
        image_b64:  str,
        mime_type:  str,
        session_id: str,
        history:    list[dict],
    ) -> dict:
        """Route image + message to VisionAgent."""
        vision = self._agents.get(AgentType.VISION)

        if not vision:
            return {
                "response":   "Vision agent not available.",
                "agent_used": "none",
                "tools_used": [],
                "success":    False,
                "errors":     ["VisionAgent not initialized"],
            }

        request = AgentRequest(
            intent=IntentType.ANALYZE_IMAGE,
            raw_input=message,
            parameters={
                "image_base64": image_b64,
                "mime_type":    mime_type,
                "destination":  "display",  # default — user can override
            },
            context=history,
        )

        self._context.add_turn(session_id, "user", f"[image] {message}")
        response = vision.handle(request)
        self._context.add_turn(session_id, "assistant", response.response)

        return {
            "response":   response.response,
            "agent_used": response.agent.value,
            "tools_used": response.actions_taken,
            "success":    response.success,
            "errors":     response.errors,
        }

    def _inject_data_context(
        self,
        session_id: str,
        intent:     IntentType,
        data:       object,
    ) -> None:
        """
        Inject structured data into context for follow-up references.
        Allows "reply to that" to work because Claude has the
        message details in its history.
        """
        if intent == IntentType.READ_MESSAGES and data:
            try:
                messages = data if isinstance(data, list) else []
                if messages:
                    latest = messages[0]
                    self._context.inject_context(
                        session_id,
                        "last_message",
                        f"Last message from {latest.sender} in "
                        f"#{latest.channel}: '{latest.content}' "
                        f"(thread_ts: {latest.id})"
                    )
            except Exception:
                pass

        elif intent == IntentType.READ_CALENDAR and data:
            try:
                events = data if isinstance(data, list) else []
                if events:
                    next_event = events[0]
                    self._context.inject_context(
                        session_id,
                        "next_event",
                        f"Next event: '{next_event.title}' at "
                        f"{next_event.start.strftime('%I:%M %p')} "
                        f"(id: {next_event.id})"
                    )
            except Exception:
                pass

    @property
    def active_agents(self) -> list[str]:
        """Return names of initialized agents."""
        return [
            agent_type.value
            for agent_type, agent in self._agents.items()
            if agent is not None
        ]

