import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv('.env')

url = os.getenv('GRAFANA_URL', 'http://10.10.1.25:3000')
user = os.getenv('GRAFANA_USER', 'admin')
password = os.getenv('GRAFANA_PASSWORD', 'admin')

dash_url = f"{url}/d/sgs-modems-wan/sgs-modems-and-links-wan-sgs-links"

print(f"Opening Grafana at {dash_url} to test functional LAN ports...")

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

    # 1. Capture initial state (WAN selected)
    os.makedirs("assets", exist_ok=True)
    page.screenshot(path="assets/sgs_modem_lan_initial.png", full_page=True)
    print("Saved assets/sgs_modem_lan_initial.png")

    # 2. Inspect LAN port 0 (LAN 1)
    lan0 = page.locator("#sgs-lan-unit-0")
    if lan0.count() > 0:
        title = lan0.get_attribute("title") or ""
        print("LAN 1 title found!")
        print("Clicking on LAN 1 to test 1-click interface switching...")
        lan0.click()
        page.wait_for_timeout(5000)

        # Capture state with LAN 1 selected
        page.screenshot(path="assets/sgs_modem_lan1_selected.png", full_page=True)
        print("Saved assets/sgs_modem_lan1_selected.png")

        # Also capture close-up of the chassis
        chassis = page.locator(".sgs-modem-chassis")
        if chassis.count() > 0:
            chassis.screenshot(path="assets/sgs_chassis_lan_closeup.png")
            print("Saved assets/sgs_chassis_lan_closeup.png")

    browser.close()
    print("Test completed successfully!")
