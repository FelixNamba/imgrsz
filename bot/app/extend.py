"""AI outpainting to any aspect ratio, keeping the whole source image.

Image models only output a few ratios (at most 21:9 / 9:16) and tend to crop or
reframe when asked to "zoom out". So we build the canvas ourselves: the source is
pasted at native resolution onto a gray canvas of the target ratio, and the model
only fills the gray parts. Ratios wider than the model allows are filled window by
window (each window is a supported ratio and overlaps already-filled pixels).
Only previously-gray pixels are taken from the model, so the source stays intact.
The model sometimes leaves a gray band; such bands stay "unfilled" and get another window.
Every model answer is checked against the source in a band along the seam: a model that
reframed or re-imagined the window fails the check and the window is retried. Accepted
answers are matched to the source in colour and sharpness before they are blended in.
"""
import io
import logging

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .pipeline import load
from .plan import AI_RATIOS
from .prompts import EXTEND as PROMPT
from .providers import ImageEditProvider

log = logging.getLogger(__name__)

GRAY = (128, 128, 128)
MAX_CALLS = 6
RETRIES = 2  # extra calls per window when the answer does not match the source
FEATHER = 0.08  # blend width as a share of the window along the extension axis
SEAM_BAND = 0.05  # share of the window: source pixels next to the gray area used for checks
SEAM_MAX_DIFF = 12  # mean |model - source| in the seam band (0..255, blurred) above this = reframed; good answers ~3
SEAM_MAX_JUMP = 3.0  # jump across the seam vs the same measure next to it; good ~1, visible line ~10+
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


def _seam_band(known: Image.Image, width: int) -> Image.Image:
    """Mask of known pixels within `width` px of the gray area."""
    near_gray = known.point(lambda v: 255 - v).filter(ImageFilter.BoxBlur(width)).point(lambda v: 255 if v else 0)
    return ImageChops.multiply(near_gray, known)


def seam_diff(tile: Image.Image, out: Image.Image, band: Image.Image) -> float:
    """How far the model moved away from the source along the seam. Blurred first, so new
    detail or noise does not count, only shifted, rescaled or replaced content."""
    a = tile.convert("L").filter(ImageFilter.GaussianBlur(4))
    b = out.convert("L").filter(ImageFilter.GaussianBlur(4))
    return ImageStat.Stat(ImageChops.difference(a, b), mask=band).mean[0]


def _jump(img: Image.Image, b: int, k: int = 3) -> float:
    """Mean per-row difference between the k columns left and right of column b."""
    h = img.height
    left = img.crop((max(0, b - k), 0, b, h)).resize((1, max(1, h // 4)), Image.BOX)
    right = img.crop((b, 0, min(img.width, b + k), h)).resize((1, max(1, h // 4)), Image.BOX)
    return ImageStat.Stat(ImageChops.difference(left, right).convert("L")).mean[0]


def seam_jump(out: Image.Image, known: Image.Image, horizontal: bool, skip: list[bool]) -> float:
    """Worst seam of the model answer: the jump across the photo edge relative to the jumps a few
    columns away. The model sometimes copies the photo but does not continue its details there."""
    if not horizontal:
        return seam_jump(out.transpose(Image.TRANSPOSE), known.transpose(Image.TRANSPOSE), True, skip)
    line, w, worst = _axis_filled(known, True), out.width, 0.0
    for b in range(41, w - 41):
        if line[b] == line[b - 1] or skip[b - 1 if line[b] else b]:
            continue
        ref = sorted(_jump(out, b + d) for d in (-40, -30, -20, 20, 30, 40))[3]
        worst = max(worst, _jump(out, b) / max(ref, 2.5))
    return worst


def match_colour(out: Image.Image, tile: Image.Image, band: Image.Image) -> Image.Image:
    """Per-channel gain/offset so the model's tone in the seam band equals the source."""
    src, gen = ImageStat.Stat(tile, mask=band), ImageStat.Stat(out, mask=band)
    luts = []
    for m_s, s_s, m_g, s_g in zip(src.mean, src.stddev, gen.mean, gen.stddev):
        k = max(0.5, min(2.0, s_s / s_g)) if s_g > 1 else 1.0
        luts += [max(0, min(255, round((v - m_g) * k + m_s))) for v in range(256)]
    return out.point(luts)


def sharpness(img: Image.Image, mask: Image.Image) -> float:
    edges = img.convert("L").filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(edges, mask=mask).mean[0]


def match_blur(out: Image.Image, target: float, area: Image.Image) -> Image.Image:
    """Soften generated pixels until they are no sharper than the source edge (bokeh stays bokeh)."""
    for radius in (0, 1, 2, 3, 5, 8):
        blurred = out.filter(ImageFilter.GaussianBlur(radius)) if radius else out
        if sharpness(blurred, area) <= target * 1.2:
            return blurred
    return blurred


STEP_STRIP = 3  # px on each side of the seam used to measure a brightness step
STEP_REACH = 0.15  # share of the window over which a step is faded out
STEP_MAX = 20  # larger jumps are real content, corrected only up to this


def remove_steps(img: Image.Image, known: Image.Image, horizontal: bool, skip: list[bool]) -> Image.Image:
    """The model sometimes draws a faint line where the gray met the photo. Measure the jump
    across each seam (per row, smoothed) and fade it out on the generated side."""
    if not horizontal:
        out = remove_steps(img.transpose(Image.TRANSPOSE), known.transpose(Image.TRANSPOSE), True, skip)
        return out.transpose(Image.TRANSPOSE)
    w, h = img.size
    line = _axis_filled(known, True)
    reach = max(8, round(w * STEP_REACH))
    smooth = max(1, h // 24)
    for b in range(1, w):
        if line[b] == line[b - 1]:
            continue
        gen_left = line[b]  # known starts at b, generated pixels are on the left
        g_col = b - 1 if gen_left else b
        if skip[g_col]:
            continue  # the model left this side gray; the next window fills it
        k = STEP_STRIP
        src_box = (b, 0, min(w, b + k), h) if gen_left else (max(0, b - k), 0, b, h)
        gen_box = (max(0, b - k), 0, b, h) if gen_left else (b, 0, min(w, b + k), h)

        def profile(box):
            col = img.crop(box).resize((1, h), Image.BOX)
            return col.resize((1, smooth), Image.BOX).resize((1, h), Image.BILINEAR)

        src, gen = profile(src_box), profile(gen_box)
        cap = lambda v: min(v, STEP_MAX)
        pos, neg = ImageChops.subtract(src, gen).point(cap), ImageChops.subtract(gen, src).point(cap)
        n = min(reach, b if gen_left else w - b)
        ramp = Image.new("L", (n, 1))
        ramp.putdata([round(255 * (i + 1) / n) for i in range(n)] if gen_left else [round(255 * (n - i) / n) for i in range(n)])
        ramp = Image.merge("RGB", [ramp.resize((n, h))] * 3)
        region = (b - n, 0, b, h) if gen_left else (b, 0, b + n, h)
        patch = img.crop(region)
        patch = ImageChops.add(patch, ImageChops.multiply(pos.resize((n, h)), ramp))
        patch = ImageChops.subtract(patch, ImageChops.multiply(neg.resize((n, h)), ramp))
        img.paste(patch, region[:2])
    return img


async def _fill(provider: ImageEditProvider, canvas: Image.Image, filled: Image.Image, box: tuple, ratio: str,
                horizontal: bool, budget: int) -> tuple[float, int]:
    """Ask the model to fill the gray part of canvas[box]; paste back only the unfilled pixels.
    Retries while the answer does not match the source along the seam. Returns (cost, calls)."""
    tile = canvas.crop(box)
    known = filled.crop(box)
    axis = tile.width if horizontal else tile.height
    band = _seam_band(known, max(8, round(axis * SEAM_BAND)))
    gray = known.point(lambda v: 255 - v)
    buf = io.BytesIO()
    tile.save(buf, "JPEG", quality=95)
    cost, calls, best = 0.0, 0, None
    while calls < min(1 + RETRIES, budget):
        res = await provider.edit(buf.getvalue(), PROMPT, ratio)
        cost, calls = cost + res.cost_usd, calls + 1
        out = load(res.data).convert("RGB").resize(tile.size, Image.LANCZOS)
        # Lines the model left gray, found before colour matching shifts the gray.
        still_gray = _gray_lines(Image.composite(tile, out, known), horizontal)
        diff = seam_diff(tile, out, band) if band.getbbox() else 0.0
        jump = seam_jump(out, known, horizontal, still_gray)
        log.info("extend window %s: seam diff %.1f, jump %.1f (try %d)", box, diff, jump, calls)
        score = max(diff / SEAM_MAX_DIFF, jump / SEAM_MAX_JUMP)
        if best is None or score < best[0]:
            best = (score, diff, out, still_gray)
        if score <= 1:
            break
    _, diff, out, still_gray = best
    if diff > SEAM_MAX_DIFF:
        raise ValueError(f"AI fill does not match the source (seam diff {diff:.0f} after {calls} calls)")
    # A seam jump alone does not fail the job: the best answer goes on, remove_steps softens it.
    if band.getbbox():
        out = match_colour(out, tile, band)
        out = match_blur(out, sharpness(tile, band), gray)
    # Mask = unfilled area plus a ramp into filled pixels; the gate above made the overlap trustworthy.
    feather = max(16, round(axis * FEATHER / 2))
    mask = gray.filter(ImageFilter.BoxBlur(feather)).point(lambda v: min(255, v * 2))
    done = Image.new("L", tile.size, 255)
    for i, g in enumerate(still_gray):
        if g:
            line = (i, 0, i + 1, tile.height) if horizontal else (0, i, tile.width, i + 1)
            done.paste(0, line)
            mask.paste(0, line)  # keep canvas gray there: the next window fills it
    canvas.paste(out, box[:2], mask)
    canvas.paste(remove_steps(canvas.crop(box), known, horizontal, still_gray), box[:2])
    filled.paste(ImageChops.lighter(known, done), box[:2])
    return cost, calls


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
        c, n = await _fill(provider, canvas, filled, box, ratio, horizontal, MAX_CALLS - calls)
        cost, calls = cost + c, calls + n
    if not all(_axis_filled(filled, horizontal)):
        raise ValueError(f"AI left gray areas after {calls} calls")
    return (canvas.crop(crop) if crop else canvas), cost, calls
