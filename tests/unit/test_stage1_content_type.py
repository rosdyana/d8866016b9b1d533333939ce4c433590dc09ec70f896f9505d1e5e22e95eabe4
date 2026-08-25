import httpx
import pytest
import respx

from common.errors import UnsupportedContentType
from pipeline.stages.stage1_http import Stage1Http


@pytest.mark.asyncio
async def test_raises_on_pdf_content_type():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/file.pdf").mock(
                return_value=httpx.Response(
                    200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
                )
            )
            stage = Stage1Http(client, user_agent="ccscraper-test")
            with pytest.raises(UnsupportedContentType):
                await stage.fetch("http://example.com/file.pdf")


@pytest.mark.asyncio
async def test_allows_html_with_charset_suffix():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/page").mock(
                return_value=httpx.Response(
                    200,
                    text="<html><body>hi</body></html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            )
            stage = Stage1Http(client, user_agent="ccscraper-test")
            result = await stage.fetch("http://example.com/page")
            assert "<html>" in result.html


@pytest.mark.asyncio
async def test_allows_missing_content_type_header():
    # httpx.Response(text=...) auto-adds a text/plain content-type unless
    # given raw bytes via content=, which is what actually simulates a
    # response with no Content-Type header at all.
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/page").mock(
                return_value=httpx.Response(200, content=b"<html><body>hi</body></html>")
            )
            stage = Stage1Http(client, user_agent="ccscraper-test")
            result = await stage.fetch("http://example.com/page")
            assert "<html>" in result.html
