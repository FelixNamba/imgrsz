import pytest

from app.config import config
from app.plan import PlanError, nearest_ai_ratio, orientation_warning, parse_plan, ratio_crop_warning


def test_technical_price():
    p = parse_plan({"brief": "x", "ops": [{"op": "resize", "mode": "fit", "width": 100}]})
    assert p.price == config.price_technical and not p.is_ai and p.actionable


def test_ai_price():
    p = parse_plan({"brief": "x", "ai_op": "enhance"})
    assert p.price == config.price_ai and p.ai_op == "enhance"
    assert "ground truth" in p.ai_prompt


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


def test_unknown_ai_op_rejected():
    with pytest.raises(PlanError):
        parse_plan({"brief": "x", "ai_op": "redraw_everything"})


def test_remove_object_needs_object():
    with pytest.raises(PlanError):
        parse_plan({"brief": "x", "ai_op": "remove_object"})
    p = parse_plan({"brief": "x", "ai_op": "remove_object", "ai_object": "a red truck"})
    assert "a red truck" in p.ai_prompt


def test_legacy_ai_prompt_still_works():
    p = parse_plan({"brief": "x", "ai_prompt": "Remove the background.", "ai_ratio": "16:9"})
    assert p.is_ai and "Remove the background." in p.ai_prompt


def test_nearest_ai_ratio_is_the_source_ratio():
    assert nearest_ai_ratio(800, 600) == "4:3"
    assert nearest_ai_ratio(1920, 1080) == "16:9"
    assert nearest_ai_ratio(1080, 1920) == "9:16"


def test_ratio_crop_without_intent_asks():
    p = parse_plan({"brief": "x", "ops": [{"op": "crop_ratio", "ratio": "16:9"}]})
    assert ratio_crop_warning(p, "сделай 16х9", 800, 600)
    fill = parse_plan({"brief": "x", "ops": [{"op": "resize", "mode": "fill", "width": 1600, "height": 900}]})
    assert ratio_crop_warning(fill, "сделай 1600x900", 800, 600)


def test_explicit_crop_does_not_ask():
    p = parse_plan({"brief": "x", "ops": [{"op": "crop_ratio", "ratio": "16:9"}]})
    assert ratio_crop_warning(p, "обрежь до 16:9", 800, 600) is None


def test_extend_does_not_ask():
    p = parse_plan({"brief": "x", "extend": "16:9"})
    assert ratio_crop_warning(p, "сделай 16х9", 800, 600) is None


def test_background_plus_extend_pads_not_outpaints():
    p = parse_plan({
        "brief": "x", "ai_op": "remove_background", "extend": "3840:1080",
        "ops": [{"op": "resize", "mode": "exact", "width": 3840, "height": 1080}],
    })
    assert p.extend is None
    assert p.ops[0] == {"op": "resize", "mode": "pad", "width": 3840, "height": 1080, "color": "#ffffff"}


def test_background_plus_ratio_pads():
    p = parse_plan({
        "brief": "x", "ai_op": "remove_background", "extend": "16:9",
        "ops": [{"op": "resize", "mode": "exact", "width": 1600, "height": 900}],
    })
    assert p.extend is None
    assert p.ops[0] == {"op": "pad_ratio", "ratio": "16:9", "color": "#ffffff"}


def test_vertical_request_horizontal_plan_asks():
    p = parse_plan({"brief": "x", "ai_op": "enhance",
                    "ops": [{"op": "resize", "mode": "exact", "width": 2560, "height": 1440}]})
    assert orientation_warning(p, "вертикальный монитор 9х16", (2560, 1440))


def test_vertical_plan_ok():
    p = parse_plan({"brief": "x", "ai_op": "enhance",
                    "ops": [{"op": "resize", "mode": "exact", "width": 2160, "height": 3840}]})
    assert orientation_warning(p, "вертикальный монитор 9х16", (2160, 3840)) is None


def test_horizontal_request_vertical_plan_asks():
    p = parse_plan({"brief": "x", "ai_op": "enhance",
                    "ops": [{"op": "resize", "mode": "exact", "width": 1440, "height": 2560}]})
    assert orientation_warning(p, "нужен баннер 16:9", (1440, 2560))


def test_refuse_not_actionable():
    p = parse_plan({"brief": "", "refuse": "нельзя", "ops": [{"op": "grayscale"}]})
    assert p.refuse and not p.actionable and p.ops == []


def test_jpg_alias():
    p = parse_plan({"brief": "x", "ops": [{"op": "format", "format": "JPG"}]})
    assert p.ops[0]["format"] == "jpeg"
