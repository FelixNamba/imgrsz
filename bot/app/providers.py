"""AI image edit providers behind one interface."""
import base64
import io
import logging
from dataclasses import dataclass

import httpx
from PIL import Image

from .config import config
from .pipeline import load

log = logging.getLogger(__name__)


@dataclass
class EditResult:
    data: bytes
    cost_usd: float


class ProviderError(RuntimeError):
    pass


class ImageEditProvider:
    async def edit(self, image: bytes, prompt: str, ratio: str | None) -> EditResult:
        raise NotImplementedError


def _prepare(image: bytes, max_side: int = 2048) -> str:
    """Downscale and re-encode the input to keep provider tokens low."""
    img = load(image)
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    buf = io.BytesIO()
    fmt, mime = ("PNG", "image/png") if img.mode == "RGBA" else ("JPEG", "image/jpeg")
    img.save(buf, fmt, quality=92)
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


class OpenRouterProvider(ImageEditProvider):
    url = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=180)

    async def edit(self, image: bytes, prompt: str, ratio: str | None) -> EditResult:
        body = {
            "model": config.openrouter_model,
            "modalities": ["image", "text"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _prepare(image)}},
                    ],
                }
            ],
            "usage": {"include": True},
        }
        if ratio:
            body["image_config"] = {"aspect_ratio": ratio}
        r = await self.client.post(
            self.url,
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "HTTP-Referer": "https://github.com/felixnamba/imgrsz",
                "X-Title": "imgrsz",
            },
            json=body,
        )
        if r.status_code != 200:
            raise ProviderError(f"openrouter {r.status_code}: {r.text[:300]}")
        d = r.json()
        cost = float(d.get("usage", {}).get("cost") or 0)
        msg = d["choices"][0]["message"]
        images = msg.get("images") or []
        if not images:
            raise ProviderError(f"no image in response: {(msg.get('content') or '')[:300]}")
        url = images[0]["image_url"]["url"]
        return EditResult(base64.b64decode(url.split(",", 1)[1]), cost)


class FakeProvider(ImageEditProvider):
    """Offline stand-in: returns the input (optionally padded to ratio). For tests/dev."""

    async def edit(self, image: bytes, prompt: str, ratio: str | None) -> EditResult:
        from .pipeline import encode, pad_ratio

        img = load(image)
        if ratio:
            img = pad_ratio(img, ratio, "#dddddd")
        return EditResult(encode(img, "png").data, 0.0)


def get_provider() -> ImageEditProvider:
    if config.image_provider == "openrouter":
        return OpenRouterProvider()
    return FakeProvider()
