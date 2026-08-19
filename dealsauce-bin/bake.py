#!/usr/bin/env python3
"""
Re-bake reiflow_foreclosures.json and reiflow_sellers.json into index.html's
INIT_FORECLOSURE / INIT_SELLER JS consts (the dashboard reads these at load,
then seeds localStorage from them — see the seed script already in index.html).
Idempotent: safe to run every night, only replaces the two array literals in
place, does not touch the one-time localStorage seed script.
"""
import json
import re
import os

REIFLOW_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ~/reiflow-command
INDEX_HTML = os.path.join(REIFLOW_DIR, 'index.html')
SELLERS_JSON = os.path.join(REIFLOW_DIR, 'reiflow_sellers.json')
FORECLOSURES_JSON = os.path.join(REIFLOW_DIR, 'reiflow_foreclosures.json')


def main():
    with open(SELLERS_JSON) as f:
        sellers = json.load(f)
    with open(FORECLOSURES_JSON) as f:
        foreclosures = json.load(f)

    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        html = f.read()

    sellers_js = json.dumps(sellers, separators=(',', ':'))
    foreclosures_js = json.dumps(foreclosures, separators=(',', ':'))

    # Anchor-based replace: JSON never contains a bare ';', so up to the next
    # known const declaration is a safe boundary.
    fc_pattern = re.compile(r"const INIT_FORECLOSURE=\[.*?\];(?=\s*\nconst INIT_SELLER=)", re.DOTALL)
    seller_pattern = re.compile(r"const INIT_SELLER=\[.*?\];(?=\s*\n)", re.DOTALL)

    html, n1 = fc_pattern.subn(f"const INIT_FORECLOSURE={foreclosures_js};", html, count=1)
    html, n2 = seller_pattern.subn(f"const INIT_SELLER={sellers_js};", html, count=1)

    if n1 != 1 or n2 != 1:
        raise SystemExit(
            f"bake.py: anchor patterns did not match cleanly (fc matches={n1}, seller matches={n2}) "
            f"— index.html structure may have changed, refusing to write a possibly-corrupt file."
        )

    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Baked {len(sellers)} sellers + {len(foreclosures)} foreclosures into index.html")


if __name__ == '__main__':
    main()
