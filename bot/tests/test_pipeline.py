import io

import pytest
from PIL import Image

from app import pipeline


def make(w=1200, h=800, mode="RGB", fmt="JPEG", exif=True):
    img = Image.new(mode, (w, h), (200, 100, 50) + ((128,) if mode == "RGBA" else ()))
    buf = io.BytesIO()
    kw = {}
    if exif and fmt == "JPEG":
        ex = Image.Exif()
        ex[0x010F] = "Camera"  # Make
        ex[0x0131] = "AI Generator"  # Software
        kw["exif"] = ex.tobytes()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def reopen(res):
    return Image.open(io.BytesIO(res.data))


def test_describe_reports_metadata():
    info = pipeline.describe(make())
    assert info["width"] == 1200 and info["format"] == "jpeg" and info["has_metadata"]


def test_output_has_no_metadata():
    res = pipeline.run(make(), [{"op": "strip_metadata"}], "jpeg")
    img = reopen(res)
    assert not img.getexif() and "exif" not in img.info and "xmp" not in img.info


def test_crop_and_exact_resize():
    res = pipeline.run(make(), [{"op": "crop_ratio", "ratio": "1:1"}, {"op": "resize", "mode": "exact", "width": 1080, "height": 1080}])
    assert (res.width, res.height) == (1080, 1080)


def test_fit_keeps_ratio():
    res = pipeline.run(make(1200, 800), [{"op": "resize", "mode": "fit", "width": 600}])
    assert (res.width, res.height) == (600, 400)


def test_pad_ratio():
    res = pipeline.run(make(1000, 1000), [{"op": "pad_ratio", "ratio": "16:9", "color": "#ffffff"}])
    assert abs(res.width / res.height - 16 / 9) < 0.01 and res.height == 1000


def test_print_size_and_dpi():
    res = pipeline.run(make(), [{"op": "print_size", "width_mm": 35, "height_mm": 45, "dpi": 300}])
    assert (res.width, res.height) == (413, 531)
    assert round(reopen(res).info["dpi"][0]) == 300


def test_max_size_kb():
    noisy = Image.effect_noise((3000, 2000), 80).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, "PNG")
    res = pipeline.run(buf.getvalue(), [{"op": "format", "format": "jpeg"}, {"op": "max_size_kb", "kb": 300}])
    assert len(res.data) <= 300 * 1024 and res.fmt == "jpeg"


def test_png_alpha_to_jpeg_flattens():
    res = pipeline.run(make(mode="RGBA", fmt="PNG", exif=False), [{"op": "format", "format": "jpeg"}])
    assert reopen(res).mode == "RGB"


def test_unknown_source_format_defaults_to_jpeg():
    res = pipeline.run(make(), [], "heif")
    assert res.fmt == "jpeg"
