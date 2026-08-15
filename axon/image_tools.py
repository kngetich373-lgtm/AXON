"""Image generation, editing, and local poster tools."""
from __future__ import annotations

import base64
from datetime import datetime
import mimetypes
from pathlib import Path

import requests

from .actions import ActionResult
from .config import AXON_OUTPUT_DIR, OPENAI_IMAGE_MODEL


class ImageService:
    generation_endpoint = "https://api.openai.com/v1/images/generations"
    edit_endpoint = "https://api.openai.com/v1/images/edits"

    def __init__(self, api_key: str = "", output_dir: Path | None = None, model: str | None = None):
        self.api_key = str(api_key or "").strip()
        self.output_dir = (output_dir or AXON_OUTPUT_DIR).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.model = model or OPENAI_IMAGE_MODEL

    def _output(self, prefix: str, suffix: str = ".png") -> Path:
        return self.output_dir / f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{suffix}"

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _response_image(response) -> bytes | None:
        try:
            encoded = response.json().get("data", [{}])[0].get("b64_json", "")
            return base64.b64decode(encoded) if encoded else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _api_error(response) -> str:
        try:
            return str(response.json().get("error", {}).get("message", "Image API request failed."))[:500]
        except ValueError:
            return f"Image API request failed with HTTP {response.status_code}."

    def generate(self, prompt: str, size: str = "1024x1024") -> ActionResult:
        if not self.api_key:
            return ActionResult.failure("Image generation is not configured. Add OPENAI_API_KEY to .env and restart AXON.")
        if not str(prompt).strip():
            return ActionResult.failure("Describe the image you want to generate.")
        try:
            response = requests.post(
                self.generation_endpoint, headers={**self._headers(), "Content-Type": "application/json"},
                json={"model": self.model, "prompt": str(prompt).strip(), "size": size}, timeout=120,
            )
        except requests.RequestException as exc:
            return ActionResult.failure("Image generation request failed.", str(exc))
        if not response.ok:
            return ActionResult.failure(self._api_error(response))
        image = self._response_image(response)
        if not image:
            return ActionResult.failure("The image provider returned no image data.")
        target = self._output("generated")
        target.write_bytes(image)
        return ActionResult.success(f"Generated image saved to {target}.", path=str(target))

    def edit(self, source: str | Path, prompt: str) -> ActionResult:
        source = Path(source).expanduser().resolve()
        if not self.api_key:
            return ActionResult.failure("Image editing is not configured. Add OPENAI_API_KEY to .env and restart AXON.")
        if not source.is_file():
            return ActionResult.failure("Choose an existing image to edit.")
        if not str(prompt).strip():
            return ActionResult.failure("Describe the image edit you want.")
        mime = mimetypes.guess_type(source.name)[0] or "image/png"
        try:
            with source.open("rb") as handle:
                response = requests.post(
                    self.edit_endpoint, headers=self._headers(),
                    data={"model": self.model, "prompt": str(prompt).strip()},
                    files={"image[]": (source.name, handle, mime)}, timeout=120,
                )
        except (OSError, requests.RequestException) as exc:
            return ActionResult.failure("Image editing request failed.", str(exc))
        if not response.ok:
            return ActionResult.failure(self._api_error(response))
        image = self._response_image(response)
        if not image:
            return ActionResult.failure("The image provider returned no edited image data.")
        target = self._output("edited")
        target.write_bytes(image)
        return ActionResult.success(f"Edited image saved to {target}; the original was not changed.", path=str(target), source=str(source))

    def poster(self, title: str, subtitle: str = "", colors: tuple[str, str] = ("#1d4ed8", "#0f172a"), size: tuple[int, int] = (1080, 1350)) -> ActionResult:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return ActionResult.failure("Poster generation needs Pillow. Run: python -m pip install -r requirements.txt")
        target = self._output("poster")
        try:
            image = Image.new("RGB", size, colors[1])
            draw = ImageDraw.Draw(image)
            for y in range(size[1]):
                ratio = y / max(1, size[1] - 1)
                start = tuple(int(colors[0].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
                end = tuple(int(colors[1].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
                draw.line((0, y, size[0], y), fill=tuple(int(a * (1 - ratio) + b * ratio) for a, b in zip(start, end)))
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(42, size[0] // 14))
            subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", max(24, size[0] // 30))
            draw.multiline_text((size[0] * 0.08, size[1] * 0.36), title[:180], font=title_font, fill="white", spacing=10)
            draw.multiline_text((size[0] * 0.08, size[1] * 0.66), subtitle[:300], font=subtitle_font, fill="#dbeafe", spacing=8)
            image.save(target, "PNG")
        except (OSError, ValueError) as exc:
            return ActionResult.failure("AXON could not create that poster.", str(exc))
        return ActionResult.success(f"Poster saved to {target}.", path=str(target))

    def resize(self, source: str | Path, width: int, height: int) -> ActionResult:
        try:
            from PIL import Image
        except ImportError:
            return ActionResult.failure("Image resizing needs Pillow. Run: python -m pip install -r requirements.txt")
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            return ActionResult.failure("Choose an existing image to resize.")
        target = self._output("resized")
        try:
            with Image.open(source) as image:
                image.resize((int(width), int(height))).save(target)
        except (OSError, ValueError) as exc:
            return ActionResult.failure("AXON could not resize that image.", str(exc))
        return ActionResult.success(f"Resized image saved to {target}; the original was not changed.", path=str(target))
