"""
Render one Structurizr view to PNG through a headless browser.

Runs inside the ui image, which holds Playwright and Chromium. Called by
scripts/export_diagram.sh, which starts the Structurizr server this script reads from.

    python3 export_diagram.py <diagram-page-url> <output.png>
"""

import base64
import sys
import time

from playwright.sync_api import Error, sync_playwright

SERVER_START_TIMEOUT_S = 120


def main(url, output_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        deadline = time.monotonic() + SERVER_START_TIMEOUT_S
        while True:
            try:
                page.goto(url)
                break
            except Error:
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        page.wait_for_function(
            "() => window.structurizr && structurizr.diagram && structurizr.diagram.isRendered()",
            timeout=SERVER_START_TIMEOUT_S * 1000,
        )
        data_url = page.evaluate(
            "() => new Promise(r => structurizr.diagram.exportCurrentDiagramToPNG({}, r))"
        )
        browser.close()
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(data_url.split(",", 1)[1]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
