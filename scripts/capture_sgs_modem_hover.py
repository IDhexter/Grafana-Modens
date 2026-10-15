import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv('.env')

url = os.getenv('GRAFANA_URL', 'http://10.10.1.25:3000')
user = os.getenv('GRAFANA_USER', 'admin')
password = os.getenv('GRAFANA_PASSWORD', 'admin')

dash_url = f"{url}/d/sgs-modems-wan/sgs-modems-and-links-wan-sgs-links"

print(f"Opening Grafana at {dash_url} to test hover inspection...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = context.new_page()

    page.on("console", lambda msg: print(f"[CONSOLE {msg.type}]: {msg.text}"))
    page.on("pageerror", lambda err: print(f"[PAGE ERROR]: {err}"))

    # Login to Grafana
    page.goto(f"{url}/login")
    page.fill("input[name='user']", user)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_timeout(3000)

    # Navigate to dashboard
    print("Navigating to dashboard...")
    page.goto(dash_url)
    page.wait_for_timeout(8000)

    # Locate the canvas wrap
    wrap = page.locator("#sgs-canvas-wrap")
    if wrap.count() > 0:
        box = wrap.bounding_box()
        if box:
            print(f"Canvas box found: {box}")
            # Hover over canvas at 60% of width
            target_x = box["x"] + box["width"] * 0.58
            target_y = box["y"] + box["height"] * 0.5
            print(f"Moving mouse to ({target_x}, {target_y})...")
            page.mouse.move(target_x, target_y)
            page.wait_for_timeout(1500)
    else:
        print("[WARN] #sgs-canvas-wrap not found!")

    os.makedirs("assets", exist_ok=True)
    shot_path = "assets/sgs_modem_hover_oscilloscope.png"
    page.screenshot(path=shot_path, full_page=True)
    print(f"Screenshot saved to {shot_path}")

    # Also capture just the oscilloscope card for detailed zoom inspection
    card = page.locator(".sgs-chart-card")
    if card.count() > 0:
        zoom_shot = "assets/sgs_modem_oscilloscope_detail.png"
        card.screenshot(path=zoom_shot)
        print(f"Oscilloscope detail screenshot saved to {zoom_shot}")

        artifact_detail = r"C:\Users\alexs\.gemini\antigravity\brain\40fb7fed-c857-4252-b32f-2fce117b0af9\sgs_modem_oscilloscope_detail.png"
        card.screenshot(path=artifact_detail)

    artifact_shot = r"C:\Users\alexs\.gemini\antigravity\brain\40fb7fed-c857-4252-b32f-2fce117b0af9\sgs_modem_hover_oscilloscope.png"
    page.screenshot(path=artifact_shot, full_page=True)

    browser.close()
    print("Done!")
