from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
from _runtime.tutorial_re.manifest import read_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Write canonical framework readiness JSON.")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--toolchain-root", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    package = read_json(args.package)
    version = package.get("dependencies", {}).get("remotion")
    if not version:
        raise ValueError("package.json is missing dependencies.remotion")

    receipt = read_json(args.receipt) if args.receipt and args.receipt.is_file() else {}
    status = "ready" if receipt.get("state") == "ready" else "toolchain_ready_project_pending"
    write_json(
        args.output,
        {
            "schema_version": 1,
            "framework": "Remotion",
            "version": version,
            "status": status,
            "readiness_scope": "framework_toolchain_and_project_scaffold",
            "install_command": "prepare_remotion.py --setup-shared",
            "verification_command": "npm run typecheck; npm run compositions; shared Remotion render smoke",
            "project_root": args.project_root.replace("\\", "/"),
            "toolchain_root": str(args.toolchain_root).replace("\\", "/"),
            "toolchain_receipt": str(args.receipt).replace("\\", "/") if args.receipt else None,
            "toolchain_receipt_sha256": receipt.get("lock_sha256"),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
