#!/usr/bin/env python3
# fetch_stream_optimized.py

import os
import sys
import time
import json
import re
import shutil
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

try:
    from webdriver_manager.chrome import ChromeDriverManager
    _HAS_WDM = True
except Exception:
    _HAS_WDM = False

DEFAULT_URL = "https://news.abplive.com/live-tv"
M3U8_RE = re.compile(r'https?://[^\'"\s>]+\.m3u8[^\'"\s>]*', flags=re.IGNORECASE)

def now():
    return time.strftime("%H:%M:%S")

def extract_m3u8_from_text(text):
    if not text:
        return []
    return M3U8_RE.findall(text)

def find_chromedriver_from_env_or_path():
    env_path = os.getenv("CHROMEDRIVER_PATH")
    if env_path and shutil.which(env_path):
        return env_path
    path = shutil.which("chromedriver")
    if path:
        return path
    if _HAS_WDM:
        try:
            return ChromeDriverManager(cache_valid_range=365).install()
        except Exception:
            return None
    return None

def make_driver(chromedriver_path):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720") # Force consistent window size for ActionChains
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--no-first-run")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    
    service = Service(chromedriver_path) if chromedriver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(int(os.getenv("STARTUP_TIMEOUT", "30")))
    return driver

def attempt_play_click(driver):
    """Robust 3-step sequence to bypass covers, ad-overlays, and iframes."""
    print(f"{now()} 🖱️ Starting robust play-click sequence...")

    # STEP 1: Click fake covers on the main page (123movies often requires this to load the iframe)
    try:
        js_main = """
        var selectors = ['.Tp-Poster', '.TPlayerPlay', '.play-video', '#play-now', '.play-btn', '.play', '#my-video'];
        var clicked = 0;
        for (var s of selectors) {
            document.querySelectorAll(s).forEach(function(el) {
                if (el.offsetParent !== null) {
                    el.scrollIntoView({behavior: 'smooth', block: 'center'});
                    el.click();
                    clicked++;
                }
            });
        }
        return clicked;
        """
        main_clicks = driver.execute_script(js_main)
        if main_clicks > 0:
            print(f"{now()}   -> Clicked {main_clicks} cover/play element(s) on main page. Waiting for iframe...")
            time.sleep(2.0)
    except Exception as e:
        print(f"{now()}   -> Warning on main page JS click: {e}")

    # STEP 2: Find the player (Iframe or Video tag), scroll to it, and use Physical Mouse Clicks
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        target_elements = iframes if iframes else driver.find_elements(By.TAG_NAME, "video")
        
        if not target_elements:
            print(f"{now()}   -> ⚠️ No iframes or video tags found on the page.")
            return

        for idx, el in enumerate(target_elements):
            print(f"{now()}   -> Targeting {'iframe' if iframes else 'video'} #{idx+1}...")
            
            # Scroll element dead center
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(1)

            # Use ActionChains to simulate a real OS mouse click on the center of the element
            actions = ActionChains(driver)
            
            # Click 1: Absorbs the invisible ad-overlay
            actions.move_to_element(el).click().perform()
            time.sleep(0.5)
            
            # Click 2: Actually triggers the video
            actions.move_to_element(el).click().perform()
            time.sleep(1.0)

            # STEP 3: If it's an iframe, dive into it and click internal player buttons
            if el.tag_name == "iframe":
                print(f"{now()}   -> Switching into iframe to click internal play buttons...")
                driver.switch_to.frame(el)
                
                js_iframe = """
                var inner_selectors = ['.vjs-big-play-button', '.jw-icon-display', '.jw-state-idle', '.ytp-large-play-button', '.plyr__control--overlaid', 'video'];
                var clicked = 0;
                for (var s of inner_selectors) {
                    document.querySelectorAll(s).forEach(function(btn) {
                        if (btn.offsetParent !== null) {
                            btn.click();
                            clicked++;
                        }
                    });
                }
                return clicked;
                """
                try:
                    inner_clicks = driver.execute_script(js_iframe)
                    print(f"{now()}   -> Clicked {inner_clicks} element(s) inside the iframe.")
                except Exception as e:
                    pass
                
                # IMPORTANT: Switch back to main page so the rest of the script works
                driver.switch_to.default_content()

    except Exception as e:
        print(f"{now()}   -> ⚠️ Error during physical mouse/iframe clicking: {e}")
        driver.switch_to.default_content()

def main():
    target_url = os.getenv("TARGET_URL") or (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)
    if not target_url:
        print("\x1b[31mNo URL provided. Exiting.\x1b[0m")
        sys.exit(1)

    MAX_WAIT = float(os.getenv("MAX_WAIT_SECONDS", "15"))
    POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "0.6"))

    print(f"{now()} 🌀 Starting optimized Selenium CDP capture")
    print(f"{now()} Target URL: {target_url}")

    chromedriver_path = find_chromedriver_from_env_or_path()
    driver = None
    try:
        driver = make_driver(chromedriver_path)
        print(f"{now()} Selenium launched")

        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except Exception:
            pass

        # Load page
        driver.get(target_url)
        time.sleep(2.0)
        
        # --- THE CLICK SEQUENCE ---
        attempt_play_click(driver)
        
        # Take a screenshot for debugging on your phone
        driver.save_screenshot("player_screenshot.png")
        print(f"{now()} 📸 Saved debug screenshot to player_screenshot.png")

        found = set()
        processed = set()
        start = time.time()

        # Listen for Network Traffic
        while time.time() - start < MAX_WAIT:
            logs = []
            try:
                logs = driver.get_log("performance")
            except Exception:
                pass

            for entry in logs:
                raw = entry.get("message")
                if not raw or raw in processed:
                    continue
                processed.add(raw)

                try:
                    msg = json.loads(raw)["message"]
                except Exception:
                    continue

                method = msg.get("method", "")
                params = msg.get("params", {}) or {}

                if method == "Network.requestWillBeSent":
                    url = params.get("request", {}).get("url", "") or ""
                    if ".m3u8" in url.lower() and url not in found:
                        found.add(url)
                        print(f"{now()} \x1b[32mFound .m3u8 URL (request):\x1b[0m {url}")

                elif method == "Network.responseReceived":
                    resp = params.get("response", {}) or {}
                    url = resp.get("url", "") or ""
                    
                    if ".m3u8" in url.lower() and url not in found:
                        found.add(url)
                        print(f"{now()} \x1b[32mFound .m3u8 URL (response):\x1b[0m {url}")

                    mime = (resp.get("mimeType") or "").lower()
                    should_fetch_body = False
                    if url and any(url.lower().endswith(x) for x in ('.json', '.js', '.txt', '.html')):
                        should_fetch_body = True
                    if "json" in mime or "text" in mime or "html" in mime:
                        should_fetch_body = True
                    if resp.get("encodedDataLength", 0) > 200_000:
                        should_fetch_body = False

                    if should_fetch_body:
                        request_id = params.get("requestId")
                        if request_id:
                            try:
                                body_info = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
                                body_text = body_info.get("body", "") if isinstance(body_info, dict) else ""
                                if body_text and ".m3u8" in body_text:
                                    for m in extract_m3u8_from_text(body_text):
                                        if m not in found:
                                            found.add(m)
                                            print(f"{now()} \x1b[32mFound .m3u8 URL (in body):\x1b[0m {m}")
                            except Exception:
                                pass

            if found:
                break
            time.sleep(POLL_INTERVAL)

        # Final output
        if found:
            print(f"{now()} \x1b[32m✅ Total .m3u8 URLs found: {len(found)}\x1b[0m")
            for u in sorted(found):
                print(u)
            sys.exit(0)
        else:
            print(f"{now()} \x1b[33m⚠️ No .m3u8 URL found within {MAX_WAIT}s.\x1b[0m")
            sys.exit(2)

    finally:
        if driver:
            driver.quit()
            print(f"{now()} Selenium driver quit")

if __name__ == "__main__":
    main()
