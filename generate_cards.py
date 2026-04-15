#!/usr/bin/env python3
"""Generate card PNGs from XCF templates using properties.json."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
)
from rich.table import Table

app = typer.Typer(help="Generate card game PNGs from XCF templates + properties.json")
console = Console()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PROPERTIES_PATH = os.path.join(BASE_DIR, "properties.json")


# --- Settings with hardcoded defaults ---


@dataclass
class LayerSettings:
    font: str = "Sans-serif"
    size: float = 12.0
    color: list[int] = field(default_factory=lambda: [0, 0, 0])
    center_x: int | None = None
    center_y: int | None = None


LAYER_DEFAULTS: dict[str, LayerSettings] = {
    "Name": LayerSettings(
        font="Noto Serif",
        size=12.5,
        color=[46, 75, 93],
        center_x=447,
        center_y=105,
    ),
    "Dice": LayerSettings(
        font="Noto Sans Devanagari Bold Italic",
        size=11,
        color=[46, 75, 93],
        center_x=447,
        center_y=1060,
    ),
}


def get_defaults(props: dict) -> dict:
    """Merge hardcoded LAYER_DEFAULTS with optional 'defaults' from properties.json.

    properties.json overrides win over hardcoded values.
    """
    merged = {}
    for name, settings in LAYER_DEFAULTS.items():
        merged[name] = asdict(settings)
    for name, overrides in props.get("defaults", {}).items():
        if name in merged:
            merged[name].update(overrides)
        else:
            merged[name] = overrides
    return merged


# --- Script-Fu generation ---


def escape_sf(s: str) -> str:
    """Escape a string for use inside Script-Fu double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_layer_script(
    layer_name: str,
    text: str,
    font: str,
    size: float,
    color: list[int],
    center_x: int | None,
    center_y: int | None,
) -> str:
    """Build Script-Fu commands to create/replace one text layer."""
    r, g, b = color
    lines = []

    # Remove existing layer with this name
    lines.append(
        f'    (let* ((old-layer (car (gimp-image-get-layer-by-name image "{escape_sf(layer_name)}"))))'
    )
    lines.append(f"      (when (>= old-layer 0)")
    lines.append(f"        (gimp-image-remove-layer image old-layer)))")

    # Create new text layer (unit 3 = POINTS)
    lines.append(
        f"    (let* ((tl (car (gimp-text-layer-new image"
        f' "{escape_sf(text)}" "{escape_sf(font)}" {size} 3))))'
    )
    lines.append(f"      (gimp-image-insert-layer image tl 0 0)")
    lines.append(f"      (gimp-text-layer-set-color tl '({r} {g} {b}))")
    lines.append(f'      (gimp-item-set-name tl "{escape_sf(layer_name)}")')

    # Center the text layer
    if center_x is not None or center_y is not None:
        lines.append(f"      (let* ((tw (car (gimp-drawable-width tl)))")
        lines.append(f"             (th (car (gimp-drawable-height tl)))")
        if center_x is not None:
            lines.append(f"             (ox (- {center_x} (quotient tw 2)))")
        else:
            lines.append(f"             (ox 0)")
        if center_y is not None:
            lines.append(f"             (oy (- {center_y} (quotient th 2)))")
        else:
            lines.append(f"             (oy 0)")
        lines.append(f"            )")
        lines.append(f"        (gimp-layer-set-offsets tl ox oy)))")
    else:
        lines.append(f"    )")

    return "\n".join(lines)


def resolve_layer_props(layer_name: str, value: str | dict, defaults: dict) -> dict:
    """Resolve text, font, size, color, position from value + defaults."""
    if isinstance(value, str):
        text = value
        overrides = {}
    else:
        text = value["text"]
        overrides = {k: v for k, v in value.items() if k != "text"}

    layer_defaults = defaults.get(layer_name, {})
    fallback = LayerSettings()

    return {
        "text": text,
        "font": overrides.get("font", layer_defaults.get("font", fallback.font)),
        "size": overrides.get("size", layer_defaults.get("size", fallback.size)),
        "color": overrides.get("color", layer_defaults.get("color", fallback.color)),
        "center_x": overrides.get(
            "center_x", layer_defaults.get("center_x", fallback.center_x)
        ),
        "center_y": overrides.get(
            "center_y", layer_defaults.get("center_y", fallback.center_y)
        ),
    }


def build_card_script(
    xcf_path: str, output_png: str, text_layers: dict, defaults: dict
) -> str:
    """Build Script-Fu for processing one card variant."""
    lines = []
    lines.append(
        f"  (let* ((image (car (gimp-file-load RUN-NONINTERACTIVE"
        f' "{escape_sf(xcf_path)}" "{escape_sf(os.path.basename(xcf_path))}"))))'
    )

    for layer_name, value in text_layers.items():
        if layer_name.startswith("_"):
            continue
        props = resolve_layer_props(layer_name, value, defaults)
        lines.append(
            build_layer_script(
                layer_name,
                props["text"],
                props["font"],
                props["size"],
                props["color"],
                props["center_x"],
                props["center_y"],
            )
        )

    lines.append(f"    (gimp-image-flatten image)")
    lines.append(
        f"    (file-png-save RUN-NONINTERACTIVE image"
        f" (car (gimp-image-get-active-drawable image))"
        f' "{escape_sf(output_png)}" "{escape_sf(os.path.basename(output_png))}"'
        f" 0 9 1 1 1 1 1)"
    )
    lines.append(f"    (gimp-image-delete image))")

    return "\n".join(lines)


def output_path(lang: str, xcf_rel_path: str, variant: str | None = None) -> str:
    """Compute output PNG path."""
    dirname = os.path.dirname(xcf_rel_path)
    basename = os.path.splitext(os.path.basename(xcf_rel_path))[0]
    if variant:
        basename = f"{basename}_{variant}"
    return os.path.join(OUTPUT_DIR, lang, dirname, f"{basename}.png")


def normalize_variants(card_value) -> list[tuple[str | None, dict]]:
    """Normalize card value to a list of (variant_name, layers_dict) tuples."""
    if isinstance(card_value, list):
        result = []
        for i, entry in enumerate(card_value):
            variant = entry.get("_variant", str(i))
            layers = {k: v for k, v in entry.items() if not k.startswith("_")}
            result.append((variant, layers))
        return result
    else:
        return [(None, card_value)]


# --- Commands ---


@app.command()
def generate(
    lang: str = typer.Option("pl", help="Language to process (empty string = all)"),
    card: Optional[str] = typer.Option(
        None, help="Process only this card (e.g. bears/1.xcf)"
    ),
):
    """Generate card PNGs from XCF templates."""
    if not os.path.exists(PROPERTIES_PATH):
        console.print(
            "[bold red]Error:[/] properties.json not found. Run [cyan]init-properties[/] first."
        )
        raise typer.Exit(1)

    with open(PROPERTIES_PATH) as f:
        props = json.load(f)

    defaults = get_defaults(props)

    # Collect jobs
    jobs = []
    for lang_key, cards in props.items():
        if lang_key == "defaults":
            continue
        if lang and lang_key != lang:
            continue
        for xcf_rel, card_value in cards.items():
            if card and xcf_rel != card:
                continue

            xcf_full = os.path.join(BASE_DIR, xcf_rel)
            if not os.path.exists(xcf_full):
                console.print(f"[yellow]Warning:[/] {xcf_rel} not found, skipping")
                continue

            for variant, layers in normalize_variants(card_value):
                png = output_path(lang_key, xcf_rel, variant)
                jobs.append((xcf_full, png, layers, xcf_rel, variant))

    if not jobs:
        console.print("[yellow]No cards to process.[/]")
        raise typer.Exit(0)

    # Show plan
    table = Table(
        title=f"Cards to generate ({lang or 'all languages'})", show_lines=False
    )
    table.add_column("Source", style="cyan")
    table.add_column("Variant", style="magenta")
    table.add_column("Output", style="green")
    for _, png, _, xcf_rel, variant in jobs:
        table.add_row(xcf_rel, variant or "-", os.path.relpath(png, BASE_DIR))
    console.print(table)
    console.print()

    # Ensure output dirs
    for _, png, _, _, _ in jobs:
        os.makedirs(os.path.dirname(png), exist_ok=True)

    # Build Script-Fu
    console.log("Building Script-Fu batch script...")
    script_lines = ["(gimp-message-set-handler 2)"]
    for xcf_full, png, layers, _, _ in jobs:
        script_lines.append(build_card_script(xcf_full, png, layers, defaults))
    script_lines.append("(gimp-quit 0)")
    script = "\n".join(script_lines)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".scm", delete=False) as f:
        f.write(script)
        script_path = f.name

    # Run GIMP
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Running GIMP batch...", total=len(jobs))

            result = subprocess.run(
                ["gimp", "-i", "-b", f'(load "{script_path}")'],
                capture_output=True,
                text=True,
                timeout=300,
            )

            # Check results
            for _, png, _, xcf_rel, variant in jobs:
                label = xcf_rel + (f" ({variant})" if variant else "")
                if os.path.exists(png):
                    progress.console.log(
                        f"[green]OK[/] {label} → {os.path.relpath(png, BASE_DIR)}"
                    )
                else:
                    progress.console.log(f"[red]FAIL[/] {label}")
                progress.advance(task)

        if result.returncode != 0:
            console.print(
                Panel(
                    f"GIMP exited with code {result.returncode}\nScript saved at: {script_path}",
                    title="Error",
                    style="red",
                )
            )
            if result.stderr:
                for line in result.stderr.splitlines():
                    if "error" in line.lower():
                        console.print(f"  [dim]{line}[/]")
            raise typer.Exit(1)

        # Summary
        ok = sum(1 for _, png, _, _, _ in jobs if os.path.exists(png))
        fail = len(jobs) - ok
        if fail == 0:
            console.print(f"\n[bold green]Done![/] Generated {ok} card(s)")
        else:
            console.print(f"\n[bold yellow]Done with errors:[/] {ok} OK, {fail} failed")

    finally:
        if result.returncode == 0:
            os.unlink(script_path)


def scan_xcf_files() -> list[str]:
    """Find all .xcf files in subdirectories, excluding templates and root."""
    xcf_files = []
    for dirpath, _, filenames in os.walk(BASE_DIR):
        if dirpath == BASE_DIR:
            continue
        rel_dir = os.path.relpath(dirpath, BASE_DIR)
        if rel_dir.startswith("output") or rel_dir.startswith("."):
            continue
        for fname in sorted(filenames):
            if fname.endswith(".xcf"):
                xcf_files.append(os.path.join(rel_dir, fname))
    return sorted(xcf_files)


@app.command("init-properties")
def init_properties(
    lang: Optional[str] = typer.Option(
        None, help="Add an empty language section (e.g. pl, en)"
    ),
    add_xcf: bool = typer.Option(
        False, "--add-xcf", help="Scan project and add all XCF files"
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing properties.json"
    ),
):
    """Generate a properties.json with default settings."""
    if os.path.exists(PROPERTIES_PATH) and not force:
        console.print(
            f"[yellow]properties.json already exists.[/] Use [cyan]--force[/] to overwrite."
        )
        raise typer.Exit(1)

    props: dict = {
        "defaults": {
            name: asdict(settings) for name, settings in LAYER_DEFAULTS.items()
        },
    }

    if lang:
        if add_xcf:
            xcf_files = scan_xcf_files()
            layer_names = [name for name in LAYER_DEFAULTS]
            cards = {}
            for xcf in xcf_files:
                cards[xcf] = {name: "" for name in layer_names}
            props[lang] = cards
            console.print(
                f"Added [cyan]{len(xcf_files)}[/] XCF files to language [cyan]{lang}[/]"
            )
        else:
            props[lang] = {}
            console.print(f"Added empty section for language [cyan]{lang}[/]")
    elif add_xcf:
        console.print("[yellow]--add-xcf requires --lang[/] (e.g. --lang pl --add-xcf)")
        raise typer.Exit(1)

    with open(PROPERTIES_PATH, "w") as f:
        json.dump(props, f, indent="\t", ensure_ascii=False)
        f.write("\n")

    console.print(
        f"[bold green]Created[/] {os.path.relpath(PROPERTIES_PATH, BASE_DIR)}"
    )


@app.command("sync-xcf")
def sync_xcf(
    lang: str = typer.Option("pl", help="Language section to sync"),
):
    """Add new XCF files from project directories to existing properties.json."""
    if not os.path.exists(PROPERTIES_PATH):
        console.print(
            "[bold red]Error:[/] properties.json not found. Run [cyan]init-properties[/] first."
        )
        raise typer.Exit(1)

    with open(PROPERTIES_PATH) as f:
        props = json.load(f)

    if lang not in props:
        props[lang] = {}

    existing = set(props[lang].keys())
    all_xcf = set(scan_xcf_files())
    new_xcf = sorted(all_xcf - existing)

    if not new_xcf:
        console.print(f"[green]No new XCF files found for [cyan]{lang}[/].[/]")
        raise typer.Exit(0)

    layer_names = list(LAYER_DEFAULTS)
    for xcf in new_xcf:
        props[lang][xcf] = {name: "" for name in layer_names}

    with open(PROPERTIES_PATH, "w") as f:
        json.dump(props, f, indent="\t", ensure_ascii=False)
        f.write("\n")

    console.print(f"Added [cyan]{len(new_xcf)}[/] new XCF file(s) to [cyan]{lang}[/]:")
    for xcf in new_xcf:
        console.print(f"  [green]+[/] {xcf}")


# --- Template-application command ---


def build_apply_template_script(
    template_path: str,
    target_w: int,
    target_h: int,
    trim_w: int,
    trim_h: int,
    card_paths: list[str],
    old_layer_name: str,
    new_layer_name: str,
) -> str:
    """Build Script-Fu that:

    1. Loads template, scales its single layer proportionally to fit within
       (trim_w × trim_h) preserving the template's own aspect ratio (no crop).
    2. Computes (offset_x, offset_y) that centers the scaled template on the
       target canvas — resulting bleed = (target - trim) / 2 on each side.
    3. For each card XCF: resizes canvas to target only if smaller (centering
       existing layers), removes old top layer by name, copies scaled template
       layer in at (offset_x, offset_y).
    4. Saves each XCF in place.
    """
    lines: list[str] = []
    lines.append("(let* (")
    lines.append(f'  (template (car (gimp-file-load RUN-NONINTERACTIVE'
                 f' "{escape_sf(template_path)}" "{escape_sf(os.path.basename(template_path))}")))')
    lines.append(f"  (tmpl-w (car (gimp-image-width template)))")
    lines.append(f"  (tmpl-h (car (gimp-image-height template)))")
    # Uniform scale: cover (trim_w, trim_h) — scale-to-fill, excess hangs off canvas
    lines.append(f"  (s-w (/ {trim_w}.0 tmpl-w))")
    lines.append(f"  (s-h (/ {trim_h}.0 tmpl-h))")
    lines.append(f"  (scale (max s-w s-h))")
    lines.append(f"  (scaled-w (round (* tmpl-w scale)))")
    lines.append(f"  (scaled-h (round (* tmpl-h scale)))")
    lines.append(f"  (offset-x (quotient (- {target_w} scaled-w) 2))")
    lines.append(f"  (offset-y (quotient (- {target_h} scaled-h) 2)))")
    lines.append(f"  (gimp-image-scale template scaled-w scaled-h)")
    # Clip template layer to canvas bounds (preserves alpha, no white fill)
    lines.append(f"  (gimp-layer-resize-to-image-size (vector-ref (cadr (gimp-image-get-layers template)) 0))")
    lines.append("")

    for card_path in card_paths:
        lines.append(f"  ;; --- card: {card_path} ---")
        lines.append(f'  (let* ((card (car (gimp-file-load RUN-NONINTERACTIVE'
                     f' "{escape_sf(card_path)}" "{escape_sf(os.path.basename(card_path))}")))')
        lines.append(f"         (card-w (car (gimp-image-width card)))")
        lines.append(f"         (card-h (car (gimp-image-height card))))")
        # Only resize canvas if smaller than target (idempotent re-runs)
        lines.append(f"    (when (or (< card-w {target_w}) (< card-h {target_h}))")
        lines.append(f"      (gimp-image-resize card {target_w} {target_h}")
        lines.append(f"                         (quotient (- {target_w} card-w) 2)")
        lines.append(f"                         (quotient (- {target_h} card-h) 2)))")
        # Remove old frame layer by name (if present)
        lines.append(f'    (let* ((old-layer (car (gimp-image-get-layer-by-name card "{escape_sf(old_layer_name)}"))))')
        lines.append(f"      (when (>= old-layer 0)")
        lines.append(f"        (gimp-image-remove-layer card old-layer)))")
        # Copy template layer in as new top-of-stack
        lines.append(f"    (let* ((tmpl-frame (vector-ref (cadr (gimp-image-get-layers template)) 0))")
        lines.append(f"           (new-layer (car (gimp-layer-new-from-drawable tmpl-frame card))))")
        lines.append(f"      (gimp-image-insert-layer card new-layer 0 -1)")
        lines.append(f'      (gimp-item-set-name new-layer "{escape_sf(new_layer_name)}")')
        lines.append(f"      (gimp-layer-set-offsets new-layer offset-x offset-y))")
        # Save XCF in place
        lines.append(f"    (gimp-xcf-save RUN-NONINTERACTIVE card")
        lines.append(f"                   (car (gimp-image-get-active-drawable card))")
        lines.append(f'                   "{escape_sf(card_path)}" "{escape_sf(os.path.basename(card_path))}")')
        lines.append(f"    (gimp-image-delete card))")
        lines.append("")

    lines.append("  (gimp-image-delete template))")
    return "\n".join(lines)


def find_card_xcfs(category: Optional[str] = None) -> list[str]:
    """Find all card XCFs (numeric stems like 1.xcf, 2.xcf, ...).

    Returns absolute paths.
    """
    cards: list[str] = []
    for rel in scan_xcf_files():
        # Skip root-level templates
        parts = rel.split(os.sep)
        if len(parts) < 2:
            continue
        if category and parts[0] != category:
            continue
        stem = os.path.splitext(parts[-1])[0]
        if not stem.isdigit():
            continue
        cards.append(os.path.join(BASE_DIR, rel))
    return sorted(cards)


@app.command("apply-template")
def apply_template(
    template: str = typer.Option(
        ..., help="Path to template XCF (e.g. template3.xcf)"
    ),
    card: Optional[str] = typer.Option(
        None, help="Process only this card (e.g. bears/1.xcf). Default: all numeric XCFs."
    ),
    category: Optional[str] = typer.Option(
        None, help="Process only cards in this category (e.g. bears). Default: all."
    ),
    target_width: int = typer.Option(876, help="Target canvas width in px (incl. bleed)"),
    target_height: int = typer.Option(1200, help="Target canvas height in px (incl. bleed)"),
    trim_width: int = typer.Option(876, help="Trim (printed) width in px — template scales to fit"),
    trim_height: int = typer.Option(1200, help="Trim (printed) height in px — template scales to fit"),
    old_layer: str = typer.Option("Frame", help="Name of the existing top layer to replace"),
    new_layer: str = typer.Option("Frame", help="Name to assign to the new layer"),
    no_backup: bool = typer.Option(
        False, "--no-backup", help="Skip creating .xcf.bak backups (NOT recommended)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan but don't run"),
) -> None:
    """Resize card XCFs and replace top layer with frame from a template XCF.

    Each card XCF: canvas resized to (target_width × target_height) with content
    centered horizontally, the layer named OLD_LAYER is removed, and the layer
    from TEMPLATE is scaled-and-cropped to fit then inserted on top as NEW_LAYER.
    """
    template_path = os.path.join(BASE_DIR, template) if not os.path.isabs(template) else template
    if not os.path.exists(template_path):
        console.print(f"[bold red]Error:[/] template not found: {template_path}")
        raise typer.Exit(1)

    # Collect target cards
    if card:
        card_full = os.path.join(BASE_DIR, card) if not os.path.isabs(card) else card
        if not os.path.exists(card_full):
            console.print(f"[bold red]Error:[/] card not found: {card_full}")
            raise typer.Exit(1)
        cards = [card_full]
    else:
        cards = find_card_xcfs(category=category)

    if not cards:
        console.print("[yellow]No card XCFs found to process.[/]")
        raise typer.Exit(0)

    # Plan summary
    table = Table(title="Apply template plan", show_header=False)
    table.add_row("Template", os.path.relpath(template_path, BASE_DIR))
    table.add_row("Cards", str(len(cards)))
    table.add_row("Target canvas", f"{target_width} × {target_height} px")
    table.add_row("Trim (fit-to)", f"{trim_width} × {trim_height} px")
    table.add_row("Replace layer", f'"{old_layer}" → "{new_layer}"')
    table.add_row("Backup", "no" if no_backup else "yes (.xcf.bak)")
    console.print(table)
    console.print()
    for c in cards:
        console.print(f"  [cyan]·[/] {os.path.relpath(c, BASE_DIR)}")
    console.print()

    if dry_run:
        console.print("[yellow]--dry-run: nothing executed.[/]")
        raise typer.Exit(0)

    # Backup
    if not no_backup:
        for c in cards:
            backup = c + ".bak"
            shutil.copy2(c, backup)
        console.print(f"[green]✓[/] Backed up {len(cards)} file(s) → *.xcf.bak")

    # Build & run Script-Fu
    script_lines = ["(gimp-message-set-handler 2)"]
    script_lines.append(
        build_apply_template_script(
            template_path,
            target_width,
            target_height,
            trim_width,
            trim_height,
            cards,
            old_layer,
            new_layer,
        )
    )
    script_lines.append("(gimp-quit 0)")
    script = "\n".join(script_lines)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".scm", delete=False) as f:
        f.write(script)
        script_path = f.name

    console.log(f"Script-Fu saved to {script_path}")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Running GIMP batch...", total=None)
            result = subprocess.run(
                ["gimp", "-i", "-b", f'(load "{script_path}")'],
                capture_output=True,
                text=True,
                timeout=300,
            )
            progress.update(task, completed=1, total=1)

        if result.returncode != 0:
            console.print(
                Panel(
                    f"GIMP exited with code {result.returncode}\nScript: {script_path}",
                    title="Error", style="red",
                )
            )
            if result.stderr:
                for line in result.stderr.splitlines():
                    if "error" in line.lower() or "Error" in line:
                        console.print(f"  [dim]{line}[/]")
            raise typer.Exit(1)

        console.print(f"\n[bold green]Done![/] Updated {len(cards)} XCF file(s).")
        if not no_backup:
            console.print("[dim]Backups available at *.xcf.bak — remove with: find . -name '*.xcf.bak' -delete[/]")
    finally:
        if result.returncode == 0:
            os.unlink(script_path)


if __name__ == "__main__":
    app()
