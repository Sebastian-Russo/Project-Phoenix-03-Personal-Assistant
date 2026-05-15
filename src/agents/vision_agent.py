"""
Vision agent — analyze images, extract structured data, route to destination.
Uses Claude's vision capability to read photos of forms, documents,
receipts, code, and anything else you point a camera at.

Think of it as a smart scanner that not only reads the image but
decides what to do with it — save to Drive, drop into a repo,
or just show you the extracted data.

Flow:
    Image (base64) → Claude Vision → extracted data + content type
    → user confirms destination → Drive upload or local file save
"""

import base64
import os
from pathlib import Path
from typing import Any, Optional

import anthropic

from src.models import AgentRequest, AgentResponse, AgentType, ImageAnalysis


CLAUDE_MODEL = "claude-sonnet-4-20250514"


class VisionAgent:

    def __init__(self, drive_connector=None):
        """
        drive_connector — optional GoogleDriveConnector.
        If provided, agent can upload directly to Drive.
        If None, Drive upload is skipped and local save is the only option.
        """
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._drive  = drive_connector

    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        Main entry point.
        request.parameters expected:
            image_path   — local path to image file
            image_base64 — base64 encoded image (alternative to path)
            mime_type    — image MIME type (default: image/jpeg)
            destination  — "drive", "local", or "display" (default: display)
            folder_id    — Drive folder ID (if destination=drive)
            local_path   — local file path (if destination=local)
        """
        params    = request.parameters
        image_b64 = self._load_image(params)

        if not image_b64:
            return AgentResponse(
                success=False,
                agent=AgentType.VISION,
                response="Could not load image — provide image_path or image_base64.",
                errors=["No image provided"],
            )

        mime_type = params.get("mime_type", "image/jpeg")

        # Step 1: Analyze the image
        try:
            analysis = self._analyze(image_b64, mime_type)
        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.VISION,
                response=f"Image analysis failed: {e}",
                errors=[str(e)],
            )

        # Step 2: Route to destination
        destination   = params.get("destination", "display")
        actions_taken = []

        if destination == "drive" and self._drive:
            try:
                result = self._upload_to_drive(
                    analysis=analysis,
                    folder_id=params.get("folder_id"),
                    original_path=params.get("image_path"),
                )
                actions_taken.append(f"Uploaded to Drive: {result.get('web_link')}")
            except Exception as e:
                return AgentResponse(
                    success=False,
                    agent=AgentType.VISION,
                    response=f"Drive upload failed: {e}",
                    errors=[str(e)],
                )

        elif destination == "local":
            try:
                local_path = params.get("local_path")
                if not local_path:
                    raise ValueError("local_path required for destination=local")
                self._save_locally(analysis, local_path)
                actions_taken.append(f"Saved locally: {local_path}")
            except Exception as e:
                return AgentResponse(
                    success=False,
                    agent=AgentType.VISION,
                    response=f"Local save failed: {e}",
                    errors=[str(e)],
                )

        # Step 3: Build natural language response
        response = self._format_response(analysis, destination, actions_taken)

        return AgentResponse(
            success=True,
            agent=AgentType.VISION,
            response=response,
            data=analysis,
            actions_taken=actions_taken,
        )

    def _load_image(self, params: dict) -> Optional[str]:
        """Load image as base64 from path or direct base64 input."""
        if "image_base64" in params:
            return params["image_base64"]

        if "image_path" in params:
            path = Path(params["image_path"])
            if not path.exists():
                print(f"[vision] Image not found: {path}")
                return None
            with open(path, "rb") as f:
                return base64.standard_b64encode(f.read()).decode("utf-8")

        return None

    def _analyze(self, image_b64: str, mime_type: str) -> ImageAnalysis:
        """
        Send image to Claude Vision and extract structured data.
        Claude identifies the content type and pulls out key information.
        """
        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type":       "base64",
                                "media_type": mime_type,
                                "data":       image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": """Analyze this image and respond in this exact JSON format:
{
    "content_type": "one of: form, code, document, receipt, invoice, handwriting, screenshot, diagram, other",
    "extracted": {
        "key": "value pairs of all important data found in the image"
    },
    "raw_text": "all text visible in the image",
    "suggested_destination": "suggested filename or folder name for saving this content",
    "confidence": 0.95
}

For code images: extract the language and full code in extracted.code
For forms: extract all field labels and their values
For receipts/invoices: extract merchant, date, items, total
For documents: extract title, date, key points
Only return valid JSON, no other text."""
                        }
                    ],
                }
            ],
        )

        import json
        raw  = resp.content[0].text.strip()
        data = json.loads(raw)

        return ImageAnalysis(
            content_type=data.get("content_type", "other"),
            extracted=data.get("extracted", {}),
            raw_text=data.get("raw_text", ""),
            suggested_destination=data.get("suggested_destination"),
            confidence=float(data.get("confidence", 0.0)),
        )

    def _upload_to_drive(
        self,
        analysis:      ImageAnalysis,
        folder_id:     Optional[str],
        original_path: Optional[str],
    ) -> dict:
        """Upload extracted content to Google Drive as a text file."""
        import json

        filename = analysis.suggested_destination or "extracted_content.txt"
        if not filename.endswith(".txt"):
            filename += ".txt"

        content = f"Content Type: {analysis.content_type}\n"
        content += f"Confidence: {analysis.confidence:.0%}\n\n"
        content += "── Extracted Data ──\n"
        content += json.dumps(analysis.extracted, indent=2)
        content += "\n\n── Raw Text ──\n"
        content += analysis.raw_text

        return self._drive.execute_tool("drive_upload_bytes", {
            "filename":  filename,
            "content":   content,
            "folder_id": folder_id,
            "mime_type": "text/plain",
        })

    def _save_locally(self, analysis: ImageAnalysis, local_path: str) -> None:
        """Save extracted content to a local file."""
        import json

        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        content = f"Content Type: {analysis.content_type}\n"
        content += f"Confidence: {analysis.confidence:.0%}\n\n"
        content += "── Extracted Data ──\n"
        content += json.dumps(analysis.extracted, indent=2)
        content += "\n\n── Raw Text ──\n"
        content += analysis.raw_text

        path.write_text(content)
        print(f"[vision] Saved to {local_path}")

    def _format_response(
        self,
        analysis:      ImageAnalysis,
        destination:   str,
        actions_taken: list[str],
    ) -> str:
        """Build a natural language summary of what was found and done."""
        lines = [f"I analyzed the image and found a **{analysis.content_type}**."]

        if analysis.extracted:
            lines.append("\nExtracted data:")
            for key, val in analysis.extracted.items():
                if isinstance(val, str) and len(val) < 200:
                    lines.append(f"  • {key}: {val}")

        if analysis.raw_text:
            preview = analysis.raw_text[:200]
            if len(analysis.raw_text) > 200:
                preview += "..."
            lines.append(f"\nRaw text preview: {preview}")

        if actions_taken:
            lines.append("\nActions taken:")
            for action in actions_taken:
                lines.append(f"  ✓ {action}")
        elif destination == "display":
            lines.append("\nNo file saved — use destination='drive' or 'local' to save.")

        return "\n".join(lines)
