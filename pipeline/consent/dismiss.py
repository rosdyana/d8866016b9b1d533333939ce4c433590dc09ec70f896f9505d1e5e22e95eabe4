"""Best-effort cookie-consent/popup dismissal.

Layered, cheapest-and-most-specific first:
  1. native browser dialogs (alert/confirm/prompt) - auto-dismissed via
     attach_dialog_autodismiss(), which the caller installs on the page
  2. known CMP button selectors (OneTrust, Cookiebot, Didomi, Quantcast,
     TrustArc, cookieconsent.js, ...)
  3. generic multilingual "Accept all / I agree / OK" text matching
  4. generic overlay removal - hides any element that looks like a modal
     covering most of the viewport, for popups no CMP-specific rule catches

None of this is guaranteed to work on every site - new CMPs and popup
designs appear constantly - so it degrades gracefully: a page that
couldn't be dismissed just gets extracted as-is, and a genuinely blocked
result still falls through to pipeline.quality's checks like any other
stage output.
"""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

_KNOWN_SELECTORS = (
    "#onetrust-accept-btn-handler",  # OneTrust
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot
    "#didomi-notice-agree-button",  # Didomi
    "button.qc-cmp2-summary-buttons > button[mode='primary']",  # Quantcast
    "#truste-consent-button",  # TrustArc
    ".cc-btn.cc-allow",  # cookieconsent.js
    ".cc-allow",
    "[id*='accept-all' i]",
    "[class*='accept-all' i]",
    "[data-testid*='accept' i]",
)

_CONSENT_TEXT_PATTERN = re.compile(
    r"^("
    r"accept all cookies?|accept all|accept cookies?|allow all|allow cookies?|"
    r"i agree|agree|got it|ok|okay|allow|i accept|"
    r"alle akzeptieren|akzeptieren|"
    r"tout accepter|j'accepte|accepter|"
    r"accetta tutto|accetta|"
    r"aceptar todo|aceptar|"
    r"aceitar tudo|aceitar"
    r")$",
    re.IGNORECASE,
)

_SELECTOR_TIMEOUT_MS = 400
_TEXT_MATCH_TIMEOUT_MS = 800


def attach_dialog_autodismiss(page: Page) -> None:
    """Auto-dismiss native browser dialogs (alert/confirm/prompt/
    beforeunload) - these block all page interaction if left unhandled,
    and are a different mechanism entirely from HTML cookie banners
    (which are just DOM elements a selector/text click can close)."""

    def _handle_dialog(dialog) -> None:
        asyncio.create_task(dialog.dismiss())

    page.on("dialog", _handle_dialog)


async def dismiss_consent_and_overlays(page: Page) -> str:
    """Runs the full layered dismissal. Returns which mechanism fired, or
    "" if nothing matched - useful to log for tuning selector coverage."""
    mechanism = await _click_known_selectors(page)
    if mechanism:
        return mechanism
    mechanism = await _click_by_text(page)
    if mechanism:
        return mechanism
    hidden_count = await _hide_blocking_overlays(page)
    return f"overlay_hide:{hidden_count}" if hidden_count else ""


async def _click_known_selectors(page: Page) -> str:
    for selector in _KNOWN_SELECTORS:
        try:
            await page.locator(selector).first.click(timeout=_SELECTOR_TIMEOUT_MS)
            return f"selector:{selector}"
        except PlaywrightError:
            continue
    return ""


async def _click_by_text(page: Page) -> str:
    try:
        await page.get_by_role("button", name=_CONSENT_TEXT_PATTERN).first.click(
            timeout=_TEXT_MATCH_TIMEOUT_MS
        )
        return "text_match:button"
    except PlaywrightError:
        pass
    try:
        await page.get_by_role("link", name=_CONSENT_TEXT_PATTERN).first.click(
            timeout=_TEXT_MATCH_TIMEOUT_MS
        )
        return "text_match:link"
    except PlaywrightError:
        pass
    return ""


_OVERLAY_HIDE_SCRIPT = """
() => {
    const viewportArea = window.innerWidth * window.innerHeight;
    let hidden = 0;
    for (const el of document.querySelectorAll('body *')) {
        const style = getComputedStyle(el);
        if (style.position !== 'fixed' && style.position !== 'sticky') continue;
        const zIndex = parseInt(style.zIndex, 10) || 0;
        if (zIndex < 999) continue;
        const rect = el.getBoundingClientRect();
        const area = rect.width * rect.height;
        if (area < viewportArea * 0.4) continue;
        el.style.setProperty('display', 'none', 'important');
        hidden += 1;
    }
    document.body.style.overflow = 'auto';
    return hidden;
}
"""


async def _hide_blocking_overlays(page) -> int:
    """Generic fallback for popups no CMP-specific rule caught: hide any
    fixed/sticky, high z-index element covering a large share of the
    viewport (typical of modal backdrops/newsletter popups)."""
    try:
        return await page.evaluate(_OVERLAY_HIDE_SCRIPT)
    except PlaywrightError:
        return 0
