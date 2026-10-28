"""Screenshots of every screen at 390 and 1440 wide (uses the system Chrome; dev-only, needs `pip install playwright`)."""
import json, os, sys, urllib.request
from playwright.sync_api import sync_playwright
B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5090"; OUT = sys.argv[2] if len(sys.argv) > 2 else "/workspace/krio-order-crm-shots"
os.makedirs(OUT, exist_ok=True)
get = lambda u: json.load(urllib.request.urlopen(B + u))
O = get("/api/orders?chip=Needs%20check")[0]["id"]; F = get("/api/orders?chip=Replied")[0]["id"]
pages = [("01-inbox", "/"), ("02-review", f"/o/{O}"), ("03-receipt", f"/o/{F}/receipt"), ("04-customers", "/customers"), ("05-customer-detail", "/customers/1"),
         ("06-pharmacies", "/pharmacies"), ("07-pharmacy-detail", "/pharmacies/1"), ("08-catalogue", "/catalogue"), ("09-summary", "/summary"),
         ("10-settings-whatsapp", "/settings"), ("11-simulator", "/simulate")]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-gpu"])
    for w, h in ((390, 844), (1440, 900)):
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        for name, u in pages:
            pg.goto(B + u, wait_until="networkidle"); pg.screenshot(path=f"{OUT}/{name}-{w}.png", full_page=True); print(name, w)
        pg.close()
    b.close()
