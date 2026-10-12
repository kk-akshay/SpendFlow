import sys, json
from playwright.sync_api import sync_playwright
BASE="http://localhost:8765"; SH="/tmp/claude-0/shots"; S="tests/samples"
errors=[]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium" if False else None)
    ctx = b.new_context(viewport={"width":1280,"height":900})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append("PAGEERROR "+str(e)))
    pg.on("console", lambda m: errors.append("CONSOLE "+m.text) if m.type=="error" and "fonts.googleapis" not in m.text and "ERR_" not in m.text else None)
    pg.goto(BASE); pg.fill("#em","e2e@test.io"); pg.click("#aswitch"); pg.fill("#em","e2e@test.io"); pg.fill("#pw","password123"); pg.click("#asub")
    pg.wait_for_selector(".empty"); pg.screenshot(path=f"{SH}/1_empty.png")
    pg.click("#e-imp"); pg.set_input_files("#files", [f"{S}/hdfc_ruled.pdf", f"{S}/gpay.pdf"]); pg.click("#igo")
    pg.wait_for_selector("#imp-ok", timeout=60000); pg.wait_for_timeout(400); pg.screenshot(path=f"{SH}/2_preview.png")
    pg.click("#imp-ok"); pg.wait_for_selector("#imp-ok", timeout=15000); pg.wait_for_timeout(300); pg.click("#imp-ok")
    pg.wait_for_selector("#card", timeout=15000); pg.wait_for_timeout(400); pg.screenshot(path=f"{SH}/3_review.png")
    print("progress:", pg.inner_text(".progress .top").replace("\n"," "))
    # keyboard: accept suggestion, pick by key, skip, undo
    pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    pg.keyboard.press("1"); pg.wait_for_timeout(500)
    pg.keyboard.press(" "); pg.wait_for_timeout(500)
    print("after 2 answers + skip:", pg.inner_text(".progress .top").replace("\n"," "))
    pg.keyboard.press("Backspace"); pg.wait_for_timeout(500)
    print("after undo:", pg.inner_text(".progress .top").replace("\n"," "))
    # reload mid-way: must resume
    pg.reload(); pg.wait_for_selector("#card"); print("after reload:", pg.inner_text(".progress .top").replace("\n"," "), "|", pg.inner_text(".merchant"))
    # split dialog
    pg.keyboard.press("/"); pg.wait_for_selector(".modal"); pg.screenshot(path=f"{SH}/4_split.png"); pg.keyboard.press("Escape")
    # answer a bunch quickly
    for k in ["2","3","1","4","5","Enter","6","7","1","2"]:
        pg.keyboard.press(k); pg.wait_for_timeout(350)
    for name in ["dashboard","transactions","plan","settings"]:
        pg.goto(f"{BASE}/#/{name}"); pg.wait_for_timeout(900); pg.screenshot(path=f"{SH}/5_{name}.png", full_page=True)
    pg.click("#nav-theme"); pg.goto(f"{BASE}/#/dashboard"); pg.wait_for_timeout(700); pg.screenshot(path=f"{SH}/6_dark.png", full_page=True)
    # mobile
    m = b.new_context(viewport={"width":390,"height":844}, has_touch=True, is_mobile=True, storage_state=ctx.storage_state()).new_page()
    m.on("pageerror", lambda e: errors.append("MOBILE PAGEERROR "+str(e)))
    m.goto(f"{BASE}/#/review"); m.wait_for_selector("#card"); m.wait_for_timeout(500); m.screenshot(path=f"{SH}/7_mobile_review.png")
    m.goto(f"{BASE}/#/dashboard"); m.wait_for_timeout(900); m.screenshot(path=f"{SH}/8_mobile_dash.png")
    sw = m.evaluate("document.documentElement.scrollWidth > window.innerWidth"); print("mobile horizontal overflow:", sw)
    b.close()
print("JS errors:", errors or "none")
