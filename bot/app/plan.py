"""Edit plan schema: the only contract between the LLM and the executor.

The LLM never calls tools directly. It returns JSON; we accept only allow-listed
ops with typed, clamped params (anti prompt injection by construction).
"""
import re
from dataclasses import dataclass, field

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


def _color(v):
    v = v or "#ffffff"
    if not HEX_RE.match(v):
        raise PlanError("color must be #rrggbb")
    return v


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
    ai_prompt: str | None = None
    ai_ratio: str | None = None
    question: str | None = None
    refuse: str | None = None

    @property
    def is_ai(self) -> bool:
        return bool(self.ai_prompt)

    @property
    def price(self) -> int:
        return config.price_ai if self.is_ai else config.price_technical

    @property
    def actionable(self) -> bool:
        return not self.refuse and not self.question and (self.is_ai or bool(self.ops))

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [])}


def parse_plan(data: dict) -> Plan:
    if not isinstance(data, dict):
        raise PlanError("plan must be an object")
    brief = str(data.get("brief") or "").strip()[:1200]
    refuse = (str(data["refuse"]).strip()[:500] or None) if data.get("refuse") else None
    question = (str(data["question"]).strip()[:500] or None) if data.get("question") else None
    if refuse:
        return Plan(brief=brief or refuse, refuse=refuse)
    ops = [_validate_op(o) for o in (data.get("ops") or []) if isinstance(o, dict)][:12]
    ai_prompt = data.get("ai_prompt")
    ai_prompt = str(ai_prompt).strip()[:1500] if ai_prompt else None
    ai_ratio = data.get("ai_ratio") or None
    if ai_ratio is not None and ai_ratio not in AI_RATIOS:
        ai_ratio = None
    if not brief and not question:
        raise PlanError("empty brief")
    return Plan(brief=brief, ops=ops, ai_prompt=ai_prompt, ai_ratio=ai_ratio, question=question)
