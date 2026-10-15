import asyncio
import io

from PIL import Image, ImageChops

from app import extend
from app.providers import EditResult, ImageEditProvider


def _img(w, h, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


class Painter(ImageEditProvider):
    """Paints gray areas blue; with `lazy` the first call leaves the gray as is (the real model sometimes does)."""

    def __init__(self, lazy=False):
        self.calls, self.lazy = 0, lazy

    async def edit(self, image, prompt, ratio):
        self.calls += 1
        img = Image.open(io.BytesIO(image)).convert("RGB")
        gray = ImageChops.difference(img, Image.new("RGB", img.size, extend.GRAY)).convert("L").point(lambda v: 255 if v < 12 else 0)
        if self.lazy and self.calls == 1:
            gray.paste(0, (0, 0, img.width, img.height))
        img.paste((40, 60, 220), mask=gray)
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
