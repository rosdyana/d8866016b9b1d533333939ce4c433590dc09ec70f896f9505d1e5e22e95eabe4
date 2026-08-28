"""Regression: an OEM product catalogue must not be judged a failed fetch.

These pages are enormous (1-2MB) because they inline their JavaScript, but
they carry real content. A visible-text-to-HTML ratio check used to reject
them - measured against pages fetched live on 2026-08-29, it failed 4 of 7
real target pages (hp.com/us-en/shop 0.0052, lenovo laptops 0.0030,
lenovo home 0.0078, acer laptops 0.0193) while `quotes.toscrape.com/js/` -
an actually-empty shell - scored 0.0165, higher than three of them. The
check tracked how much JavaScript a page ships, not whether it had content.
"""

from pipeline.quality import is_good_enough

# Proportions taken from the real lenovo.com/us/en/pc/laptops/ response:
# ~1.2MB of HTML, a ~638KB inline script, ~3.7k characters of visible text.
_PRODUCT_ROWS = "".join(
    f"<li><a href='/p/thinkpad-{i}'>ThinkPad model {i} — 14 inch Intel laptop</a>"
    f"<span>Starting at ${900 + i}.00</span></li>"
    for i in range(60)
)
_INLINE_BUNDLE = "<script>window.__DATA__=%s;</script>" % ('{"k":"' + "v" * 40000 + '"}')

CATALOGUE_PAGE = (
    f"<html><body><nav>Laptops Desktops Workstations Accessories</nav>"
    f"<ul>{_PRODUCT_ROWS}</ul>{_INLINE_BUNDLE}</body></html>"
)


def test_script_heavy_catalogue_page_passes():
    verdict = is_good_enough(200, CATALOGUE_PAGE)
    assert verdict.passed is True, verdict.reason


def test_catalogue_page_is_script_heavy_enough_to_have_tripped_the_old_check():
    # Guards the premise of the regression: if this fixture stopped being
    # script-heavy, the test above would pass for the wrong reason.
    assert len(CATALOGUE_PAGE) > 40_000
    assert CATALOGUE_PAGE.count("<script>") == 1


def test_empty_shell_with_big_inline_script_still_fails():
    # The case the removed check was credited with catching is caught by
    # the text-length floor instead, because clean_html() strips <script>
    # before the count. This must keep working.
    shell = f"<html><body><div id='root'></div>{_INLINE_BUNDLE}</body></html>"
    verdict = is_good_enough(200, shell)
    assert verdict.passed is False
    assert verdict.reason == "text_too_short"


def test_blocked_status_still_wins_over_good_content():
    assert is_good_enough(403, CATALOGUE_PAGE).passed is False


def test_captcha_word_inside_script_source_is_not_a_challenge():
    # Regression: lenovo.com product pages inline a JS config containing
    # RECAPTCHA:"https://www.recaptcha.net/...". Matching challenge markers
    # against raw HTML saw "captcha" there and rejected a clean HTTP 200
    # fetch as a bot challenge, escalating every product page to a browser.
    body = "<p>ThinkPad L13 Gen 5 laptop specifications and pricing. </p>" * 8
    html = (
        f"<html><body>{body}"
        '<script>window.CFG={JSPATH:{RECAPTCHA:"https://www.recaptcha.net/recaptcha/api.js"}};</script>'
        "</body></html>"
    )
    verdict = is_good_enough(200, html)
    assert verdict.passed is True, verdict.reason


def test_challenge_marker_in_visible_text_still_fails():
    # The counterpart: a real interstitial says it where a user can read it.
    html = "<html><body><h1>Just a moment...</h1><p>Checking your browser before access. </p></body></html>" + (
        "<p>Please wait. </p>" * 12
    )
    verdict = is_good_enough(200, html)
    assert verdict.passed is False
    assert verdict.reason.startswith("challenge_marker")


def test_large_document_rendering_almost_no_text_escalates():
    # Regression: lenovo.com's Taiwan product pages return 788KB of HTML
    # containing ~413 characters of visible text — the specs only exist
    # inside <script> until a browser runs the page. That cleared the
    # 200-character floor, so Stage 1 "won" with a shell and the browser
    # stages that could actually render it never ran.
    shell = (
        "<html><body><nav>" + ("Store Support Account Wishlist " * 12) + "</nav>"
        "<div id='pdp-root'></div>"
        "<script>window.__PRODUCT__=" + ('{"spec":"' + "x" * 400000 + '"}') + ";</script>"
        "</body></html>"
    )
    verdict = is_good_enough(200, shell)
    assert verdict.passed is False
    assert verdict.reason == "unrendered_shell"


def test_small_page_with_modest_text_is_not_an_unrendered_shell():
    # The counterpart: a genuinely short page is also a *small* page, and
    # must not be escalated just for being brief.
    page = "<html><body><article>" + ("<p>Short but complete post. </p>" * 12) + "</article></body></html>"
    assert is_good_enough(200, page).passed is True
