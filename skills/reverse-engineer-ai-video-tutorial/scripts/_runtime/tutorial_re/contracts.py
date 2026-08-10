from __future__ import annotations


PUBLIC_ACTIONS = ("guide", "recreate", "create")
STOP_POINTS = ("evidence", "guide")
TARGET_CHOICES = ("match", "adapt", "method")

TARGET_CHOICE_TO_FIDELITY = {
    "match": "reference_reconstruction",
    "adapt": "style_match",
    "method": "method_only",
}
FIDELITY_POLICIES = tuple(TARGET_CHOICE_TO_FIDELITY.values())

VALIDATION_STAGES = (
    "scaffold",
    "section-mapped",
    "evidence-complete",
    "guide-complete",
    "scene-ready",
    "assets-approved",
    "comparison-complete",
    "delivery-complete",
)
INTERNAL_STAGES = (
    "initialized",
    "evidence-scaffold",
    "section-mapped",
    "evidence-complete",
    "guide-draft",
    "guide-complete",
    "guide-approved",
    "guide-rejected",
    "scene-preparation",
    "scene-ready",
    "assets-approved",
    "comparison-complete",
    "delivery-complete",
)
TERMINAL_STAGES = frozenset(VALIDATION_STAGES[1:])


def require_action(action: str) -> str:
    if action not in PUBLIC_ACTIONS:
        raise ValueError(f"unsupported action: {action}")
    return action


def fidelity_for_target_choice(target_choice: str) -> str:
    try:
        return TARGET_CHOICE_TO_FIDELITY[target_choice]
    except KeyError as exc:
        raise ValueError(f"unsupported target choice: {target_choice}") from exc
