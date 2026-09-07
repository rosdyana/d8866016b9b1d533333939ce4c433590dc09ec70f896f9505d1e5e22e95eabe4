"""Real headless-Firefox tests for pipeline.browser.lazyload - deterministic
because the "site" is a static fixture we control, unlike testing against a
live Lenovo product page whose lazyload payload can change at any time.
"""

import time

import pytest

from pipeline.browser.lazyload import has_unresolved_lazy_content, scroll_full_page

# Real IntersectionObserver scripts, not a static shell - a fixture with no
# script would never populate the placeholder on scroll and the test would
# only prove scrollTo was called, not that scrolling actually triggers
# lazy content the way it does on the real site.
RESOLVES_ON_SCROLL_INTO_VIEW = """
<html><body style="margin:0">
  <div style="height: 2000px;">spacer</div>
  <div class="comp_lazyload" tag="ofp-fe-techSpecs" file="_cms_lazyload_include_/abc/"></div>
  <script>
    var target = document.querySelector('.comp_lazyload');
    new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          target.innerHTML = '<h2>Tech Specs</h2><p>16GB RAM</p>';
        }
      });
    }).observe(target);
  </script>
</body></html>
"""

# A second placeholder is only added to the DOM once the first resolves,
# growing scrollHeight after the sweep already visited that position -
# proves the re-measurement inside the scroll loop reaches it.
SECOND_FRAGMENT_APPEARS_AFTER_FIRST_RESOLVES = """
<html><body style="margin:0">
  <div style="height: 1500px;">spacer</div>
  <div class="comp_lazyload" id="first" tag="ofp-fe-techSpecs" file="_cms_lazyload_include_/abc/"></div>
  <script>
    var first = document.getElementById('first');
    new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) return;
        first.innerHTML = '<p>tech specs resolved</p>';

        var spacer = document.createElement('div');
        spacer.style.height = '1500px';
        document.body.appendChild(spacer);

        var second = document.createElement('div');
        second.className = 'comp_lazyload';
        second.setAttribute('tag', 'ofp-fe-reviews');
        second.setAttribute('file', '_cms_lazyload_include_/xyz/');
        document.body.appendChild(second);

        new IntersectionObserver(function(entries2) {
          entries2.forEach(function(entry2) {
            if (entry2.isIntersecting) {
              second.innerHTML = '<p>reviews resolved</p>';
            }
          });
        }).observe(second);
      });
    }).observe(first);
  </script>
</body></html>
"""

NO_SCROLLABLE_CONTENT = """
<html><body><main><h1>Short page</h1><p>Nothing below the fold.</p></main></body></html>
"""

# Every scroll grows the page further, simulating a page that never
# stabilizes (e.g. an infinite-scroll feed) - scroll_full_page must still
# return once its own budget elapses rather than chasing scrollHeight forever.
INFINITE_SCROLL = """
<html><body style="margin:0">
  <div style="height: 2000px;">spacer</div>
  <script>
    window.addEventListener('scroll', function() {
      var more = document.createElement('div');
      more.style.height = '2000px';
      document.body.appendChild(more);
    });
  </script>
</body></html>
"""


@pytest.mark.asyncio
async def test_scroll_resolves_lazyload_placeholder_on_intersection(playwright_page):
    await playwright_page.set_content(RESOLVES_ON_SCROLL_INTO_VIEW)
    assert has_unresolved_lazy_content(await playwright_page.content()) is True

    await scroll_full_page(playwright_page, budget_seconds=5.0)

    assert has_unresolved_lazy_content(await playwright_page.content()) is False


@pytest.mark.asyncio
async def test_scroll_reaches_fragment_that_appears_after_an_earlier_one_resolves(
    playwright_page,
):
    await playwright_page.set_content(SECOND_FRAGMENT_APPEARS_AFTER_FIRST_RESOLVES)

    await scroll_full_page(playwright_page, budget_seconds=5.0)

    assert has_unresolved_lazy_content(await playwright_page.content()) is False


@pytest.mark.asyncio
async def test_non_scrollable_page_returns_quickly(playwright_page):
    await playwright_page.set_content(NO_SCROLLABLE_CONTENT)

    start = time.monotonic()
    await scroll_full_page(playwright_page, budget_seconds=5.0)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_ever_growing_page_stops_at_its_own_budget(playwright_page):
    await playwright_page.set_content(INFINITE_SCROLL)

    start = time.monotonic()
    await scroll_full_page(playwright_page, budget_seconds=1.5)
    elapsed = time.monotonic() - start

    assert elapsed < 3.0
