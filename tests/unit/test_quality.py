from pipeline.quality import is_good_enough

REAL_PAGE = "<html><body>" + ("<p>Real article content here. </p>" * 30) + "</body></html>"


def test_passes_for_normal_content_page():
    verdict = is_good_enough(200, REAL_PAGE)
    assert verdict.passed is True


def test_fails_for_blocked_status_code():
    verdict = is_good_enough(403, REAL_PAGE)
    assert verdict.passed is False
    assert verdict.reason == "blocked_status_403"


def test_fails_for_cloudflare_challenge_marker():
    filler = "Please wait while we verify your connection. " * 6
    html = f"<html><body>Checking your browser before accessing example.com. {filler}</body></html>"
    verdict = is_good_enough(200, html)
    assert verdict.passed is False
    assert verdict.reason.startswith("challenge_marker")


def test_long_article_mentioning_captcha_is_not_a_false_positive():
    # Regression: a real article *about* scraping/anti-bot techniques will
    # legitimately use words like "captcha" - that must not trip the
    # short-challenge-page heuristic once there's substantial real content.
    paragraph = "This is a real paragraph of article text discussing web scraping. " * 60
    html = f"<html><body><article>{paragraph} Sites sometimes use a captcha to deter bots.</article></body></html>"
    verdict = is_good_enough(200, html)
    assert verdict.passed is True


def test_fails_for_js_shell_with_no_text():
    html = '<html><body><div id="root"></div><script src="bundle.js"></script></body></html>'
    verdict = is_good_enough(200, html)
    assert verdict.passed is False


def test_fails_for_js_shell_with_large_inline_data_script():
    # Regression: quotes.toscrape.com/js/ embeds its real content as a
    # `var data = [...]` JSON blob inside an inline <script>, which a naive
    # tag-stripping regex counts as "visible text" even though a user (and
    # trafilatura) would see none of it - this must still escalate.
    inline_json = '{"quotes": [' + ('{"text": "filler quote text here."},' * 40) + "]}"
    html = (
        "<html><body><h1>App</h1>"
        f"<script>var data = {inline_json};</script>"
        "</body></html>"
    )
    verdict = is_good_enough(200, html)
    assert verdict.passed is False


def test_fails_for_error_status():
    verdict = is_good_enough(500, REAL_PAGE)
    assert verdict.passed is False
    assert verdict.reason == "error_status_500"
