#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
skill_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
exec python3 "$skill_root/scripts/install_skill.py" --source "$skill_root" "$@"
