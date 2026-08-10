from __future__ import annotations

import re
from pathlib import Path


YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})"
)


def video_id_from_url(url: str) -> str:
    match = YOUTUBE_ID_RE.search(url)
    if match:
        return match.group(1)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", url).strip("_")
    return safe[:80] or "local_video"


def default_work_dir(cache_root: Path, video_url: str) -> Path:
    return cache_root / video_id_from_url(video_url)


def ensure_run_dirs(work_dir: Path) -> None:
    (work_dir / "frames").mkdir(parents=True, exist_ok=True)
