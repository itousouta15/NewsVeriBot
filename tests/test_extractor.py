import ipaddress

import pytest

from newsveribot.extractor import UnsafeUrlError, extract_text_from_html, validate_public_url


async def _public_resolver(_: str, __: int) -> set[ipaddress.IPv4Address]:
    return {ipaddress.IPv4Address("93.184.216.34")}


async def _private_resolver(_: str, __: int) -> set[ipaddress.IPv4Address]:
    return {ipaddress.IPv4Address("127.0.0.1")}


async def test_validate_public_url_accepts_public_https() -> None:
    result = await validate_public_url("https://example.com/news", _public_resolver)
    assert result == "https://example.com/news"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@example.com/article",
        "http://localhost/admin",
    ],
)
async def test_validate_public_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_public_url(url, _private_resolver)


def test_extract_text_prefers_article_and_removes_scripts() -> None:
    html = """
    <html><head><title> 測試新聞 </title></head><body>
      <nav>選單不應出現</nav>
      <article><h1>主要標題</h1><p>這是新聞正文。</p><script>惡意內容</script></article>
      <footer>頁尾不應出現</footer>
    </body></html>
    """
    text, title = extract_text_from_html(html)
    assert title == "測試新聞"
    assert text == "主要標題\n這是新聞正文。"
