from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from run import _ensure_runtime  # noqa: E402


def main() -> int:
    _ensure_runtime()
    from tutorial_re.validate import main as validate_main

    return validate_main()


if __name__ == "__main__":
    raise SystemExit(main())
