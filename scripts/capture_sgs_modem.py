import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv('.env')

url = os.getenv('GRAFANA_URL', 'http://10.10.1.25:3000')
user = os.getenv('GRAFANA_USER', 'admin')
password = os.getenv('GRAFANA_PASSWORD', 'admin')

dash_url = f"{url}/d/sgs-modems-wan/sgs-modems-and-links-wan-sgs-links"

print(f"Opening Grafana at {dash_url}...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1600, "height": 1100})
    page = context.new_page()

    page.on("console", lambda msg: print(f"[BROWSER CONSOLE {msg.type}]: {msg.text}"))
    page.on("pageerror", lambda err: print(f"[BROWSER PAGE ERROR]: {err}"))

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

    # Check panel HTML
    content = page.content()
    print("Page title:", page.title())
    if "sgs-modem-container" in content:
        print("[OK] sgs-modem-container found in page DOM!")
    else:
        print("[WARN] sgs-modem-container NOT found in page DOM!")

    os.makedirs("assets", exist_ok=True)
    shot_path = "assets/sgs_modem_dashboard.png"
    page.screenshot(path=shot_path, full_page=True)
    print(f"Screenshot saved to {shot_path}")

    artifact_shot = r"C:\Users\alexs\.gemini\antigravity\brain\40fb7fed-c857-4252-b32f-2fce117b0af9\sgs_modem_dashboard.png"
    page.screenshot(path=artifact_shot, full_page=True)

    browser.close()
