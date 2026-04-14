"""
Stealth Browser Factory — Anti-bot detection evasion for browser automation.

Tiered approach (highest ↔ lowest overhead):
  1. camoufox   — Engine-level Firefox stealth. Full fingerprint spoofing.
                  +250MB RAM, +2-3s launch. DEFAULT.
  2. patchright  — Patched Playwright (Chromium). CDP leak fixes, no webdriver flag.
                  ~Zero overhead. Fallback if camoufox unavailable.
  3. none        — Vanilla Playwright. No stealth. Only for local testing.

Usage:
    browser, context = await create_stealth_browser()
    page = await context.new_page()
    # ... use page normally ...
    await browser.close()

Or as an async context manager:
    async with stealth_browser() as (browser, context):
        page = await context.new_page()
"""
from __future__ import annotations

import asyncio
import logging
import random
import string
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Real-world User-Agent pool (top browsers, March 2026)
# ─────────────────────────────────────────────
_USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Common desktop viewport resolutions (width x height) by market share
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720},
    {"width": 2560, "height": 1440},
    {"width": 1600, "height": 900},
]

# Persistent browser state directory (preserves cookies/localStorage across sessions)
_STATE_DIR = Path("./records/.browser_state")


def _get_random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _get_random_viewport() -> dict:
    return random.choice(_VIEWPORTS)


def _get_state_path() -> Path:
    """Returns the persistent browser state directory, creating it if needed."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _STATE_DIR


# ─────────────────────────────────────────────
# Tier 1: Camoufox (default)
# ─────────────────────────────────────────────
async def _launch_camoufox(
    headless: bool,
    proxy: str | None,
    viewport: dict,
    user_agent: str,
) -> tuple:
    """
    Launch a Camoufox browser with full fingerprint spoofing.
    Returns (browser, context) compatible with Playwright API.
    """
    from camoufox.async_api import AsyncCamoufox  # type: ignore

    state_path = _get_state_path()
    storage_state = state_path / "camoufox_state.json"

    proxy_cfg = None
    if proxy:
        proxy_cfg = {"server": proxy}

    kwargs: dict = {
        "headless": headless,
        "viewport": viewport,
        "geoip": True,           # align timezone/locale with IP automatically
        "humanize": True,         # built-in human-like mouse movement
    }
    if proxy_cfg:
        kwargs["proxy"] = proxy_cfg

    browser = await AsyncCamoufox(**kwargs).__aenter__()  # type: ignore

    # Create persistent context for session reuse
    ctx_kwargs: dict = {
        "viewport": viewport,
        "user_agent": user_agent,
    }
    if storage_state.exists():
        ctx_kwargs["storage_state"] = str(storage_state)
    if proxy_cfg:
        ctx_kwargs["proxy"] = proxy_cfg  # type: ignore

    context = await browser.new_context(**ctx_kwargs)

    # Inject WebRTC leak prevention if using a proxy
    if proxy:
        await context.add_init_script("""
            // Block WebRTC to prevent real IP leakage behind proxy
            Object.defineProperty(navigator, 'mediaDevices', {
                get: () => ({ getUserMedia: () => Promise.reject(new Error('Not allowed')) })
            });
        """)

    logger.info(f"[stealth] Launched Camoufox (headless={headless}, geoip=True, humanize=True)")
    return browser, context


async def _save_camoufox_state(context) -> None:
    """Persist cookies and storage for session continuity."""
    try:
        state_path = _get_state_path()
        storage_state_path = state_path / "camoufox_state.json"
        await context.storage_state(path=str(storage_state_path))
        logger.debug("[stealth] Browser state saved.")
    except Exception as e:
        logger.warning(f"[stealth] Could not save browser state: {e}")


# ─────────────────────────────────────────────
# Tier 2: Patchright (fallback)
# ─────────────────────────────────────────────
async def _launch_patchright(
    headless: bool,
    proxy: str | None,
    viewport: dict,
    user_agent: str,
) -> tuple:
    """
    Launch a Patchright browser (patched Playwright Chromium).
    Patches: navigator.webdriver, CDP Runtime.enable leak, --enable-automation flag removal.
    Returns (browser, context).
    """
    from patchright.async_api import async_playwright  # type: ignore

    state_path = _get_state_path()
    storage_state = state_path / "patchright_state.json"

    playwright = await async_playwright().start()

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--disable-translate",
        f"--window-size={viewport['width']},{viewport['height']}",
    ]

    proxy_cfg = None
    if proxy:
        proxy_cfg = {"server": proxy}

    browser = await playwright.chromium.launch(
        headless=headless,
        args=launch_args,
        proxy=proxy_cfg,  # type: ignore
    )

    ctx_kwargs: dict = {
        "viewport": viewport,
        "user_agent": user_agent,
        "locale": "en-US",
        "timezone_id": "America/Chicago",
        "permissions": ["geolocation"],
        "java_script_enabled": True,
    }
    if storage_state.exists():
        ctx_kwargs["storage_state"] = str(storage_state)
    if proxy_cfg:
        ctx_kwargs["proxy"] = proxy_cfg  # type: ignore

    context = await browser.new_context(**ctx_kwargs)

    # Patch navigator.webdriver and common fingerprint leaks
    await context.add_init_script("""
        // Remove webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Fake permissions API
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );

        // Fake plugins array (non-empty like a real browser)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        // Fake language consistency
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });

        // Remove Chrome automation flags
        window.chrome = { runtime: {} };

        // WebRTC IP protection
        Object.defineProperty(navigator, 'mediaDevices', {
            get: () => ({ getUserMedia: () => Promise.reject(new Error('Not allowed')) })
        });
    """)

    logger.info(f"[stealth] Launched Patchright (headless={headless})")
    return browser, context


async def _save_patchright_state(context) -> None:
    try:
        state_path = _get_state_path()
        await context.storage_state(path=str(state_path / "patchright_state.json"))
        logger.debug("[stealth] Patchright state saved.")
    except Exception as e:
        logger.warning(f"[stealth] Could not save patchright state: {e}")


# ─────────────────────────────────────────────
# Tier 3: Vanilla Playwright (no stealth)
# ─────────────────────────────────────────────
async def _launch_vanilla(
    headless: bool,
    proxy: str | None,
    viewport: dict,
    user_agent: str,
) -> tuple:
    """Launch standard Playwright Chromium (no stealth). Only for local dev/testing."""
    from playwright.async_api import async_playwright  # type: ignore

    playwright = await async_playwright().start()
    proxy_cfg = {"server": proxy} if proxy else None
    browser = await playwright.chromium.launch(headless=headless, proxy=proxy_cfg)  # type: ignore
    context = await browser.new_context(
        viewport=viewport,
        user_agent=user_agent,
    )
    logger.warning("[stealth] Using VANILLA Playwright — no stealth active! Set STEALTH_TIER=patchright or camoufox.")
    return browser, context


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
async def create_stealth_browser(
    tier: str | None = None,
    headless: bool | None = None,
    proxy: str | None = None,
) -> tuple:
    """
    Create and return a stealth-configured (browser, context) pair.

    Args:
        tier:     "camoufox" | "patchright" | "none" | None (uses settings default)
        headless: True/False | None (uses settings default)
        proxy:    Proxy URL or None (uses settings default if set)

    Returns:
        (browser, context) — standard Playwright-compatible objects
    """
    from src.config import settings

    effective_tier = tier or getattr(settings, "stealth_tier", "camoufox")
    effective_headless = headless if headless is not None else getattr(settings, "stealth_headless", True)
    effective_proxy = proxy or getattr(settings, "stealth_proxy", None) or None

    ua = _get_random_ua()
    viewport = _get_random_viewport()

    logger.info(f"[stealth] Creating browser: tier={effective_tier}, headless={effective_headless}, proxy={'set' if effective_proxy else 'none'}")

    if effective_tier == "camoufox":
        try:
            return await _launch_camoufox(effective_headless, effective_proxy, viewport, ua)
        except ImportError:
            logger.warning("[stealth] camoufox not installed. Falling back to patchright. Run: uv add camoufox[geoip]")
            effective_tier = "patchright"

    if effective_tier == "patchright":
        try:
            return await _launch_patchright(effective_headless, effective_proxy, viewport, ua)
        except ImportError:
            logger.warning("[stealth] patchright not installed. Falling back to vanilla playwright. Run: uv add patchright")
            effective_tier = "none"

    # Tier 3: no stealth
    return await _launch_vanilla(effective_headless, effective_proxy, viewport, ua)


async def save_stealth_state(context, tier: str | None = None) -> None:
    """Persist the browser session state (cookies, localStorage) for future reuse."""
    from src.config import settings
    effective_tier = tier or getattr(settings, "stealth_tier", "camoufox")

    if effective_tier == "patchright":
        await _save_patchright_state(context)
    else:
        await _save_camoufox_state(context)


@asynccontextmanager
async def stealth_browser(
    tier: str | None = None,
    headless: bool | None = None,
    proxy: str | None = None,
) -> AsyncGenerator[tuple, None]:
    """
    Async context manager that creates a stealth browser and saves state on exit.

    Usage:
        async with stealth_browser() as (browser, context):
            page = await context.new_page()
    """
    browser, context = await create_stealth_browser(tier=tier, headless=headless, proxy=proxy)
    try:
        yield browser, context
    finally:
        await save_stealth_state(context, tier=tier)
        try:
            await context.close()
            await browser.close()
        except Exception as e:
            logger.debug(f"[stealth] Browser close error (non-critical): {e}")


# ─────────────────────────────────────────────
# Behavioral helpers (for prompts and delays)
# ─────────────────────────────────────────────
def human_delay_instruction() -> str:
    """Return a prompt instruction snippet for human-like timing."""
    return (
        "IMPORTANT — act like a real human user:\n"
        "- Wait 0.5 to 1.5 seconds between each click or keystroke (randomize the wait time)\n"
        "- After navigating to a new page, pause 1-3 seconds before interacting\n"
        "- Scroll naturally before clicking on elements that are off-screen\n"
        "- Do NOT rush through fields — type at a natural pace\n"
    )
