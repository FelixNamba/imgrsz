"""Generate landing images with the bot's own pipeline (real outputs, not mockups).

Usage (repo root):  set -a; . ./credentials.env; set +a
                    .venv/bin/python scripts/landing_assets.py [source|hero|features|all]
Writes to web/assets/img/. Costs ~$0.03 per AI call.
"""
import asyncio
import base64
import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
from app import pipeline  # noqa: E402
from app.config import config  # noqa: E402
from app.providers import OpenRouterProvider  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "assets" / "img"
OUT.mkdir(parents=True, exist_ok=True)
SRC = OUT / "source.jpg"
cost = 0.0

SOURCE_PROMPT = (
    "Studio product photo, square. A matte black blank bank card with an EMV chip and absolutely no logos, "
    "no text, no brand marks, standing upright, slightly turned, resting in soft green velvet fabric. "
    "Dramatic green backlight glow behind, dark green shadows. Photorealistic, sharp, high detail."
)


async def generate(prompt: str, ratio: str = "1:1") -> bytes:
    global cost
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
            json={"model": config.openrouter_model, "modalities": ["image", "text"],
                  "messages": [{"role": "user", "content": prompt}],
                  "image_config": {"aspect_ratio": ratio}, "usage": {"include": True}},
        )
        r.raise_for_status()
        d = r.json()
    cost += float(d.get("usage", {}).get("cost") or 0)
    url = d["choices"][0]["message"]["images"][0]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1])


async def ai_edit(data: bytes, prompt: str, ratio: str | None) -> bytes:
    global cost
    res = await OpenRouterProvider().edit(data, prompt, ratio)
    cost += res.cost_usd
    return res.data


def save(name: str, data: bytes, ops: list[dict]) -> dict:
    res = pipeline.run(data, ops)
    (OUT / f"{name}.{res.ext}").write_bytes(res.data)
    return {"file": f"{name}.{res.ext}", "w": res.width, "h": res.height, "kb": res.kb}


async def source():
    raw = await generate(SOURCE_PROMPT)
    print("source", save("source", raw, [{"op": "resize", "mode": "fit", "width": 1200}, {"op": "format", "format": "jpeg"}]))


async def hero():
    src = SRC.read_bytes()
    print("before", pipeline.describe(src))
    # Gemini outputs at most 21:9 and ignores "zoom out", so: place the photo small on a wide gray canvas
    # (Pillow), let the AI fill only the gray area, then crop the 468x60 (7.8:1) band — the whole card fits.
    img = pipeline.load(src).convert("RGB")
    img.thumbnail((560, 560), Image.LANCZOS)
    canvas = Image.new("RGB", (2100, 900), (128, 128, 128))
    canvas.paste(img, ((2100 - img.width) // 2, (900 - img.height) // 2))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=95)
    wider = await ai_edit(buf.getvalue(), "The photo in the center is surrounded by flat gray empty areas. Fill all gray areas "
                                          "by seamlessly continuing the dark green velvet fabric and the green backlit background "
                                          "of the central photo, so it becomes one natural wide photo. Do not change the card.", "21:9")
    print("hero", save("hero_after", wider, [{"op": "resize", "mode": "fill", "width": 468, "height": 60}, {"op": "format", "format": "jpeg"}]))
    print("hero_2x", save("hero_after@2x", wider, [{"op": "resize", "mode": "fill", "width": 936, "height": 120}, {"op": "format", "format": "jpeg"}]))


async def features():
    src = SRC.read_bytes()
    meta = {}
    # 1. resize: 1:1 → 9:16 story (AI extension keeps it honest: the bot extends instead of cropping)
    meta["resize_before"] = save("f_resize_before", src, [{"op": "resize", "mode": "fit", "width": 480}, {"op": "format", "format": "webp"}])
    meta["resize_after"] = save("f_resize_after", src, [{"op": "crop_ratio", "ratio": "16:9"}, {"op": "resize", "mode": "exact", "width": 1280, "height": 720}, {"op": "format", "format": "webp"}])
    # 2. upscale: tiny → AI enhance
    tiny = pipeline.run(src, [{"op": "resize", "mode": "fit", "width": 160}, {"op": "format", "format": "jpeg"}, {"op": "max_size_kb", "kb": 6}])
    (OUT / "f_upscale_before.jpg").write_bytes(tiny.data)  # landing shows a cropped fragment, pixelated via CSS
    meta["upscale_before"] = {"file": "f_upscale_before.jpg", "w": tiny.width, "h": tiny.height, "kb": tiny.kb}
    up = await ai_edit(tiny.data, "Upscale and restore this low-resolution photo: recover sharp detail and texture, remove "
                                  "JPEG artifacts and blur. Keep composition, colors and the card exactly the same.", "1:1")
    meta["upscale_after"] = save("f_upscale_after", up, [{"op": "resize", "mode": "fit", "width": 480}, {"op": "format", "format": "webp"}])
    meta["upscale_after"]["orig"] = pipeline.describe(up)
    # 3. file size: original → ≤100 KB JPG
    big = pipeline.run(src, [{"op": "format", "format": "png"}])
    small = pipeline.run(src, [{"op": "format", "format": "jpeg"}, {"op": "max_size_kb", "kb": 100}])
    meta["weight"] = {"before_kb": big.kb, "after_kb": small.kb, "w": small.width, "h": small.height}
    save("f_weight", small.data, [{"op": "resize", "mode": "fit", "width": 480}, {"op": "format", "format": "webp"}])
    # 4. background → clean white studio
    bg = await ai_edit(src, "Replace the background and the fabric with a clean pure white seamless studio background with a soft "
                            "natural shadow under the card. Keep the card exactly unchanged.", "1:1")
    meta["bg_after"] = save("f_bg_after", bg, [{"op": "resize", "mode": "fit", "width": 480}, {"op": "format", "format": "webp"}])
    # 5. monochrome
    meta["mono_after"] = save("f_mono_after", src, [{"op": "grayscale"}, {"op": "resize", "mode": "fit", "width": 480}, {"op": "format", "format": "webp"}])
    (OUT / "features.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(json.dumps(meta, ensure_ascii=False))


async def main(what: str):
    if what in ("source", "all"):
        await source()
    if what in ("hero", "all"):
        await hero()
    if what in ("features", "all"):
        await features()
    print(f"total AI cost: ${cost:.3f}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
