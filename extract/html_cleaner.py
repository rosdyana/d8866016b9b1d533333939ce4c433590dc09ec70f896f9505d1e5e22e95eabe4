from __future__ import annotations

from html.parser import HTMLParser

_STRIP_TAGS = {"script", "style", "noscript", "template"}


class _TagStrippingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._skip_depth = 0
        self._out: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _STRIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0:
            self._out.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _STRIP_TAGS:
            return
        if self._skip_depth == 0:
            self._out.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in _STRIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth == 0:
            self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth == 0:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth == 0:
            self._out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        return

    def get_clean_html(self) -> str:
        return "".join(self._out)


def clean_html(html: str) -> str:
    """Strip script/style/noscript/template tags. Returns HTML, not text."""
    parser = _TagStrippingParser()
    parser.feed(html)
    parser.close()
    return parser.get_clean_html()
