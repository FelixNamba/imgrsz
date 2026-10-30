"""Edit plan schema: the only contract between the LLM and the executor.

The LLM never calls tools directly. It returns JSON; we accept only allow-listed
ops with typed, clamped params (anti prompt injection by construction).
"""
import math
import re
from dataclasses import dataclass, field, replace

from . import prompts
from .config import config

RATIO_RE = re.compile(r"^\d{1,2}:\d{1,2}$")
AI_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
FORMATS = {"jpeg", "png", "webp"}
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class PlanError(ValueError):
    pass


def _int(v, lo, hi, name):
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        raise PlanError(f"{name}: not a number")
    if not lo <= v <= hi:
        raise PlanError(f"{name}: out of range {lo}..{hi}")
    return v


def _ratio(v):
    if not isinstance(v, str) or not RATIO_RE.match(v):
        raise PlanError("ratio must look like 16:9")
    a, b = map(int, v.split(":"))
    if not a or not b:
        raise PlanError("ratio must be positive")
    return v


def _extend_ratio(v):
    """Final aspect ratio for AI extension: any W:H (e.g. 468:60), between 1:10 and 10:1."""
    if not isinstance(v, str) or not re.match(r"^\d{1,5}:\d{1,5}$", v):
        raise PlanError("extend must look like 32:9")
    a, b = map(int, v.split(":"))
    if not a or not b or not 0.1 <= a / b <= 10:
        raise PlanError("extend ratio out of range 1:10..10:1")
    return v


def _color(v):
    v = v or "#ffffff"
    if not HEX_RE.match(v):
        raise PlanError("color must be #rrggbb")
    return v


def _phrase(v, maxlen: int) -> str | None:
    """One-line free text from the LLM (object/region for the AI task)."""
    if not v:
        return None
    s = re.sub(r"[\r\n]+", " ", str(v)).strip()
    return s[:maxlen] or None


def _ratio_value(r: str) -> float:
    a, b = map(int, r.split(":"))
    return a / b


def nearest_ai_ratio(width: int, height: int) -> str:
    """The AI step always runs at the source ratio, so the model never changes framing.

    The final ratio is produced by extend.py or Pillow ops, not by the image model.
    """
    target = width / height if height else 1.0
    return min(AI_RATIOS, key=lambda r: abs(_ratio_value(r) - target))


def ai_ratio_fits(width: int, height: int) -> bool:
    """True when the image model can output this ratio (within 2%), so a whole-image edit keeps framing."""
    r = width / height
    return abs(_ratio_value(nearest_ai_ratio(width, height)) - r) / r < 0.02


def _pad_op(extend: str, color: str) -> dict:
    """Pad to a W:H target. Small numbers are a ratio; large ones are pixels."""
    a, b = map(int, extend.split(":"))
    if a <= 99 and b <= 99:
        return {"op": "pad_ratio", "ratio": f"{a}:{b}", "color": color}
    return {"op": "resize", "mode": "pad", "width": a, "height": b, "color": color}


def _validate_op(op: dict) -> dict:
    name = op.get("op")
    if name == "crop_ratio":
        return {"op": name, "ratio": _ratio(op.get("ratio"))}
    if name == "resize":
        mode = op.get("mode", "fit")
        if mode not in {"fit", "fill", "exact", "pad"}:
            raise PlanError("resize.mode")
        w = op.get("width")
        h = op.get("height")
        if w is None and h is None:
            raise PlanError("resize needs width or height")
        out = {"op": name, "mode": mode}
        if w is not None:
            out["width"] = _int(w, 16, 8000, "width")
        if h is not None:
            out["height"] = _int(h, 16, 8000, "height")
        if mode in {"fill", "exact", "pad"} and not ("width" in out and "height" in out):
            raise PlanError(f"resize.{mode} needs width and height")
        if mode == "pad":
            out["color"] = _color(op.get("color"))
        return out
    if name == "pad_ratio":
        return {"op": name, "ratio": _ratio(op.get("ratio")), "color": _color(op.get("color"))}
    if name == "rotate":
        return {"op": name, "degrees": _int(op.get("degrees"), -360, 360, "degrees")}
    if name in {"grayscale", "flatten", "strip_metadata"}:
        return {"op": name, **({"color": _color(op.get("color"))} if name == "flatten" else {})}
    if name == "print_size":
        return {
            "op": name,
            "width_mm": _int(op.get("width_mm"), 10, 1000, "width_mm"),
            "height_mm": _int(op.get("height_mm"), 10, 1000, "height_mm"),
            "dpi": _int(op.get("dpi", 300), 72, 1200, "dpi"),
        }
    if name == "dpi":
        return {"op": name, "dpi": _int(op.get("dpi"), 72, 1200, "dpi")}
    if name == "format":
        fmt = str(op.get("format", "")).lower().replace("jpg", "jpeg")
        if fmt not in FORMATS:
            raise PlanError("format must be jpeg/png/webp")
        return {"op": name, "format": fmt}
    if name == "max_size_kb":
        return {"op": name, "kb": _int(op.get("kb"), 10, 50000, "kb")}
    raise PlanError(f"unknown op: {name!r}")


@dataclass
class Plan:
    brief: str
    ops: list[dict] = field(default_factory=list)
    ai_op: str | None = None  # one of prompts.AI_OPS
    ai_object: str | None = None
    ai_region: str | None = None
    ai_target: str | None = None
    ai_prompt: str | None = None  # rendered in code: invariant + task
    extend: str | None = None  # final W:H; executed by extend.py, keeps the whole source
    question: str | None = None
    refuse: str | None = None

    @property
    def is_ai(self) -> bool:
        return bool(self.ai_prompt or self.extend)

    @property
    def price(self) -> int:
        return config.price_ai if self.is_ai else config.price_technical

    @property
    def actionable(self) -> bool:
        return not self.refuse and not self.question and (self.is_ai or bool(self.ops))

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [])}


CROP_WORDS = ("обрез", "обреж", "кадрир", "crop", "вырез", "отрез", "среза", "убрать края", "по краям")
# "вертикальн"/"горизонтальн", not "вертикал"/"горизонт": «по горизонтали» names a rotation axis, not the result.
VERTICAL_WORDS = ("вертикальн", "портрет", "9:16", "9х16", "9x16", "story", "стори", "shorts", "reels")
HORIZONTAL_WORDS = ("горизонтальн", "ландшафт", "16:9", "16х9", "16x9", "широкоформат", "баннер")
QUALITY_WORDS = ("качеств", "резк", "чётк", "четк", "детал", "улучш", "размыт", "шум", "пиксел", "enhance", "upscale", "апскейл")
ROTATE_WORDS = ("поверн", "переверн", "разверн", "поворот", "rotate", "градус")
NO_STRETCH = 0.01  # resize exact is allowed only when the ratio already matches within 1%


def drop_unasked_enhance(plan: Plan, request: str) -> Plan:
    """The LLM adds `enhance` to "увеличь"/"дорисуй" requests. An extra AI pass costs money and
    re-renders the source, so it runs only when the user asked for quality."""
    if plan.ai_op != "enhance" or any(w in request.lower() for w in QUALITY_WORDS):
        return plan
    return replace(plan, ai_op=None, ai_region=None, ai_prompt=None)


def fix_stretch(plan: Plan, request: str, width: int, height: int) -> Plan:
    """The executor never stretches. A resize exact to another ratio becomes a crop (the user
    asked to crop), AI extend (AI plans without background removal) or padding (everything else)."""
    if plan.question or plan.refuse:
        return plan
    from .pipeline import output_size

    ops, extend, note = list(plan.ops), plan.extend, None
    crop = any(w in request.lower() for w in CROP_WORDS)
    for i, op in enumerate(ops):
        if op["op"] != "resize" or op["mode"] != "exact":
            continue
        w, h = output_size(width, height, ops[:i], extend)
        target = op["width"] / op["height"]
        if abs(w / h - target) / target < NO_STRETCH:
            continue
        geometry_before = any(o["op"] in ("crop_ratio", "pad_ratio", "resize", "rotate", "print_size") for o in ops[:i])
        if crop:
            ops[i] = {**op, "mode": "fill"}
            note = "Лишнее по краям обрежется, растягивать не будем."
        elif plan.is_ai and plan.ai_op != "remove_background" and not geometry_before:
            g = math.gcd(op["width"], op["height"])
            extend = f"{op['width'] // g}:{op['height'] // g}"
            note = "Недостающие края дорисует ИИ, растягивать не будем."
        else:
            ops[i] = {**op, "mode": "pad", "color": plan.ai_target or "#ffffff"}
            note = "Пропорция другая: добавим однотонные поля, растягивать не будем."
    if note is None:
        return plan
    return replace(plan, ops=ops, extend=extend, brief=f"{plan.brief}\n{note}")


def ratio_crop_warning(plan: Plan, request: str, width: int, height: int) -> str | None:
    """A ratio-changing crop loses pixels; ask unless the user explicitly asked to crop."""
    if plan.extend or plan.question or plan.refuse:
        return None
    source = width / height if height else 1.0
    target = None
    for op in plan.ops:
        if op["op"] == "crop_ratio":
            target = _ratio_value(op["ratio"])
        elif op["op"] == "resize" and op.get("mode") == "fill" and op.get("width") and op.get("height"):
            target = op["width"] / op["height"]
    if target is None or abs(target - source) / source < 0.02:
        return None
    if any(w in request.lower() for w in CROP_WORDS):
        return None
    return ("Пропорция меняется обрезкой — часть кадра потеряется. Обрезать края или дорисовать их с ИИ? "
            "Напишите «обрежь» или «дорисуй».")


def orientation_warning(plan: Plan, request: str, size: tuple[int, int]) -> str | None:
    """The plan's final W×H must match the orientation the user asked for."""
    if plan.question or plan.refuse:
        return None
    text = request.lower()
    if any(o["op"] == "rotate" for o in plan.ops) or any(w in text for w in ROTATE_WORDS):
        return None  # a rotation changes orientation on purpose
    vertical = any(w in text for w in VERTICAL_WORDS)
    horizontal = any(w in text for w in HORIZONTAL_WORDS)
    if vertical == horizontal:
        return None
    w, h = size
    if vertical and w > h:
        return (f"Вы просили вертикальное изображение, а план даёт горизонтальное {w}×{h}. "
                "Исправить на вертикальное? Напишите «да, вертикально» или укажите размеры.")
    if horizontal and h > w:
        return (f"Вы просили горизонтальное изображение, а план даёт вертикальное {w}×{h}. "
                "Исправить на горизонтальное? Напишите «да, горизонтально» или укажите размеры.")
    return None


def parse_plan(data: dict) -> Plan:
    if not isinstance(data, dict):
        raise PlanError("plan must be an object")
    brief = str(data.get("brief") or "").strip()[:1200]
    refuse = (str(data["refuse"]).strip()[:500] or None) if data.get("refuse") else None
    question = (str(data["question"]).strip()[:500] or None) if data.get("question") else None
    if refuse:
        return Plan(brief=brief or refuse, refuse=refuse)
    ops = [_validate_op(o) for o in (data.get("ops") or []) if isinstance(o, dict)][:12]
    ai_op = data.get("ai_op")
    ai_object = _phrase(data.get("ai_object"), 120)
    ai_region = _phrase(data.get("ai_region"), 120)
    ai_target = _color(data.get("ai_target")) if data.get("ai_target") else None
    if ai_op is not None:
        ai_op = str(ai_op).strip()
        if ai_op not in prompts.AI_OPS:
            raise PlanError(f"unknown ai_op: {ai_op!r}")
        if ai_op == "remove_object" and not ai_object:
            raise PlanError("remove_object needs ai_object")
        ai_target = ai_target if ai_op == "remove_background" else None
        ai_prompt = prompts.render(ai_op, object=ai_object, region=ai_region, target=ai_target)
    else:
        # Legacy drafts stored a free-form ai_prompt; keep them working, wrapped in the invariant.
        legacy = data.get("ai_prompt")
        ai_prompt = prompts.with_invariant(str(legacy).strip()[:1500]) if legacy else None
        ai_object = ai_region = ai_target = None
    extend = _extend_ratio(data["extend"]) if data.get("extend") else None
    if ai_op == "remove_background" and extend:
        # A white background plus a wider canvas is padding, not outpainting. extend would
        # continue whatever is at the source edge (objects, lot) into the new area.
        pad = _pad_op(extend, ai_target or "#ffffff")
        idx = next((i for i, o in enumerate(ops) if o["op"] == "resize"), len(ops))
        ops.insert(idx, pad)
        extend = None
    if not brief and not question:
        raise PlanError("empty brief")
    return Plan(brief=brief, ops=ops, ai_op=ai_op, ai_object=ai_object, ai_region=ai_region,
                ai_target=ai_target, ai_prompt=ai_prompt, extend=extend, question=question)
