"""'Is this response good enough to extract, or should we escalate?'

Deliberately conservative: a stage that returns 200 with a JS-shell or a
bot-challenge page must NOT be treated as success, or the pipeline will
"succeed" with junk instead of escalating to a stage that can actually
render/bypass the block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from extract.html_cleaner import clean_html

_BLOCK_STATUS_CODES = {401, 403, 429, 503}

_CHALLENGE_MARKERS = (
    "checking your browser",
    "cf-browser-verification",
    "cf-challenge",
    "just a moment",
    "enable javascript to continue",
    "please enable javascript",
    "captcha",
    "attention required",
    "ddos protection by",
    # reddit.com serves this interstitial with HTTP 200 and ~270 chars of
    # visible text, so nothing else here catches it: not the status check,
    # not _MIN_TEXT_LENGTH, and not the unrendered-shell check (its 167KB of
    # inline CSS/SVG lands just under _UNRENDERED_MIN_HTML_LENGTH). Without
    # this marker Stage 1 "succeeds" on the challenge page and the pipeline
    # never escalates to the browser stage that actually gets the content.
    "prove your humanity",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# There used to be a visible-text-to-HTML ratio check here as a second
# JS-shell signal. It was removed after measuring it against both real
# pages and real shells: it tracks how much JavaScript a page ships, not
# whether the page has content. An OEM product catalogue (a 1.2MB Lenovo
# listing whose products live in a 638KB inline script) scored 0.0030
# while quotes.toscrape.com/js/ - an actual empty shell - scored 0.0165,
# so the check fired *harder* on the real page than on the shell it was
# meant to catch. Counting text after clean_html() strips <script> is
# what actually catches those shells, via _MIN_TEXT_LENGTH below.
_MIN_TEXT_LENGTH = 200

# A megabyte of HTML that renders under this much text is a shell whose
# content hasn't been built yet - a page that is genuinely this short is
# also a *small* page. Measured across 16 real pages: every rendered page
# cleared 1,700 characters, while lenovo.com's Taiwan product pages ship
# 788KB of HTML around 413 characters of text and their specs only appear
# once a browser runs the page. Without this, Stage 1 "wins" with the shell
# and the browser stages that could render it never run.
_UNRENDERED_MAX_TEXT_LENGTH = 1000
_UNRENDERED_MIN_HTML_LENGTH = 200_000

# Real bot-challenge/interstitial pages are short. A long article that
# happens to mention "captcha" or "enable javascript" in passing (e.g. an
# article about web scraping) must not be flagged just for using the word,
# so marker matching only applies below this length.
_MARKER_CHECK_MAX_TEXT_LEN = 3000


@dataclass(frozen=True)
class QualityVerdict:
    passed: bool
    reason: str


def _visible_text(html: str) -> str:
    # Script/style/JSON blobs (e.g. a SPA's embedded data payload) are not
    # visible text - counting them made JS-shell pages look content-rich
    # enough to wrongly pass, when a real user (and trafilatura) would see
    # nothing there at all.
    without_script_style = clean_html(html)
    text = _TAG_RE.sub(" ", without_script_style)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _visible_text_len(html: str) -> int:
    return len(_visible_text(html))


def is_good_enough(status_code: int, html: str) -> QualityVerdict:
    if status_code in _BLOCK_STATUS_CODES:
        return QualityVerdict(False, f"blocked_status_{status_code}")
    if status_code >= 400:
        return QualityVerdict(False, f"error_status_{status_code}")

    text = _visible_text(html)
    if len(text) < _MIN_TEXT_LENGTH:
        return QualityVerdict(False, "text_too_short")

    if len(text) < _UNRENDERED_MAX_TEXT_LENGTH and len(html) > _UNRENDERED_MIN_HTML_LENGTH:
        return QualityVerdict(False, "unrendered_shell")

    if len(text) < _MARKER_CHECK_MAX_TEXT_LEN:
        # Match markers against visible text, never raw HTML. A real
        # challenge page says "checking your browser" where a user can read
        # it; script source says things like
        # `RECAPTCHA:"https://www.recaptcha.net/..."` as a config path.
        # lenovo.com product pages carry exactly that string and were being
        # rejected as challenges after a perfectly good 200 fetch, costing
        # a full browser launch per product page.
        lowered = text.lower()
        for marker in _CHALLENGE_MARKERS:
            if marker in lowered:
                return QualityVerdict(False, f"challenge_marker:{marker}")

    return QualityVerdict(True, "ok")
