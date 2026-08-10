from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_project(
    project: Path, manifest_path: Path | None = None, *, require_verified: bool = True
) -> list[str]:
    project = project.resolve()
    manifest_path = (manifest_path or project / "studio-timeline.json").resolve()
    errors: list[str] = []
    package_path = project / "package.json"
    package: dict[str, object] = {}
    if not package_path.is_file():
        errors.append("package.json missing")
    else:
        package = _read_json(package_path)
        if not (package.get("scripts") or {}).get("studio"):
            errors.append("package.json scripts.studio missing")
    node_modules = project / "node_modules"
    if not node_modules.is_dir():
        errors.append("shared node_modules link missing")
    launchers = [project / "start-studio.ps1", project / "start-studio.sh"]
    for launcher_path in (path for path in launchers if path.is_file()):
        launcher_text = launcher_path.read_text(encoding="utf-8-sig")
        if "npm run studio" not in launcher_text:
            errors.append(f"{launcher_path.name} must run npm run studio")
    if not manifest_path.is_file():
        return [f"studio timeline manifest missing: {manifest_path}"]
    try:
        payload = _read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"studio timeline manifest unreadable: {exc}"]

    if payload.get("schema_version") != 1:
        errors.append("studio timeline schema_version must be 1")
    composition_id = payload.get("composition_id")
    composition_component = payload.get("composition_component")
    root_file = payload.get("root_file")
    component_source_file = payload.get("component_source_file")
    for field, value in (
        ("composition_id", composition_id),
        ("composition_component", composition_component),
        ("root_file", root_file),
        ("component_source_file", component_source_file),
    ):
        if not value:
            errors.append(f"{field} missing")

    source_paths: list[Path] = []
    for relative in payload.get("source_files") or []:
        path = (project / relative).resolve()
        if project not in path.parents:
            errors.append(f"timeline source escapes project: {relative}")
            continue
        if not path.is_file():
            errors.append(f"timeline source file missing: {relative}")
        else:
            source_paths.append(path)
    if not source_paths:
        errors.append("source_files must name the Remotion Root/schema and scene source")
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    root_path = (project / str(root_file or "")).resolve()
    component_path = (project / str(component_source_file or "")).resolve()
    if root_path not in source_paths:
        errors.append("root_file must be listed in source_files")
    if component_path not in source_paths:
        errors.append("component_source_file must be listed in source_files")
    root_text = root_path.read_text(encoding="utf-8") if root_path.is_file() else ""
    component_text = component_path.read_text(encoding="utf-8") if component_path.is_file() else ""
    composition_blocks = re.findall(r"<Composition\b[\s\S]*?/>", root_text, re.IGNORECASE)
    linked = any(
        re.search(rf"\bid\s*=\s*['\"]{re.escape(str(composition_id))}['\"]", block)
        and re.search(rf"\bcomponent\s*=\s*{{\s*{re.escape(str(composition_component))}\s*}}", block)
        for block in composition_blocks
    )
    if composition_id and composition_component and not linked:
        errors.append(
            f"Root does not link composition {composition_id} to component {composition_component}"
        )
    if not re.search(r"\bschema\s*=\s*{", root_text):
        errors.append("Composition must expose Zod schema to Remotion Studio")
    if not re.search(r"\bdefaultProps\s*=\s*{", root_text):
        errors.append("Composition must expose defaultProps to Remotion Studio")
    if composition_component and not re.search(
        rf"\b(?:const|function)\s+{re.escape(str(composition_component))}\b", component_text
    ):
        errors.append(f"composition component not exported by component source: {composition_component}")

    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        errors.append("elements must be non-empty")
        elements = []
    element_ids: set[str] = set()
    for index, element in enumerate(elements):
        element_id = element.get("id")
        if not element_id or not element.get("role") or not element.get("tweakable_props"):
            errors.append(f"elements[{index}] needs id, role, and tweakable_props")
            continue
        if element_id in element_ids:
            errors.append(f"duplicate element id: {element_id}")
        element_ids.add(element_id)
        for prop in element["tweakable_props"]:
            occurrences = len(re.findall(rf"\b{re.escape(str(prop))}\b", source_text))
            if occurrences < 3:
                errors.append(
                    f"Inspector prop is declared but not demonstrably consumed: {element_id}.{prop}"
                )

    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or len(tracks) < 2:
        errors.append("tracks must contain at least two named Studio rows")
        tracks = []
    track_names: set[str] = set()
    covered: set[str] = set()
    for index, track in enumerate(tracks):
        name = track.get("name")
        required = (name, track.get("role"), track.get("element_ids"), track.get("source_component"))
        if not all(required) or track.get("from") is None or not track.get("duration_in_frames"):
            errors.append(f"tracks[{index}] needs name, role, element_ids, frame range, source_component")
            continue
        if name in track_names:
            errors.append(f"duplicate track name: {name}")
        track_names.add(name)
        covered.update(track["element_ids"])
        unknown = set(track["element_ids"]) - element_ids
        if unknown:
            errors.append(f"track {name} references unknown elements: {sorted(unknown)}")
        sequence_pattern = re.compile(
            rf"<(?:Sequence|Series\.Sequence)\b[^>]*\bname\s*=\s*[{{]?['\"]{re.escape(str(name))}['\"]",
            re.IGNORECASE,
        )
        if not sequence_pattern.search(component_text):
            errors.append(f"named Sequence not found in source: {name}")
        if not re.search(rf"\b{re.escape(str(track['source_component']))}\b", component_text):
            errors.append(f"track source_component not found: {track['source_component']}")
    uncovered = element_ids - covered
    if uncovered:
        errors.append(f"visible elements missing Studio track coverage: {sorted(uncovered)}")

    verification = payload.get("studio_verification") or {}
    if require_verified:
        if verification.get("status") != "pass":
            errors.append("studio_verification.status must be pass")
        screenshot = verification.get("screenshot_path")
        screenshot_path = Path(str(screenshot or ""))
        if screenshot_path.is_absolute() or any(part in {"", ".", ".."} for part in screenshot_path.parts):
            errors.append("Studio verification screenshot must be a relative project path")
        if screenshot_path.name not in {"studio-timeline-screenshot.png", "studio-timeline-screenshot.jpg"}:
            errors.append("Studio verification must use live studio-timeline-screenshot.png or .jpg")
        screenshot_raw = project / screenshot_path
        if screenshot_raw.is_symlink():
            errors.append("Studio verification screenshot symlink not allowed")
        screenshot_file = screenshot_raw.resolve()
        try:
            screenshot_file.relative_to(project)
        except ValueError:
            errors.append("Studio verification screenshot escapes project")
        if not screenshot or not screenshot_file.is_file():
            errors.append(f"Studio timeline screenshot missing: {screenshot or '<unset>'}")
        visible = set(verification.get("visible_track_names") or [])
        missing_visible = track_names - visible
        if missing_visible:
            errors.append(f"Studio screenshot does not verify tracks: {sorted(missing_visible)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an editable Remotion Studio timeline")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--allow-unverified", action="store_true")
    args = parser.parse_args()
    failures = validate_project(
        args.project, args.manifest, require_verified=not args.allow_unverified
    )
    if failures:
        for failure in failures:
            print(f"BLOCKED: {failure}", file=sys.stderr)
        return 1
    suffix = "structure valid; screenshot pending" if args.allow_unverified else "rows and screenshot verified"
    print(f"studio-timeline-ready: {suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
