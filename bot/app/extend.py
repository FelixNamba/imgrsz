"""AI outpainting to any aspect ratio, keeping the whole source image.

Image models only output a few ratios (at most 21:9 / 9:16) and tend to crop or
reframe when asked to "zoom out". So we build the canvas ourselves: the source is
pasted at native resolution onto a gray canvas of the target ratio, and the model
only fills the gray parts. Ratios wider than the model allows are filled window by
window (each window is a supported ratio and overlaps already-filled pixels).
Only previously-gray pixels are taken from the model, so the source stays intact.
The model sometimes leaves a gray band; such bands stay "unfilled" and get another window.
"""
import io

from PIL import Image, ImageChops, ImageFilter

from .pipeline import load
from .plan import AI_RATIOS
from .prompts import EXTEND as PROMPT
from .providers import ImageEditProvider

GRAY = (128, 128, 128)
MAX_CALLS = 6
FEATHER = 32  # px
OVERLAP = 0.4  # share of every window taken from already-filled pixels (context for the model)
_RATIOS = {r: (lambda a, b: a / b)(*map(int, r.split(":"))) for r in AI_RATIOS}
_MAX_W, _MAX_T = max(_RATIOS.values()), min(_RATIOS.values())  # 21:9 and 9:16


def ratio_value(r: str) -> float:
    a, b = map(int, r.split(":"))
    return a / b


def _layout(w: int, h: int, r: float):
    """Canvas size, source box and axis. Source keeps native size (clamped to a sane working size)."""
    scale = min(1.0, 2048 / max(w, h)) if max(w, h) > 2048 else max(1.0, 768 / min(w, h))
    w, h = round(w * scale), round(h * scale)
    if r >= w / h:  # wider: extend left/right
        cw, ch = max(w, round(h * r)), h
        return (cw, ch), ((cw - w) // 2, 0, w, h), True
    cw, ch = w, max(h, round(w / r))
    return (cw, ch), (0, (ch - h) // 2, w, h), False


def _nearest(r: float) -> str:
    return min(_RATIOS, key=lambda k: abs(_RATIOS[k] - r))


def next_window(filled: list[bool], win: int) -> tuple[int, int] | None:
    """Pick the next window along the axis: it covers the gray run closest to filled pixels
    and keeps OVERLAP of the window on filled pixels. None when everything is filled."""
    n = len(filled)
    if all(filled):
        return None
    if win >= n:
        return 0, n
    for i in range(n - 1):  # a gray run right after a filled pixel -> extend to the right
        if filled[i] and not filled[i + 1]:
            a = max(0, min(i + 1 - round(win * OVERLAP), n - win))
            right = (a, a + win)
            break
    else:
        right = None
    for i in range(n - 1, 0, -1):  # a gray run right before a filled pixel -> extend to the left
        if filled[i] and not filled[i - 1]:
            b = min(n, max(i + round(win * OVERLAP), win))
            left = (b - win, b)
            break
    else:
        left = None
    # fill the side with more gray first so both sides grow evenly
    if left and right:
        gray_left, gray_right = filled.index(True), n - 1 - filled[::-1].index(True)
        return left if gray_left >= n - 1 - gray_right else right
    return left or right


def _gray_lines(img: Image.Image, horizontal: bool) -> list[bool]:
    """Per column (horizontal) or row: True if the line is still flat canvas gray (model skipped it)."""
    diff = ImageChops.difference(img, Image.new("RGB", img.size, GRAY)).convert("L").point(lambda v: 255 if v > 10 else 0)
    line = diff.resize((img.width, 1) if horizontal else (1, img.height), Image.BOX)
    return [v < 13 for v in line.get_flattened_data()]  # < 5% non-gray pixels


async def _fill(provider: ImageEditProvider, canvas: Image.Image, filled: Image.Image, box: tuple, ratio: str,
                horizontal: bool) -> float:
    """Ask the model to fill the gray part of canvas[box]; paste back only the unfilled pixels."""
    tile = canvas.crop(box)
    buf = io.BytesIO()
    tile.save(buf, "JPEG", quality=95)
    res = await provider.edit(buf.getvalue(), PROMPT, ratio)
    out = load(res.data).convert("RGB").resize(tile.size, Image.LANCZOS)
    # Mask = unfilled area plus a 32 px ramp into filled pixels, so tone shifts of the model blend out.
    mask = filled.crop(box).point(lambda v: 255 - v).filter(ImageFilter.BoxBlur(FEATHER)).point(lambda v: min(255, v * 2))
    canvas.paste(out, box[:2], mask)
    # Mark the window filled, except lines the model left gray.
    still_gray = _gray_lines(canvas.crop(box), horizontal)
    done = Image.new("L", tile.size, 255)
    for i, gray in enumerate(still_gray):
        if gray:
            done.paste(0, (i, 0, i + 1, tile.height) if horizontal else (0, i, tile.width, i + 1))
    filled.paste(ImageChops.lighter(filled.crop(box), done), box[:2])
    return res.cost_usd


def _axis_filled(filled: Image.Image, horizontal: bool) -> list[bool]:
    line = filled.resize((filled.width, 1) if horizontal else (1, filled.height), Image.BOX)
    return [v > 250 for v in line.get_flattened_data()]


async def extend(provider: ImageEditProvider, data: bytes, target: str) -> tuple[Image.Image, float, int]:
    """Returns (image with target ratio, provider cost in USD, number of model calls)."""
    src = load(data).convert("RGB")
    (cw, ch), (x, y, w, h), horizontal = _layout(src.width, src.height, ratio_value(target))
    src = src.resize((w, h), Image.LANCZOS) if (w, h) != src.size else src
    canvas = Image.new("RGB", (cw, ch), GRAY)
    canvas.paste(src, (x, y))
    filled = Image.new("L", (cw, ch), 0)
    filled.paste(255, (x, y, x + w, y + h))
    if (cw, ch) == (w, h):
        return canvas, 0.0, 0

    r = cw / ch
    crop = None
    if _MAX_T <= r <= _MAX_W:
        # Pad to the nearest ratio the model supports (one window), crop back at the end.
        ratio = _nearest(r)
        rv = _RATIOS[ratio]
        bw, bh = (max(cw, round(ch * rv)), ch) if rv >= r else (cw, max(ch, round(cw / rv)))
        big, big_filled = Image.new("RGB", (bw, bh), GRAY), Image.new("L", (bw, bh), 0)
        ox, oy = (bw - cw) // 2, (bh - ch) // 2
        big.paste(canvas, (ox, oy))
        big_filled.paste(filled, (ox, oy))
        canvas, filled, crop = big, big_filled, (ox, oy, ox + cw, oy + ch)
        horizontal = bw / bh >= cw / ch
        win = bw if horizontal else bh
    elif horizontal:
        ratio, win = "21:9", round(ch * _MAX_W)
    else:
        ratio, win = "9:16", round(cw / _MAX_T)

    cost, calls = 0.0, 0
    while calls < MAX_CALLS:
        span = next_window(_axis_filled(filled, horizontal), win)
        if span is None:
            break
        box = (span[0], 0, span[1], canvas.height) if horizontal else (0, span[0], canvas.width, span[1])
        cost += await _fill(provider, canvas, filled, box, ratio, horizontal)
        calls += 1
    if not all(_axis_filled(filled, horizontal)):
        raise ValueError(f"AI left gray areas after {calls} calls")
    return (canvas.crop(crop) if crop else canvas), cost, calls
