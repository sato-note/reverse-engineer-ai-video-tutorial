from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from run import _ensure_runtime  # noqa: E402
from studio_timeline_guard import validate_project  # noqa: E402


RASTER_TYPES = {
    "person", "building", "vehicle", "editorial_object", "background",
    "environment", "illustration", "photograph", "texture",
}
SEMANTIC_SVG = re.compile(
    r"(?:const|function)\s+(?:Portrait|Person|WhiteHouse|Building|Vehicle|Flag)\b[\s\S]{0,6000}?<svg\b",
    re.IGNORECASE,
)
NAMED_SEQUENCE = re.compile(r"<Sequence\b[^>]*\bname\s*=", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Block scene render until ImageGen2 assets pass")
    parser.add_argument("--run", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    _ensure_runtime()

    from tutorial_re.manifest import read_json
    from tutorial_re.validate import validate_stage

    failures: list[str] = []
    ledger = {"assets": []}
    if args.run:
        ledger_path = args.run / "scene_plan/asset_ledger.json"
        if not ledger_path.is_file():
            failures.append(f"asset ledger missing: {ledger_path}")
        else:
            result = validate_stage(args.run, "assets-approved")
            failures.extend(error["message"] for error in result["errors"])
            ledger = read_json(ledger_path)
    source_files = list(args.project.rglob("*.tsx")) + list(args.project.rglob("*.jsx"))
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_files)

    for asset in ledger.get("assets", []):
        if asset.get("semantic_type") not in RASTER_TYPES:
            continue
        output = asset.get("output", {})
        filename = Path(str(output.get("path", ""))).name
        if not filename or filename not in source_text:
            failures.append(f"raster asset not bound in scene source: {asset.get('id')}")

    for path in source_files:
        text = path.read_text(encoding="utf-8")
        if SEMANTIC_SVG.search(text):
            failures.append(f"procedural semantic SVG forbidden: {path}")
        if "useCurrentFrame" in text and not NAMED_SEQUENCE.search(text):
            failures.append(f"animated Remotion scene needs named Sequence timeline tracks: {path}")

    package_path = args.project / "package.json"
    if package_path.is_file() and '"remotion"' in package_path.read_text(encoding="utf-8"):
        failures.extend(validate_project(args.project))

    if failures:
        for failure in failures:
            print(f"BLOCKED: {failure}", file=sys.stderr)
        return 1
    print("render-ready: ImageGen2 assets bound and Remotion Studio timeline verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
