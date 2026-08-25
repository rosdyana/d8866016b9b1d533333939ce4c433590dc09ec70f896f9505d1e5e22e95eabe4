import pytest
from playwright.async_api import async_playwright


@pytest.fixture
async def playwright_page():
    """A real headless Chromium page for integration tests. We don't use
    pytest-playwright's fixtures because they're sync-API-based and this
    codebase is async throughout - this small fixture keeps everything on
    the same async Playwright API our production code actually uses."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            yield page
        finally:
            await browser.close()
