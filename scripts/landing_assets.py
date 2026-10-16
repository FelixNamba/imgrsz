"""Generate landing images with the bot's own pipeline (real outputs, not mockups).

Usage (repo root):  set -a; . ./credentials.env; set +a
                    .venv/bin/python scripts/landing_assets.py [source|logo|hero|features|all]
Writes to web/assets/img/. Costs ~$0.03 per AI call.
"""
import asyncio
import base64
import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
from app import extend, pipeline  # noqa: E402
from app.config import config  # noqa: E402
from app.providers import OpenRouterProvider  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "web" / "assets" / "img"
OUT.mkdir(parents=True, exist_ok=True)
SRC = OUT / "source.jpg"
HERO_SRC = Path(__file__).resolve().parents[1] / "initial" / "ch_pski-LzId5ONySUI-unsplash.jpg"  # Unsplash, gitignored
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
    """Hero: the bot's real 'upsize to 5120x1440 and compress' run on a photo from initial/ (bot's extend.py)."""
    global cost
    raw = HERO_SRC.read_bytes()
    before = pipeline.describe(raw)
    img, c, calls = await extend.extend(OpenRouterProvider(), raw, "5120:1440")
    cost += c
    full = pipeline.encode(img.resize((5120, 1440), Image.LANCZOS), "jpeg", max_kb=900)
    (OUT / "hero_after.jpg").write_bytes(full.data)  # full-size result, downloadable from the site
    clean = pipeline.run(raw, [{"op": "format", "format": "jpeg"}])  # source without metadata
    (OUT / "hero_before.jpg").write_bytes(clean.data)
    meta = {"before": before, "before_jpg_kb": clean.kb, "after": {"w": full.width, "h": full.height, "kb": full.kb, "calls": calls}}
    meta["before_web"] = save("hero_before", raw, [{"op": "resize", "mode": "fit", "width": 480}, {"op": "format", "format": "webp"}])
    meta["after_web"] = save("hero_after", full.data, [{"op": "resize", "mode": "fit", "width": 1280}, {"op": "format", "format": "webp"}])
    (OUT / "hero.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(json.dumps(meta, ensure_ascii=False))


def logo():
    """Brand mark: lower-right logo from initial/resize_logos.png, cut to a circle with transparent corners."""
    sheet = Image.open(Path(__file__).resolve().parents[1] / "initial" / "resize_logos.png").convert("RGB")
    tile = sheet.crop((662, 657, 1121, 1116)).resize((256, 256), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (1024, 1024), 0)
    ImageDraw.Draw(mask).ellipse((6, 6, 1018, 1018), fill=255)
    tile.putalpha(mask.resize((256, 256), Image.LANCZOS))
    tile.save(OUT / "logo.png", optimize=True)
    tile.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png", optimize=True)


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
    if what in ("logo", "all"):
        logo()
    if what in ("hero", "all"):
        await hero()
    if what in ("features", "all"):
        await features()
    print(f"total AI cost: ${cost:.3f}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
