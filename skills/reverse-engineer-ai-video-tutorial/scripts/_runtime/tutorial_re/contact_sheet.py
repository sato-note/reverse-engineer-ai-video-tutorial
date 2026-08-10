from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .models import EvidenceFrame


def write_contact_sheet(
    frames: list[EvidenceFrame],
    output_path: Path,
    *,
    thumb_width: int = 360,
    columns: int = 3,
) -> Path | None:
    if not frames:
        return None

    thumbs: list[tuple[EvidenceFrame, Image.Image]] = []
    for frame in frames:
        image = Image.open(frame.path).convert("RGB")
        ratio = thumb_width / max(image.width, 1)
        thumb_height = max(1, int(image.height * ratio))
        image = image.resize((thumb_width, thumb_height))
        thumbs.append((frame, image))

    label_height = 34
    cell_height = max(image.height for _, image in thumbs) + label_height
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)

    for idx, (frame, image) in enumerate(thumbs):
        col = idx % columns
        row = idx // columns
        x = col * thumb_width
        y = row * cell_height
        sheet.paste(image, (x, y + label_height))
        label = f"{frame.source_span_id}  {_fmt_seconds(frame.timestamp)}"
        draw.text((x + 8, y + 8), label, fill="black")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def _fmt_seconds(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02}:{secs:05.2f}"
