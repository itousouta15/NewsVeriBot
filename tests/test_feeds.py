import ipaddress

import httpx

from newsveribot.feeds import FeedCollector, FeedSource, normalize_article_url, parse_feed

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title><![CDATA[政府宣布新政策]]></title>
    <description><![CDATA[<p>政策預計2026年上路。</p>]]></description>
    <link>https://example.com/news/1?utm_source=rss</link>
    <guid>news-1</guid>
    <pubDate>Sun, 20 Sep 2026 10:00:00 +0000</pubDate>
  </item>
  <item>
    <title>政府宣布新政策</title>
    <description>政策預計2026年上路。</description>
    <link>https://example.com/news/duplicate</link>
    <guid>news-duplicate</guid>
  </item>
</channel></rss>""".encode()

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>研究顯示風險下降</title>
    <summary>研究納入500名受試者。</summary>
    <link rel="alternate" href="https://example.com/atom/1" />
    <id>atom-1</id>
    <updated>2026-09-20T10:00:00Z</updated>
  </entry>
</feed>""".encode()


async def _public_resolver(_: str, __: int) -> set[ipaddress.IPv4Address]:
    return {ipaddress.IPv4Address("93.184.216.34")}


def test_parse_rss_and_atom() -> None:
    rss_items = parse_feed(RSS)
    atom_items = parse_feed(ATOM)
    assert rss_items[0].title == "政府宣布新政策"
    assert rss_items[0].published_at is not None
    assert atom_items[0].link == "https://example.com/atom/1"


def test_normalize_article_url_removes_tracking_and_fragment() -> None:
    result = normalize_article_url(
        "https://example.com/news?a=1&utm_source=rss&at_campaign=test#section"
    )
    assert result == "https://example.com/news?a=1"


def test_parse_feed_drops_truncated_summary() -> None:
    feed = """<rss><channel><item><title>完整標題</title>
    <description>內容在這裡截斷…</description><link>https://example.com/1</link></item>
    </channel></rss>""".encode()
    assert parse_feed(feed)[0].summary == ""


async def test_collector_deduplicates_content_and_records_hash() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/rss+xml"}, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = FeedCollector(
            client,
            max_download_bytes=100_000,
            max_redirects=2,
            resolver=_public_resolver,
        )
        articles, report = await collector.collect(
            [
                FeedSource(
                    source_id="example",
                    name="Example",
                    feed_url="https://example.com/feed.xml",
                    rights_note="測試 RSS",
                    max_items=10,
                )
            ]
        )

    assert len(articles) == 1
    assert report.duplicates == 1
    assert report.source_articles == {"example": 1}
    assert articles[0].content_sha256 is not None
    assert "utm_source" not in str(articles[0].source_url)
