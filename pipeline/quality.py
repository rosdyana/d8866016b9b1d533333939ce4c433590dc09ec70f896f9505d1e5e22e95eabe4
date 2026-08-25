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
)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Below this ratio of visible text to raw HTML, a page is almost certainly
# a JS-rendered shell (empty <div id="root">/<div id="app"> and little else).
_MIN_TEXT_TO_HTML_RATIO = 0.02
_MIN_TEXT_LENGTH = 200

# Real bot-challenge/interstitial pages are short. A long article that
# happens to mention "captcha" or "enable javascript" in passing (e.g. an
# article about web scraping) must not be flagged just for using the word,
# so marker matching only applies below this length.
_MARKER_CHECK_MAX_TEXT_LEN = 3000


@dataclass(frozen=True)
class QualityVerdict:
    passed: bool
    reason: str


def _visible_text_len(html: str) -> int:
    # Script/style/JSON blobs (e.g. a SPA's embedded data payload) are not
    # visible text - counting them made JS-shell pages look content-rich
    # enough to wrongly pass, when a real user (and trafilatura) would see
    # nothing there at all.
    without_script_style = clean_html(html)
    text = _TAG_RE.sub(" ", without_script_style)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return len(text)


def is_good_enough(status_code: int, html: str) -> QualityVerdict:
    if status_code in _BLOCK_STATUS_CODES:
        return QualityVerdict(False, f"blocked_status_{status_code}")
    if status_code >= 400:
        return QualityVerdict(False, f"error_status_{status_code}")

    text_len = _visible_text_len(html)
    if text_len < _MIN_TEXT_LENGTH:
        return QualityVerdict(False, "text_too_short")

    if text_len < _MARKER_CHECK_MAX_TEXT_LEN:
        lowered = html.lower()
        for marker in _CHALLENGE_MARKERS:
            if marker in lowered:
                return QualityVerdict(False, f"challenge_marker:{marker}")

    html_len = max(len(html), 1)
    if text_len / html_len < _MIN_TEXT_TO_HTML_RATIO:
        return QualityVerdict(False, "low_text_to_html_ratio")

    return QualityVerdict(True, "ok")
