"""
Tests for the stealth browser module.
These tests validate the stealth module without launching a real browser,
using mocks for the heavy external dependencies (camoufox, patchright).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────
# Unit: stealth utility helpers
# ─────────────────────────────────────────────
def test_random_ua_is_from_pool():
    """UA should always be one of the known real-browser strings."""
    from src.stealth import _get_random_ua, _USER_AGENTS
    for _ in range(20):
        ua = _get_random_ua()
        assert ua in _USER_AGENTS
        assert "HeadlessChrome" not in ua
        assert "Playwright" not in ua
        assert "bot" not in ua.lower()


def test_random_viewport_is_sane():
    """Viewport should be a common desktop resolution."""
    from src.stealth import _get_random_viewport, _VIEWPORTS
    vp = _get_random_viewport()
    assert vp in _VIEWPORTS
    assert vp["width"] >= 1280
    assert vp["height"] >= 720


def test_human_delay_instruction_not_empty():
    """Timing instructions should be a non-empty string."""
    from src.stealth import human_delay_instruction
    result = human_delay_instruction()
    assert isinstance(result, str)
    assert len(result) > 50
    assert "wait" in result.lower() or "pause" in result.lower()


def test_state_dir_created():
    """_get_state_path() should create the directory if it doesn't exist."""
    import shutil
    from src.stealth import _get_state_path, _STATE_DIR
    # Temporarily rename if exists
    backup = None
    if _STATE_DIR.exists():
        backup = _STATE_DIR.with_suffix(".bak")
        _STATE_DIR.rename(backup)
    try:
        path = _get_state_path()
        assert path.exists()
        assert path.is_dir()
    finally:
        if _STATE_DIR.exists():
            shutil.rmtree(_STATE_DIR)
        if backup and backup.exists():
            backup.rename(_STATE_DIR)


# ─────────────────────────────────────────────
# Unit: fallback chain
# ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_camoufox_unavailable_falls_back_to_patchright():
    """If camoufox isn't installed, create_stealth_browser should fall back to patchright."""
    mock_browser = MagicMock()
    mock_context = MagicMock()

    with patch("src.stealth._launch_camoufox", side_effect=ImportError("camoufox not installed")):
        with patch("src.stealth._launch_patchright", new=AsyncMock(return_value=(mock_browser, mock_context))):
            from src.stealth import create_stealth_browser
            browser, context = await create_stealth_browser(tier="camoufox", headless=True, proxy=None)
            assert browser == mock_browser


@pytest.mark.asyncio
async def test_patchright_unavailable_falls_back_to_vanilla():
    """If both camoufox and patchright are unavailable, fall back to vanilla playwright."""
    mock_browser = MagicMock()
    mock_context = MagicMock()

    with patch("src.stealth._launch_camoufox", side_effect=ImportError("camoufox not installed")):
        with patch("src.stealth._launch_patchright", side_effect=ImportError("patchright not installed")):
            with patch("src.stealth._launch_vanilla", new=AsyncMock(return_value=(mock_browser, mock_context))):
                from src.stealth import create_stealth_browser
                browser, context = await create_stealth_browser(tier="camoufox", headless=True, proxy=None)
                assert browser == mock_browser



# ─────────────────────────────────────────────
# Unit: config integration
# ─────────────────────────────────────────────
def test_settings_has_stealth_fields():
    """Settings class should expose the three new stealth fields with correct defaults."""
    from src.config import settings
    assert hasattr(settings, "stealth_tier")
    assert hasattr(settings, "stealth_proxy")
    assert hasattr(settings, "stealth_headless")
    assert settings.stealth_tier in ("camoufox", "patchright", "none")
    assert isinstance(settings.stealth_headless, bool)
