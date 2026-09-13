"""
generate_city_poster.py
========================

Pipeline example: generate a poster-style city map (à la Etsy/MapPrints)
from a city name, ready for print or digital download.

Flow this is meant to slot into (Lovable frontend -> n8n/Python backend):
    1. User picks a city + style + size on the Lovable site.
    2. Frontend calls a webhook (n8n) with {city, style, size_cm, dpi}.
    3. n8n triggers this script (or a wrapped API) on the backend.
    4. Script returns a high-res PNG/SVG file (or a URL to it).

Requirements:
    pip install prettymaps osmnx matplotlib vsketch --break-system-packages

Note: prettymaps pulls data from OpenStreetMap live, so this needs
outbound internet access wherever it actually runs (e.g. your n8n
server / a cloud function) - it will NOT run in this sandboxed
environment, which has no network access. Treat this as the
reference implementation to deploy elsewhere.
"""

import argparse
import os
import time
from pathlib import Path

import matplotlib.pyplot as plt
import osmnx as ox
import prettymaps

# Without this, a stalled/slow response from the Overpass API (OpenStreetMap's
# query backend) can hang the whole request indefinitely with no error and no
# way to tell what's wrong. 60s is generous for a single map; if it's still
# too slow, that itself is useful information (Overpass may be overloaded -
# consider a smaller radius or retrying later).
ox.settings.timeout = 60


# ---------------------------------------------------------------------------
# Style presets - this is your product catalog. Each preset = one "look"
# you can sell. Add more presets to expand your product line without
# touching the generation logic.
# ---------------------------------------------------------------------------
STYLE_PRESETS = {
    "minimal_light": {
        "background": {"fc": "#F2F2F2", "zorder": -1},
        "perimeter": {"fc": "#F2F2F2", "ec": "#2F3737", "lw": 0},
        "streets": {"fc": "#2F3737", "ec": "#2F3737", "lw": 1.5},
        "building": {"fc": "#FFFFFF", "ec": "#2F3737", "lw": 0.5},
        "water": {"fc": "#A8C8D8", "ec": "#2F3737", "lw": 0},
        "green": {"fc": "#8BB174", "ec": "#2F3737", "lw": 0},
    },
    "dark_mode": {
        "background": {"fc": "#0B0B0F", "zorder": -1},
        "perimeter": {"fc": "#0B0B0F", "ec": "#0B0B0F", "lw": 0},
        "streets": {"fc": "#F2C078", "ec": "#F2C078", "lw": 1.5},
        "building": {"fc": "#1B1B23", "ec": "#F2C078", "lw": 0.3},
        "water": {"fc": "#12324A", "ec": "#12324A", "lw": 0},
        "green": {"fc": "#1D3324", "ec": "#1D3324", "lw": 0},
    },
    "warm_terracotta": {
        "background": {"fc": "#FBF1E6", "zorder": -1},
        "perimeter": {"fc": "#FBF1E6", "ec": "#5C3A21", "lw": 0},
        "streets": {"fc": "#B5573A", "ec": "#B5573A", "lw": 1.5},
        "building": {"fc": "#F0DCC4", "ec": "#5C3A21", "lw": 0.5},
        "water": {"fc": "#8FB8C9", "ec": "#5C3A21", "lw": 0},
        "green": {"fc": "#9CAF6B", "ec": "#5C3A21", "lw": 0},
    },
}


def generate_poster(
    city: str,
    style: str = "minimal_light",
    radius_m: int = 1500,
    size_cm: tuple[float, float] = (30, 40),
    dpi: int = 300,
    caption: str | None = None,
    output_dir: str = "output",
) -> str:
    """
    Generate a poster-style map PNG for `city` and save it to disk.

    Returns the output file path.
    """
    if style not in STYLE_PRESETS:
        raise ValueError(f"Unknown style '{style}'. Options: {list(STYLE_PRESETS)}")

    width_in = size_cm[0] / 2.54
    height_in = size_cm[1] / 2.54

    fig, ax = plt.subplots(figsize=(width_in, height_in))

    print(f"[generate_poster] fetching OSM data for '{city}' (radius={radius_m}m)...", flush=True)
    t0 = time.time()

    # Core call: prettymaps pulls streets/buildings/water/green space
    # from OpenStreetMap around the city center and renders them
    # with the chosen style layers.
    prettymaps.plot(
        city,
        ax=ax,
        radius=radius_m,
        layers={
            "perimeter": {},
            "streets": {"width": 1.5},
            "building": {"tags": {"building": True}, "union": False},
            "water": {"tags": {"natural": ["water", "bay"]}},
            "green": {"tags": {"landuse": "grass", "natural": ["wood", "island"]}},
        },
        style=STYLE_PRESETS[style],
    )
    print(f"[generate_poster] OSM fetch + draw done in {time.time() - t0:.1f}s", flush=True)

    # Optional caption under the map (city name + custom subtitle),
    # this is the "personalization" that lets you upsell per-order.
    if caption:
        fig.text(
            0.5, 0.04, caption,
            ha="center", va="bottom",
            fontsize=22, fontfamily="serif",
            color=STYLE_PRESETS[style]["streets"]["fc"],
        )

    ax.set_axis_off()
    fig.patch.set_facecolor(STYLE_PRESETS[style]["background"]["fc"])

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    safe_name = city.split(",")[0].strip().lower().replace(" ", "_")
    out_path = os.path.join(output_dir, f"{safe_name}_{style}.png")

    fig.savefig(out_path, dpi=dpi, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)

    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a poster-style city map")
    parser.add_argument("city", help="City name, e.g. 'Tel Aviv, Israel'")
    parser.add_argument("--style", default="minimal_light", choices=STYLE_PRESETS.keys())
    parser.add_argument("--radius", type=int, default=1500, help="Radius in meters")
    parser.add_argument("--width_cm", type=float, default=30)
    parser.add_argument("--height_cm", type=float, default=40)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--caption", default=None, help='e.g. "TEL AVIV — 32.0853° N, 34.7818° E"')
    args = parser.parse_args()

    path = generate_poster(
        city=args.city,
        style=args.style,
        radius_m=args.radius,
        size_cm=(args.width_cm, args.height_cm),
        dpi=args.dpi,
        caption=args.caption,
    )
    print(f"Saved: {path}")