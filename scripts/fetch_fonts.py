#!/usr/bin/env python3
"""Download the Meridian faces and regenerate their @font-face rules.

The fonts are self-hosted (see `frontend/app/src/styles/typography.css` for
why), which means adding a weight is a deliberate act rather than editing a URL.
This script is that act: it asks Google Fonts for the CSS, pulls every `woff2`
it references, and rewrites `typography.css`'s face block to point at local
paths — preserving the `unicode-range` subsetting rather than flattening it, so
a page of Latin text never downloads the extended set.

Run from the repository root:

    python scripts/fetch_fonts.py

Both families are OFL-licensed. `public/fonts/OFL.txt` must ship alongside them;
the licence requires it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "frontend" / "app" / "public" / "fonts"
CSS_FILE = ROOT / "frontend" / "app" / "src" / "styles" / "typography.css"

#: The weights the product actually uses. Adding one here and re-running is the
#: whole workflow — anything not listed is never downloaded and never shipped.
FAMILIES = {
    "Schibsted Grotesk": [400, 500, 600, 700],
    "Spline Sans Mono": [400, 500, 600],
}

#: Google serves different files per browser; asking as a modern Chrome is what
#: gets woff2 rather than a legacy format.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

MARKER_START = "/* --- generated faces: do not edit by hand --- */"
MARKER_END = "/* --- end generated faces --- */"


def google_css_url() -> str:
    parts = [
        f"family={name.replace(' ', '+')}:wght@{';'.join(str(w) for w in weights)}"
        for name, weights in FAMILIES.items()
    ]
    return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"


def fetch(url: str) -> str:
    result = subprocess.run(
        ["curl", "-sS", "-fL", "-A", UA, url], capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(f"Could not reach {url}\n{result.stderr}")
    return result.stdout


def main() -> int:
    css = fetch(google_css_url())
    blocks = re.findall(r"/\* (\S+) \*/\s*@font-face \{(.*?)\}", css, re.S)
    if not blocks:
        sys.exit("No @font-face blocks in the response — did the API shape change?")

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    faces = []
    for subset, body in blocks:
        family = re.search(r"font-family: '([^']+)'", body).group(1)
        weight = re.search(r"font-weight: (\d+)", body).group(1)
        url = re.search(r"url\((https://[^)]+)\)", body).group(1)
        unicode_range = re.search(r"unicode-range: ([^;]+);", body).group(1).strip()
        slug = family.lower().replace(" ", "-")
        name = f"{slug}-{weight}-{subset}.woff2"

        subprocess.run(["curl", "-sS", "-fL", "-o", str(FONT_DIR / name), url], check=True)
        faces.append((family, int(weight), subset, f"/fonts/{name}", unicode_range))

    faces.sort(key=lambda f: (f[0], f[1], f[2]))
    rules = "\n\n".join(
        f'@font-face {{\n'
        f'  font-family: "{family}";\n'
        f"  font-style: normal;\n"
        f"  font-weight: {weight};\n"
        f"  font-display: swap;\n"
        f'  src: url("{path}") format("woff2");\n'
        f"  unicode-range: {rng};\n"
        f"}}"
        for family, weight, subset, path, rng in faces
    )

    existing = CSS_FILE.read_text()
    if MARKER_START in existing and MARKER_END in existing:
        head = existing[: existing.index(MARKER_START) + len(MARKER_START)]
        tail = existing[existing.index(MARKER_END) :]
        CSS_FILE.write_text(f"{head}\n\n{rules}\n\n{tail}")
    else:
        sys.exit(
            f"Markers not found in {CSS_FILE.name}. Expected {MARKER_START!r} and "
            f"{MARKER_END!r} around the generated block."
        )

    total = sum(p.stat().st_size for p in FONT_DIR.glob("*.woff2"))
    print(f"{len(faces)} faces, {total / 1024:.1f} KB in {FONT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
