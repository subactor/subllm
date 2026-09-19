"""Optional browser acceptance: pip install playwright; playwright install chromium.
Run from the repository with PYTHONPATH=src python scripts/verify-usage-browser.py.
Uses isolated synthetic records only; never calls a provider or the operator DB.
"""

import argparse
import json
import os
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from subllm.poa import make_server
from subllm.usage import record_attempt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--browser", help="Optional Chromium executable")
parser.add_argument("--screenshots", type=Path, help="Optional directory for screenshots")
args = parser.parse_args()
if args.screenshots:
    args.screenshots.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    os.environ["SUBLLM_USAGE_DB"] = tmp + "/usage.sqlite3"

    def seed(app, provider, status="success", request="fixture"):
        record_attempt(
            request_id=request,
            application=app,
            function="semantic",
            provider=provider,
            model="glm-5.3",
            status=status,
            diagnostic_code="SUBLLM-PROVIDER-RATE-LIMIT" if status == "error" else None,
            duration_ms=1240,
            usage={"input_tokens": 421, "output_tokens": 87} if status == "success" else {},
        )

    seed("todo2code", "zai", "error")
    seed("todo2code", "openrouter")
    seed("koru-agent", "zai", request="other")
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.browser, headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.locator("#rows tr")).to_have_count(3)
            assert page.locator("#requests").inner_text() == "2"
            assert page.locator("#errors").inner_text() == "1"
            if args.screenshots:
                page.screenshot(path=str(args.screenshots / "dashboard-desktop.png"), full_page=True)
            page.locator("#application").select_option("todo2code")
            page.get_by_role("button", name="Zastosuj").click()
            expect(page.locator("#rows tr")).to_have_count(2)
            page.locator("#clear-filters").click()
            expect(page.locator("#rows tr")).to_have_count(3)
            seed("semcod-nfo", "zai", request="new")
            expect(page.locator("#rows tr")).to_have_count(4, timeout=10000)
            page.set_viewport_size({"width": 390, "height": 844})
            if args.screenshots:
                page.screenshot(path=str(args.screenshots / "dashboard-mobile.png"), full_page=True)
            assert page.locator("body").bounding_box()["width"] <= 390
            assert not errors, errors
            browser.close()
            print(
                json.dumps(
                    {
                        "ok": True,
                        "checks": [
                            "desktop rendering",
                            "filters",
                            "reset",
                            "live refresh",
                            "mobile layout",
                            "no browser errors",
                        ],
                        "data": "isolated synthetic fixtures, no provider traffic",
                    }
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
