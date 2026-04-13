#!/usr/bin/env python3
"""Generate print-ready PDFs (A4, 3x3 grid, MTG size) from card PNGs."""

import io
import math
import os
import random
from pathlib import Path
from typing import Optional

import typer
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Generate print-ready card sheets (PDF) from output/*/*.png")
console = Console()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_BACK = BASE_DIR / "card_back.png"

# --- Physical dimensions (MTG / Poker size) ---
CARD_W_MM = 63.0
CARD_H_MM = 88.0
DPI = 300

# Target pixel size at 300 DPI
CARD_W_PX = round(CARD_W_MM / 25.4 * DPI)  # 744
CARD_H_PX = round(CARD_H_MM / 25.4 * DPI)  # 1039

# Source card dimensions (from output/*.png)
SRC_W = 800
SRC_H = 1200

# Symmetric crop (top/bottom) to match MTG aspect ratio
# target aspect: 63/88 = 0.71591; source: 800/1200 = 0.66667
# cropped_h = 800 / (63/88) = 1117.46 -> 1117
# total crop = 83 px -> 42 top + 41 bottom
CROP_TOP = 42
CROP_BOTTOM = 41
CROPPED_H = SRC_H - CROP_TOP - CROP_BOTTOM  # 1117

# --- Layout (A4) ---
PAGE_W_MM, PAGE_H_MM = 210.0, 297.0
COLS, ROWS = 3, 3
CARDS_PER_PAGE = COLS * ROWS

# --- Aesthetics for generated back ---
BG_COLOR = (15, 23, 41)  # sampled from card corners
GOLD = (196, 146, 82)
GOLD_BRIGHT = (224, 180, 112)


def _crop_and_resize(img: Image.Image) -> Image.Image:
    """Crop source card symmetrically to MTG aspect and resize to target DPI."""
    if img.size != (SRC_W, SRC_H):
        # Defensive: enforce expected source
        img = img.resize((SRC_W, SRC_H), Image.LANCZOS)
    cropped = img.crop((0, CROP_TOP, SRC_W, SRC_H - CROP_BOTTOM))
    return cropped.resize((CARD_W_PX, CARD_H_PX), Image.LANCZOS)


def _find_cards(lang: str) -> list[Path]:
    """Find all card PNGs for a given language, sorted by category then index."""
    lang_dir = OUTPUT_DIR / lang
    if not lang_dir.is_dir():
        raise typer.BadParameter(f"No such language directory: {lang_dir}")
    cards: list[Path] = []
    for category_dir in sorted(lang_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue
        pngs = sorted(
            category_dir.glob("*.png"),
            key=lambda p: (int(p.stem) if p.stem.isdigit() else 10_000, p.stem),
        )
        cards.extend(pngs)
    return cards


def generate_default_back(output_path: Path) -> None:
    """Create a simple universal card back (starry navy + central d20 symbol).

    The back is a placeholder — replace the file or use --back to override.
    """
    w, h = CARD_W_PX, CARD_H_PX
    img = Image.new("RGB", (w, h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Starfield — sparse white/gold dots with jitter
    rng = random.Random(42)
    for _ in range(380):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        b = rng.randint(80, 220)
        color = (b, b, min(255, b + 20))
        if rng.random() < 0.12:
            color = (b, int(b * 0.75), int(b * 0.45))  # gold sparkle
        draw.point((x, y), fill=color)
    for _ in range(24):
        x = rng.randint(10, w - 10)
        y = rng.randint(10, h - 10)
        draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(200, 200, 230))

    # Outer decorative frame (thin double line, gold)
    margin = int(min(w, h) * 0.06)
    draw.rectangle(
        (margin, margin, w - margin, h - margin), outline=GOLD, width=3
    )
    inner = margin + 10
    draw.rectangle(
        (inner, inner, w - inner, h - inner), outline=GOLD, width=1
    )

    # Central d20 icon: hexagon outline with inverted triangle + "20"
    cx, cy = w // 2, h // 2
    r_outer = int(min(w, h) * 0.28)

    # Outer hexagon (pointy-top)
    hex_pts = [
        (cx + r_outer * math.cos(math.pi / 2 + i * math.pi / 3),
         cy - r_outer * math.sin(math.pi / 2 + i * math.pi / 3))
        for i in range(6)
    ]
    draw.polygon(hex_pts, outline=GOLD_BRIGHT)
    # Render as thicker line manually
    for i in range(6):
        draw.line([hex_pts[i], hex_pts[(i + 1) % 6]], fill=GOLD_BRIGHT, width=4)

    # Inner upward triangle (like top face of icosahedron)
    r_inner = int(r_outer * 0.62)
    tri_pts = [
        (cx, cy - r_inner),
        (cx - r_inner * math.cos(math.radians(30)),
         cy + r_inner * math.sin(math.radians(30))),
        (cx + r_inner * math.cos(math.radians(30)),
         cy + r_inner * math.sin(math.radians(30))),
    ]
    for i in range(3):
        draw.line([tri_pts[i], tri_pts[(i + 1) % 3]], fill=GOLD, width=3)

    # "20" text in the center
    font = None
    for font_path in (
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond-Bold.otf",
        "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ):
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, int(r_inner * 0.55))
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()

    text = "20"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1] + int(r_inner * 0.05)),
        text,
        fill=GOLD_BRIGHT,
        font=font,
    )

    img.save(output_path, "PNG", optimize=True)


def _load_back(back_path: Path) -> Image.Image:
    """Load a back image and normalize to target card pixel size."""
    img = Image.open(back_path).convert("RGB")
    if img.size != (CARD_W_PX, CARD_H_PX):
        img = img.resize((CARD_W_PX, CARD_H_PX), Image.LANCZOS)
    return img


def _pil_to_reader(img: Image.Image, use_jpeg: bool = False) -> ImageReader:
    """Encode a PIL image for embedding in the PDF.

    Defaults to PNG (lossless — best for print). JPEG is opt-in for much smaller files
    at the cost of mild artifacts on sharp edges (not ideal for pixel art).
    """
    buf = io.BytesIO()
    if use_jpeg:
        img.save(buf, format="JPEG", quality=92, subsampling=0, optimize=True)
    else:
        img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return ImageReader(buf)


def _draw_crop_marks(
    c: rl_canvas.Canvas,
    left: float,
    bottom: float,
    card_w: float,
    card_h: float,
    gap: float,
    cols: int,
    rows: int,
) -> None:
    """Draw crop marks at outer corners of the grid."""
    mark_len = 4 * mm
    mark_offset = 1 * mm  # distance from card edge
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.3)
    grid_w = cols * card_w + (cols - 1) * gap
    grid_h = rows * card_h + (rows - 1) * gap
    corners = [
        (left, bottom),                            # BL
        (left + grid_w, bottom),                   # BR
        (left, bottom + grid_h),                   # TL
        (left + grid_w, bottom + grid_h),          # TR
    ]
    for x, y in corners:
        # Horizontal tick (pointing outward)
        dx = -1 if x == left else 1
        dy = -1 if y == bottom else 1
        c.line(x + dx * mark_offset, y, x + dx * (mark_offset + mark_len), y)
        c.line(x, y + dy * mark_offset, x, y + dy * (mark_offset + mark_len))


def _grid_positions(
    left_mm: float, bottom_mm: float, card_w_mm: float, card_h_mm: float,
    gap_mm: float, cols: int, rows: int,
) -> list[tuple[float, float]]:
    """Top-to-bottom, left-to-right positions (x, y) of each cell (reportlab units=mm).

    Returns cells in reading order (row 0 = top).
    """
    positions = []
    for row in range(rows):
        # reportlab Y=0 is bottom, so top row has largest y
        y_mm = bottom_mm + (rows - 1 - row) * (card_h_mm + gap_mm)
        for col in range(cols):
            x_mm = left_mm + col * (card_w_mm + gap_mm)
            positions.append((x_mm * mm, y_mm * mm))
    return positions


def _mirror_backs_for_duplex(
    fronts_order: list[int], cols: int, rows: int, flip: str
) -> list[int]:
    """Remap indices for the back-side page so cards align after duplex flip.

    fronts_order: list of source-card indices placed on front page in reading order.
    Returns same indices re-ordered for the back page.
    """
    if flip == "long":
        # Flip columns (mirror each row horizontally)
        remapped = [0] * len(fronts_order)
        for row in range(rows):
            for col in range(cols):
                src_idx = row * cols + col
                dst_idx = row * cols + (cols - 1 - col)
                remapped[dst_idx] = fronts_order[src_idx]
        return remapped
    elif flip == "short":
        # Flip rows (mirror vertically)
        remapped = [0] * len(fronts_order)
        for row in range(rows):
            for col in range(cols):
                src_idx = row * cols + col
                dst_idx = (rows - 1 - row) * cols + col
                remapped[dst_idx] = fronts_order[src_idx]
        return remapped
    else:
        raise typer.BadParameter(f"--flip must be 'long' or 'short', got {flip!r}")


@app.command()
def generate(
    lang: str = typer.Option("pl", help="Language subdirectory under output/"),
    output: Optional[Path] = typer.Option(
        None, help="Output PDF path (default: output/<lang>/print.pdf)"
    ),
    back: Optional[Path] = typer.Option(
        None, help="Custom back image (default: ./card_back.png, auto-generated if missing)"
    ),
    gap_mm: float = typer.Option(0.0, help="Gap in mm between cards on the sheet"),
    flip: str = typer.Option("long", help="Duplex flip edge: 'long' or 'short'"),
    test_page: bool = typer.Option(
        False, "--test-page", help="Generate a single-page alignment test (1 front + 1 back)"
    ),
    no_backs: bool = typer.Option(
        False, "--no-backs", help="Skip back pages (fronts only, e.g. for sleeves)"
    ),
    crop_marks: bool = typer.Option(True, help="Draw crop marks at grid corners"),
    jpeg: bool = typer.Option(
        False, "--jpeg",
        help="Embed cards as JPEG (smaller PDF, mild edge artifacts). Default: PNG (lossless).",
    ),
) -> None:
    """Build a print-ready PDF for language LANG."""
    # Resolve back image (generate placeholder if missing)
    back_path = back or DEFAULT_BACK
    if not back_path.exists():
        console.print(
            Panel(
                f"No back image at [cyan]{back_path}[/cyan] — generating default placeholder.",
                title="Back image",
                border_style="yellow",
            )
        )
        generate_default_back(back_path)

    # Resolve output path
    if output is None:
        output = OUTPUT_DIR / lang / ("print_test.pdf" if test_page else "print.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Load cards
    card_paths = _find_cards(lang)
    if not card_paths:
        raise typer.BadParameter(f"No cards found in output/{lang}/*/*.png")

    if test_page:
        card_paths = card_paths[:1]

    # Summary table
    table = Table(title="Print sheet configuration", show_header=False)
    table.add_row("Language", lang)
    table.add_row("Cards found", str(len(card_paths)))
    table.add_row("Card size", f"{CARD_W_MM}×{CARD_H_MM} mm ({CARD_W_PX}×{CARD_H_PX} px @ {DPI}DPI)")
    table.add_row("Crop (top/bottom)", f"{CROP_TOP}/{CROP_BOTTOM} px")
    table.add_row("Grid", f"{COLS}×{ROWS} ({CARDS_PER_PAGE}/page)")
    table.add_row("Gap", f"{gap_mm} mm")
    table.add_row("Backs", "no" if no_backs else f"yes (flip={flip})")
    table.add_row("Output", str(output))
    console.print(table)

    back_img = _load_back(back_path)
    back_reader = _pil_to_reader(back_img, use_jpeg=jpeg)

    # Layout math
    grid_w_mm = COLS * CARD_W_MM + (COLS - 1) * gap_mm
    grid_h_mm = ROWS * CARD_H_MM + (ROWS - 1) * gap_mm
    left_mm = (PAGE_W_MM - grid_w_mm) / 2
    bottom_mm = (PAGE_H_MM - grid_h_mm) / 2

    c = rl_canvas.Canvas(str(output), pagesize=A4)

    # Chunk cards into pages
    pages: list[list[int]] = []
    for page_start in range(0, len(card_paths), CARDS_PER_PAGE):
        pages.append(list(range(page_start, min(page_start + CARDS_PER_PAGE, len(card_paths)))))

    for page_indices in pages:
        # --- FRONT PAGE ---
        positions = _grid_positions(
            left_mm, bottom_mm, CARD_W_MM, CARD_H_MM, gap_mm, COLS, ROWS
        )
        for slot, card_idx in enumerate(page_indices):
            x, y = positions[slot]
            img = Image.open(card_paths[card_idx]).convert("RGB")
            img = _crop_and_resize(img)
            c.drawImage(
                _pil_to_reader(img, use_jpeg=jpeg),
                x, y,
                width=CARD_W_MM * mm, height=CARD_H_MM * mm,
            )
        if crop_marks:
            _draw_crop_marks(c, left_mm * mm, bottom_mm * mm,
                             CARD_W_MM * mm, CARD_H_MM * mm,
                             gap_mm * mm, COLS, ROWS)
        c.showPage()

        # --- BACK PAGE ---
        if no_backs:
            continue
        # Pad page_indices to full grid (empty slots won't get a back)
        filled_slots = list(range(len(page_indices)))
        # Pad with sentinel -1 for empty slots
        fronts_order = page_indices + [-1] * (CARDS_PER_PAGE - len(page_indices))
        back_order = _mirror_backs_for_duplex(fronts_order, COLS, ROWS, flip)

        for slot, card_idx in enumerate(back_order):
            if card_idx < 0:
                continue
            x, y = positions[slot]
            c.drawImage(
                back_reader,
                x, y,
                width=CARD_W_MM * mm, height=CARD_H_MM * mm,
            )
        if crop_marks:
            _draw_crop_marks(c, left_mm * mm, bottom_mm * mm,
                             CARD_W_MM * mm, CARD_H_MM * mm,
                             gap_mm * mm, COLS, ROWS)
        c.showPage()

    c.save()
    console.print(f"[green]✓ Wrote[/green] {output} ([bold]{len(pages)}[/bold] front pages"
                  + ("" if no_backs else f" + {len(pages)} back pages") + ")")


@app.command("make-back")
def make_back(
    output: Path = typer.Option(DEFAULT_BACK, help="Where to write the back image"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing file"),
) -> None:
    """(Re)generate the default card back placeholder."""
    if output.exists() and not force:
        raise typer.BadParameter(f"{output} already exists. Use --force to overwrite.")
    generate_default_back(output)
    console.print(f"[green]✓ Wrote[/green] {output}")


if __name__ == "__main__":
    app()
