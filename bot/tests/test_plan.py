import pytest

from app.config import config
from app.plan import PlanError, parse_plan


def test_technical_price():
    p = parse_plan({"brief": "x", "ops": [{"op": "resize", "mode": "fit", "width": 100}]})
    assert p.price == 5 and not p.is_ai and p.actionable


def test_ai_price():
    p = parse_plan({"brief": "x", "ai_prompt": "extend", "ai_ratio": "16:9"})
    assert p.price == config.price_ai and p.ai_ratio == "16:9"


def test_extend_any_ratio():
    p = parse_plan({"brief": "x", "extend": "468:60", "ops": [{"op": "resize", "mode": "exact", "width": 468, "height": 60}]})
    assert p.extend == "468:60" and p.is_ai and p.price == config.price_ai
    with pytest.raises(PlanError):
        parse_plan({"brief": "x", "extend": "100:1"})


def test_unknown_op_rejected():
    with pytest.raises(PlanError):
        parse_plan({"brief": "x", "ops": [{"op": "shell", "cmd": "rm -rf /"}]})


def test_params_clamped():
    with pytest.raises(PlanError):
        parse_plan({"brief": "x", "ops": [{"op": "resize", "mode": "exact", "width": 99999, "height": 10}]})


def test_bad_ai_ratio_dropped():
    assert parse_plan({"brief": "x", "ai_prompt": "y", "ai_ratio": "7:3"}).ai_ratio is None


def test_refuse_not_actionable():
    p = parse_plan({"brief": "", "refuse": "нельзя", "ops": [{"op": "grayscale"}]})
    assert p.refuse and not p.actionable and p.ops == []


def test_jpg_alias():
    p = parse_plan({"brief": "x", "ops": [{"op": "format", "format": "JPG"}]})
    assert p.ops[0]["format"] == "jpeg"
