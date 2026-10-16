"""Deterministic image operations (Pillow). Output never carries metadata."""
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC support optional in dev
    pass

Image.MAX_IMAGE_PIXELS = 80_000_000
EXT = {"jpeg": "jpg", "png": "png", "webp": "webp"}


@dataclass
class Result:
    data: bytes
    fmt: str
    width: int
    height: int
    dpi: int | None

    @property
    def ext(self) -> str:
        return EXT[self.fmt]

    @property
    def kb(self) -> int:
        return max(1, round(len(self.data) / 1024))


def load(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return ImageOps.exif_transpose(img)


def describe(data: bytes) -> dict:
    """Facts about the source image for the LLM brief."""
    img = Image.open(io.BytesIO(data))
    info = {
        "width": img.width,
        "height": img.height,
        "format": (img.format or "unknown").lower(),
        "mode": img.mode,
        "size_kb": round(len(data) / 1024),
        "has_alpha": img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info,
        "has_metadata": bool(img.info.get("exif") or img.info.get("xmp") or img.getexif()),
    }
    if img.info.get("dpi"):
        info["dpi"] = round(img.info["dpi"][0])
    return info


def _ratio(r: str) -> float:
    a, b = map(int, r.split(":"))
    return a / b


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def flatten(img: Image.Image, color: str = "#ffffff") -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, _rgb(color))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB") if img.mode not in ("RGB", "L") else img


def crop_ratio(img: Image.Image, ratio: str) -> Image.Image:
    target = _ratio(ratio)
    w, h = img.size
    if w / h > target:
        nw = round(h * target)
        left = (w - nw) // 2
        return img.crop((left, 0, left + nw, h))
    nh = round(w / target)
    top = (h - nh) // 2
    return img.crop((0, top, w, top + nh))


def pad_to(img: Image.Image, w: int, h: int, color: str) -> Image.Image:
    fitted = ImageOps.contain(img, (w, h), Image.LANCZOS)
    mode = "RGBA" if fitted.mode == "RGBA" else "RGB"
    canvas = Image.new(mode, (w, h), _rgb(color) + ((255,) if mode == "RGBA" else ()))
    canvas.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    return canvas


def pad_ratio(img: Image.Image, ratio: str, color: str) -> Image.Image:
    target = _ratio(ratio)
    w, h = img.size
    if w / h > target:
        return pad_to(img, w, round(w / target), color)
    return pad_to(img, round(h * target), h, color)


def resize(img: Image.Image, mode: str, width: int | None = None, height: int | None = None, color: str = "#ffffff"):
    if mode == "exact":
        return img.resize((width, height), Image.LANCZOS)
    if mode == "fill":
        return ImageOps.fit(img, (width, height), Image.LANCZOS)
    if mode == "pad":
        return pad_to(img, width, height, color)
    # fit: keep ratio within the given box
    w, h = img.size
    scale = min((width or 10**9) / w, (height or 10**9) / h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def output_size(width: int, height: int, ops: list[dict], extend: str | None = None) -> tuple[int, int]:
    """Final pixel size of a plan without touching pixels (shown in the brief before the user pays)."""
    w, h = width, height
    if extend:
        r = _ratio(extend)
        w, h = (max(w, round(h * r)), h) if r >= w / h else (w, max(h, round(w / r)))
    for op in ops:
        name = op["op"]
        if name == "crop_ratio":
            r = _ratio(op["ratio"])
            w, h = (round(h * r), h) if w / h > r else (w, round(w / r))
        elif name == "pad_ratio":
            r = _ratio(op["ratio"])
            w, h = (w, round(w / r)) if w / h > r else (round(h * r), h)
        elif name == "resize":
            if op["mode"] in ("exact", "fill", "pad"):
                w, h = op["width"], op["height"]
            else:
                scale = min((op.get("width") or 10**9) / w, (op.get("height") or 10**9) / h)
                w, h = max(1, round(w * scale)), max(1, round(h * scale))
        elif name == "rotate" and op["degrees"] % 180:
            w, h = h, w
        elif name == "print_size":
            w, h = round(op["width_mm"] / 25.4 * op["dpi"]), round(op["height_mm"] / 25.4 * op["dpi"])
    return w, h


def apply_ops(img: Image.Image, ops: list[dict]) -> tuple[Image.Image, dict]:
    """Returns image and save options (format, dpi, max_kb)."""
    save = {"format": None, "dpi": None, "max_kb": None}
    for op in ops:
        name = op["op"]
        if name == "crop_ratio":
            img = crop_ratio(img, op["ratio"])
        elif name == "resize":
            img = resize(img, op["mode"], op.get("width"), op.get("height"), op.get("color", "#ffffff"))
        elif name == "pad_ratio":
            img = pad_ratio(img, op["ratio"], op["color"])
        elif name == "rotate":
            img = img.rotate(-op["degrees"], expand=True, fillcolor="white" if img.mode == "RGB" else None)
        elif name == "grayscale":
            img = ImageOps.grayscale(img)
        elif name == "flatten":
            img = flatten(img, op["color"])
        elif name == "print_size":
            px = (round(op["width_mm"] / 25.4 * op["dpi"]), round(op["height_mm"] / 25.4 * op["dpi"]))
            img = ImageOps.fit(img, px, Image.LANCZOS)
            save["dpi"] = op["dpi"]
        elif name == "dpi":
            save["dpi"] = op["dpi"]
        elif name == "format":
            save["format"] = op["format"]
        elif name == "max_size_kb":
            save["max_kb"] = op["kb"]
        # strip_metadata: always done on encode
    return img, save


def _encode(img: Image.Image, fmt: str, quality: int, dpi: int | None) -> bytes:
    buf = io.BytesIO()
    # Never pass exif/xmp/icc/pnginfo: output is metadata-free by construction.
    kw = {"dpi": (dpi, dpi)} if dpi and fmt in ("jpeg", "png") else {}
    if fmt == "jpeg":
        img = flatten(img) if img.mode not in ("RGB", "L") else img
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True, **kw)
    elif fmt == "webp":
        img.save(buf, "WEBP", quality=quality, method=6)
    else:
        if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            img = img.convert("RGBA")
        img.save(buf, "PNG", optimize=True, **kw)
    return buf.getvalue()


def encode(img: Image.Image, fmt: str, dpi: int | None = None, max_kb: int | None = None) -> Result:
    if not max_kb:
        data = _encode(img, fmt, 92, dpi)
        return Result(data, fmt, img.width, img.height, dpi)
    limit = max_kb * 1024
    cur = img
    for _ in range(12):
        if fmt == "png":
            data = _encode(cur, fmt, 0, dpi)
            if len(data) <= limit:
                return Result(data, fmt, cur.width, cur.height, dpi)
        else:
            lo, hi, best = 40, 95, None
            while lo <= hi:  # binary search on quality
                q = (lo + hi) // 2
                data = _encode(cur, fmt, q, dpi)
                if len(data) <= limit:
                    best, lo = data, q + 1
                else:
                    hi = q - 1
            if best:
                return Result(best, fmt, cur.width, cur.height, dpi)
        cur = cur.resize((max(16, round(cur.width * 0.85)), max(16, round(cur.height * 0.85))), Image.LANCZOS)
    raise ValueError(f"cannot fit into {max_kb} KB")


def run(data: bytes, ops: list[dict], source_format: str | None = None) -> Result:
    img = load(data)
    img, save = apply_ops(img, ops)
    fmt = save["format"] or (source_format if source_format in EXT else "jpeg")
    return encode(img, fmt, save["dpi"], save["max_kb"])
