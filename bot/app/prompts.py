"""Image-edit prompt assembly.

The LLM chooses a structured `ai_op`; this module renders the English prompt.
A fixed invariant says the source image is the ground truth, so the wording is
the same for every job and cannot drift per image.
"""

INVARIANT = """You are editing an existing photo, not generating a new one.
The input image is the ground truth.
- Keep the subject pixel-identical: shape, proportions, details, text, reflections and lighting.
- Change only the region named in the task. Everything else stays untouched.
- Never relight, restyle, beautify, upscale or re-render the subject.
- Do not change the framing or aspect ratio."""

# ai_op -> task. The LLM supplies only the parameters; it never writes this text.
AI_OPS = {
    "remove_background": (
        "Replace only the background with flat {target}. Do not create a scene, floor or new lighting "
        "on the subject. Keep the subject exactly as in the input."
    ),
    "remove_object": (
        "Remove {object} from {region}. Reconstruct only that area; keep everything else exactly as in the input."
    ),
    "enhance": "Recover detail and sharpness in {region}. Do not change identity, geometry, colours or framing.",
    "restore": "Restore {region}: remove noise, blur and compression artifacts. Do not change identity, geometry or framing.",
    "color_correct": "Correct exposure, white balance and contrast in {region}. Do not change geometry, objects or framing.",
}


def render(ai_op: str, *, object: str | None = None, region: str | None = None, target: str | None = None) -> str:
    task = AI_OPS[ai_op].format(
        object=object or "the requested object",
        region=region or "the whole image",
        target=target or "#FFFFFF",
    )
    return f"{INVARIANT}\n\nTASK: {task}"


def with_invariant(task: str) -> str:
    """Wrap a hand-written task (legacy plans, scripts) in the same invariant."""
    return f"{INVARIANT}\n\nTASK: {task.strip()}"


# Outpainting: extend.py builds the canvas, so this prompt talks only about gray.
EXTEND = (
    "You are extending an existing photo, not generating a new one. The source photo is the ground truth.\n"
    "This photo is surrounded by flat gray empty areas. Fill every gray area completely by seamlessly continuing "
    "the scene (background, surfaces, objects cut by the edge, lighting, perspective), so it becomes one natural photo.\n"
    "Complete objects cut by the photo edge, but never add a second copy of the main subject or any new person, "
    "vehicle or animal.\n"
    "Match the photo at its edge: the same focus blur and depth of field (a blurred background stays "
    "equally blurred), the same colour, light, grain, scale and camera distance. Do not zoom, crop or move the photo.\n"
    "Do not change anything that is not gray. No text, no borders, no gray left."
)
