import asyncio
import io

import pytest
from PIL import Image, ImageChops, ImageFilter, ImageStat

from app import extend
from app.providers import EditResult, ImageEditProvider


def _img(w, h, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class Painter(ImageEditProvider):
    """Paints gray areas blue; with `lazy` the first call leaves the gray as is (the real model sometimes does)."""

    def __init__(self, lazy=False):
        self.calls, self.lazy = 0, lazy

    async def edit(self, image, prompt, ratio):
        self.calls += 1
        img = Image.open(io.BytesIO(image)).convert("RGB")
        gray = ImageChops.difference(img, Image.new("RGB", img.size, extend.GRAY)).convert("L").point(lambda v: 255 if v < 12 else 0).filter(ImageFilter.MaxFilter(5))  # + JPEG halo
        if self.lazy and self.calls == 1:
            gray.paste(0, (0, 0, img.width, img.height))
        # continue the photo: its mean colour (a flat colour against a textured photo is not a seam jump)
        img.paste(tuple(round(v) for v in ImageStat.Stat(img, mask=gray.point(lambda v: 255 - v)).mean), mask=gray)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return EditResult(buf.getvalue(), 0.03)


def _no_gray(img):
    return not any(extend._gray_lines(img, True))


def test_wide_banner_keeps_source_and_ratio():
    p = Painter()
    img, cost, calls = asyncio.run(extend.extend(p, _img(1360, 1236), "5120:1440"))
    assert abs(img.width / img.height - 5120 / 1440) < 0.01 and _no_gray(img)
    assert 2 <= calls <= 3 and cost == 0.03 * calls
    assert img.getpixel((img.width // 2, img.height // 2))[0] > 150  # source untouched in the middle


def test_model_skipping_gray_gets_another_window():
    img, _, calls = asyncio.run(extend.extend(Painter(lazy=True), _img(1360, 1236), "5120:1440"))
    assert _no_gray(img) and calls >= 3


def test_in_range_single_call():
    img, _, calls = asyncio.run(extend.extend(Painter(), _img(1000, 1000), "16:9"))
    assert calls == 1 and abs(img.width / img.height - 16 / 9) < 0.01 and _no_gray(img)


def test_extreme_banner_fits_call_budget():
    img, _, calls = asyncio.run(extend.extend(Painter(), _img(1200, 1200), "468:60"))
    assert calls <= extend.MAX_CALLS and abs(img.width / img.height - 7.8) < 0.01 and _no_gray(img)


def test_tall_story():
    img, _, calls = asyncio.run(extend.extend(Painter(), _img(1600, 900), "9:32"))
    assert abs(img.width / img.height - 9 / 32) < 0.01 and calls >= 2


def _noise(w, h, seed=1):
    import random

    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    img.putdata([(rnd.randrange(256),) * 3 for _ in range(w * h)])
    return img.filter(ImageFilter.GaussianBlur(6)).point(lambda v: min(255, v * 3 - 200) if v > 70 else 10)


class Reframer(Painter):
    """First `bad` answers shift the whole tile (the model re-imagined the window), then paints properly."""

    def __init__(self, bad):
        super().__init__()
        self.bad = bad

    async def edit(self, image, prompt, ratio):
        res = await super().edit(image, prompt, ratio)
        if self.calls > self.bad:
            return res
        img = Image.open(io.BytesIO(res.data)).convert("RGB")
        img = img.transpose(Image.FLIP_TOP_BOTTOM)  # content no longer where the source is
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return EditResult(buf.getvalue(), res.cost_usd)


def _textured(w, h):
    buf = io.BytesIO()
    _noise(w, h).save(buf, "PNG")
    return buf.getvalue()


def test_reframed_answer_is_retried():
    p = Reframer(bad=1)
    img, _, calls = asyncio.run(extend.extend(p, _textured(400, 300), "16:9"))
    assert calls == 2 and _no_gray(img)


def test_always_reframed_fails():
    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(extend.extend(Reframer(bad=99), _textured(400, 300), "16:9"))


def test_colour_matched_to_source():
    tile = Image.new("RGB", (100, 50), (120, 80, 40))
    out = Image.new("RGB", (100, 50), (160, 120, 90))  # model shifted the tone
    band = Image.new("L", (100, 50), 255)
    assert extend.match_colour(out, tile, band).getpixel((5, 5)) == (120, 80, 40)


def test_sharp_fill_blurred_to_soft_source():
    sharp = _noise(200, 100)
    soft = sharp.filter(ImageFilter.GaussianBlur(4))
    area = Image.new("L", (200, 100), 255)
    target = extend.sharpness(soft, area)
    assert extend.sharpness(extend.match_blur(sharp, target, area), area) <= target * 1.2


def test_seam_step_faded_out():
    # The model drew the new area 10 levels brighter right at the photo edge (job 22, first run).
    img = Image.new("RGB", (400, 100), (130, 130, 130))
    img.paste((120, 120, 120), (100, 0, 300, 100))
    known = Image.new("L", (400, 100), 0)
    known.paste(255, (100, 0, 300, 100))
    out = extend.remove_steps(img, known, True, [False] * 400)
    assert abs(out.getpixel((98, 50))[0] - 120) <= 2 and abs(out.getpixel((302, 50))[0] - 120) <= 2
    assert out.getpixel((150, 50))[0] == 120 and out.getpixel((5, 50))[0] == 130  # source and far area kept


class Liner(Painter):
    """Copies the photo but draws the new area in another colour: a visible line at the photo edge."""

    def __init__(self, bad):
        super().__init__()
        self.bad = bad

    async def edit(self, image, prompt, ratio):
        self.calls += 1
        img = Image.open(io.BytesIO(image)).convert("RGB")
        gray = ImageChops.difference(img, Image.new("RGB", img.size, extend.GRAY)).convert("L").point(lambda v: 255 if v < 12 else 0).filter(ImageFilter.MaxFilter(5))  # + JPEG halo
        img.paste((230, 40, 40) if self.calls <= self.bad else (60, 60, 60), mask=gray)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return EditResult(buf.getvalue(), 0.03)


def test_visible_seam_line_is_retried():
    img, _, calls = asyncio.run(extend.extend(Liner(bad=1), _img(400, 300, (60, 60, 60)), "16:9"))
    assert calls == 2 and _no_gray(img)


def test_seam_line_after_retries_still_delivers():
    img, _, calls = asyncio.run(extend.extend(Liner(bad=99), _img(400, 300, (60, 60, 60)), "16:9"))
    assert calls == 1 + extend.RETRIES and _no_gray(img)
