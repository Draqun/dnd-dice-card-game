#!/usr/bin/env python3
"""Generate card PNGs from XCF templates using properties.json.

Usage:
    python3 generate_cards.py                  # all languages, all cards
    python3 generate_cards.py --lang pl         # only Polish
    python3 generate_cards.py --card bears/1.xcf  # only one card
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def escape_sf(s):
    """Escape a string for use inside Script-Fu double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_layer_script(layer_name, text, font, size, color, center_x, center_y):
    """Build Script-Fu commands to create/replace one text layer."""
    r, g, b = color
    lines = []

    # Remove existing layer with this name
    lines.append(f'    (let* ((old-layer (car (gimp-image-get-layer-by-name image "{escape_sf(layer_name)}"))))')
    lines.append(f"      (when (>= old-layer 0)")
    lines.append(f"        (gimp-image-remove-layer image old-layer)))")

    # Create new text layer (unit 3 = POINTS)
    lines.append(
        f'    (let* ((tl (car (gimp-text-layer-new image'
        f' "{escape_sf(text)}" "{escape_sf(font)}" {size} 3))))'
    )
    lines.append(f"      (gimp-image-insert-layer image tl 0 -1)")
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


def resolve_layer_props(layer_name, value, defaults):
    """Resolve text, font, size, color, position from value + defaults."""
    if isinstance(value, str):
        text = value
        overrides = {}
    else:
        text = value["text"]
        overrides = {k: v for k, v in value.items() if k != "text"}

    layer_defaults = defaults.get(layer_name, {})

    return {
        "text": text,
        "font": overrides.get("font", layer_defaults.get("font", "Sans-serif")),
        "size": overrides.get("size", layer_defaults.get("size", 18)),
        "color": overrides.get("color", layer_defaults.get("color", [0, 0, 0])),
        "center_x": overrides.get("center_x", layer_defaults.get("center_x")),
        "center_y": overrides.get("center_y", layer_defaults.get("center_y")),
    }


def build_card_script(xcf_path, output_png, text_layers, defaults):
    """Build Script-Fu for processing one card variant."""
    lines = []
    lines.append(
        f'  (let* ((image (car (gimp-file-load RUN-NONINTERACTIVE'
        f' "{escape_sf(xcf_path)}" "{escape_sf(os.path.basename(xcf_path))}"))))'
    )

    for layer_name, value in text_layers.items():
        if layer_name.startswith("_"):
            continue  # skip meta keys like _variant
        props = resolve_layer_props(layer_name, value, defaults)
        lines.append(build_layer_script(
            layer_name, props["text"], props["font"], props["size"],
            props["color"], props["center_x"], props["center_y"],
        ))

    lines.append(f"    (gimp-image-flatten image)")
    lines.append(
        f'    (file-png-save RUN-NONINTERACTIVE image'
        f' (car (gimp-image-get-active-drawable image))'
        f' "{escape_sf(output_png)}" "{escape_sf(os.path.basename(output_png))}"'
        f" 0 9 1 1 1 1 1)"
    )
    lines.append(f"    (gimp-image-delete image))")

    return "\n".join(lines)


def output_path(lang, xcf_rel_path, variant=None):
    """Compute output PNG path."""
    dirname = os.path.dirname(xcf_rel_path)
    basename = os.path.splitext(os.path.basename(xcf_rel_path))[0]
    if variant:
        basename = f"{basename}_{variant}"
    return os.path.join(OUTPUT_DIR, lang, dirname, f"{basename}.png")


def normalize_variants(card_value):
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


def main():
    parser = argparse.ArgumentParser(description="Generate card PNGs from XCF + properties.json")
    parser.add_argument("--lang", help="Process only this language")
    parser.add_argument("--card", help="Process only this card (e.g. bears/1.xcf)")
    args = parser.parse_args()

    with open(os.path.join(BASE_DIR, "properties.json")) as f:
        props = json.load(f)

    defaults = props.get("defaults", {})

    # Collect all (xcf_path, output_png, layers) to process
    jobs = []
    for lang, cards in props.items():
        if lang == "defaults":
            continue
        if args.lang and lang != args.lang:
            continue
        for xcf_rel, card_value in cards.items():
            if args.card and xcf_rel != args.card:
                continue

            xcf_full = os.path.join(BASE_DIR, xcf_rel)
            if not os.path.exists(xcf_full):
                print(f"WARNING: {xcf_full} not found, skipping", file=sys.stderr)
                continue

            for variant, layers in normalize_variants(card_value):
                png = output_path(lang, xcf_rel, variant)
                jobs.append((xcf_full, png, layers))

    if not jobs:
        print("No cards to process.")
        return

    # Ensure output dirs exist
    for _, png, _ in jobs:
        os.makedirs(os.path.dirname(png), exist_ok=True)

    # Build one big Script-Fu script
    script_lines = ["(gimp-message-set-handler 2)"]
    for xcf_full, png, layers in jobs:
        script_lines.append(build_card_script(xcf_full, png, layers, defaults))
    script_lines.append("(gimp-quit 0)")

    script = "\n".join(script_lines)

    # Write to temp file and run GIMP
    with tempfile.NamedTemporaryFile(mode="w", suffix=".scm", delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        print(f"Processing {len(jobs)} card(s)...")
        result = subprocess.run(
            ["gimp", "-i", "-b", f'(load "{script_path}")'],
            capture_output=True, text=True, timeout=120,
        )
        # Script-Fu messages go to stderr
        if result.stderr:
            for line in result.stderr.splitlines():
                if "script-fu" in line.lower() or "error" in line.lower():
                    print(f"  GIMP: {line}", file=sys.stderr)

        if result.returncode != 0:
            print(f"GIMP exited with code {result.returncode}", file=sys.stderr)
            print(f"Script saved at: {script_path}", file=sys.stderr)
            sys.exit(1)

        for _, png, _ in jobs:
            status = "OK" if os.path.exists(png) else "MISSING"
            print(f"  [{status}] {os.path.relpath(png, BASE_DIR)}")

    finally:
        if result.returncode == 0:
            os.unlink(script_path)


if __name__ == "__main__":
    main()
