"""Real headless-Chromium tests for pipeline.consent.dismiss - deterministic
because the "site" is a static fixture we control, unlike testing against a
live cookie banner whose appearance depends on the visitor's geolocation.
"""

import pytest

from pipeline.consent.dismiss import dismiss_consent_and_overlays

# Real CMP scripts remove/hide the banner in response to the click; these
# fixtures include a minimal inline handler to simulate that, since a
# static fixture with no script would never change state on click and the
# test would only prove the button was clicked, not that dismissal worked.
ONETRUST_BANNER = """
<html><body>
  <div id="onetrust-banner-sdk">
    <div id="onetrust-button-group">
      <button id="onetrust-accept-btn-handler"
              onclick="document.getElementById('onetrust-banner-sdk').remove()">
        Accept All Cookies
      </button>
    </div>
  </div>
  <main><h1>Real page content</h1><p>Article text goes here.</p></main>
</body></html>
"""

GENERIC_TEXT_BANNER = """
<html><body>
  <div class="cookie-notice">
    <p>We use cookies.</p>
    <button onclick="document.querySelector('.cookie-notice').remove()">Accept all</button>
  </div>
  <main><h1>Real page content</h1></main>
</body></html>
"""

BLOCKING_OVERLAY = """
<html><body>
  <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:9999;background:white;">
    <p>Newsletter signup modal with no recognizable close button text</p>
  </div>
  <main><h1>Real page content</h1></main>
</body></html>
"""

NO_POPUP_PAGE = """
<html><body><main><h1>Just a normal page</h1><p>Nothing to dismiss here.</p></main></body></html>
"""


@pytest.mark.asyncio
async def test_dismisses_known_onetrust_selector(playwright_page):
    await playwright_page.set_content(ONETRUST_BANNER)
    mechanism = await dismiss_consent_and_overlays(playwright_page)
    assert mechanism.startswith("selector:")
    assert await playwright_page.locator("#onetrust-banner-sdk").count() == 0 or not (
        await playwright_page.locator("#onetrust-banner-sdk").is_visible()
    )


@pytest.mark.asyncio
async def test_dismisses_via_generic_text_match(playwright_page):
    await playwright_page.set_content(GENERIC_TEXT_BANNER)
    mechanism = await dismiss_consent_and_overlays(playwright_page)
    assert mechanism.startswith("text_match:")
    assert not await playwright_page.locator(".cookie-notice").is_visible()


@pytest.mark.asyncio
async def test_hides_blocking_overlay_with_no_matching_button(playwright_page):
    await playwright_page.set_content(BLOCKING_OVERLAY)
    mechanism = await dismiss_consent_and_overlays(playwright_page)
    assert mechanism.startswith("overlay_hide:")
    main_visible = await playwright_page.locator("main h1").is_visible()
    assert main_visible is True


@pytest.mark.asyncio
async def test_no_popup_page_is_a_safe_noop(playwright_page):
    await playwright_page.set_content(NO_POPUP_PAGE)
    mechanism = await dismiss_consent_and_overlays(playwright_page)
    assert mechanism == ""
    assert await playwright_page.locator("main h1").is_visible()
