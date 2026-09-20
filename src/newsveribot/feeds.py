import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import Element, ParseError

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError

from newsveribot.dataset import ArticleRecord, DatasetError
from newsveribot.extractor import (
    REDIRECT_STATUSES,
    USER_AGENT,
    Resolver,
    resolve_host,
    validate_public_url,
)

FEED_CONTENT_TYPES = {
    "application/atom+xml",
    "application/rss+xml",
    "application/xml",
    "text/xml",
}
TRACKING_PARAMETERS = {"at_campaign", "at_medium", "fbclid", "gclid"}
SENTENCE_ENDINGS = ("。", "！", "？", ".", "!", "?")


class FeedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1)
    feed_url: AnyHttpUrl
    rights_note: str = Field(min_length=1)
    max_items: int = Field(default=20, ge=1, le=100)
    include_summary: bool = True


class FeedFailure(BaseModel):
    source_id: str
    message: str


class FeedCollectionReport(BaseModel):
    collected_at: datetime
    sources_requested: int
    sources_succeeded: int
    articles: int
    duplicates: int
    source_articles: dict[str, int]
    failures: list[FeedFailure]


@dataclass(frozen=True, slots=True)
class ParsedFeedItem:
    title: str
    summary: str
    link: str
    stable_id: str
    published_at: datetime | None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _child_text(element: Element, *names: str) -> str:
    accepted = set(names)
    for child in element:
        if _local_name(child.tag) in accepted and child.text:
            return child.text.strip()
    return ""


def _atom_link(element: Element) -> str:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        relation = child.attrib.get("rel", "alternate")
        href = child.attrib.get("href", "")
        if relation == "alternate" and href:
            return href.strip()
    return ""


def _clean_fragment(fragment: str) -> str:
    soup = BeautifulSoup(fragment, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    parts: list[str] = []
    candidates = soup.find_all(["p", "li"]) or [soup]
    for candidate in candidates:
        text = " ".join(candidate.get_text(" ", strip=True).split())
        if not text or "這篇文章最早發佈於" in text:
            continue
        if re.search(r"(?:\.{3,}|…+)$", text):
            continue
        parts.append(text)
    return "\n".join(dict.fromkeys(part for part in parts if part))


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_article_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS and not key.lower().startswith("utm_")
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _ensure_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    if cleaned and not cleaned.endswith(SENTENCE_ENDINGS):
        return f"{cleaned}。"
    return cleaned


def parse_feed(content: bytes) -> list[ParsedFeedItem]:
    try:
        root = ElementTree.fromstring(content)
    except (ParseError, DefusedXmlException) as exc:
        raise DatasetError("RSS/Atom XML 格式無效") from exc

    items = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    parsed_items: list[ParsedFeedItem] = []
    for item in items:
        title = _clean_fragment(_child_text(item, "title"))
        summary = _clean_fragment(_child_text(item, "description", "summary", "content"))
        link = _child_text(item, "link") or _atom_link(item)
        stable_id = _child_text(item, "guid", "id") or link
        published = _child_text(item, "pubDate", "published", "updated")
        if not title or not link:
            continue
        parsed_items.append(
            ParsedFeedItem(
                title=title,
                summary=summary,
                link=normalize_article_url(link),
                stable_id=stable_id,
                published_at=_parse_date(published),
            )
        )
    return parsed_items


class FeedCollector:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_download_bytes: int,
        max_redirects: int,
        resolver: Resolver = resolve_host,
    ) -> None:
        self._client = client
        self._max_download_bytes = max_download_bytes
        self._max_redirects = max_redirects
        self._resolver = resolver

    async def _download(self, url: str) -> bytes:
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            await validate_public_url(current_url, self._resolver)
            try:
                async with self._client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": USER_AGENT, "Accept": ", ".join(FEED_CONTENT_TYPES)},
                ) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise DatasetError("RSS 重新導向缺少 Location")
                        if redirect_count >= self._max_redirects:
                            raise DatasetError("RSS 重新導向次數過多")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in FEED_CONTENT_TYPES:
                        raise DatasetError(f"RSS 回應類型不支援：{content_type or 'unknown'}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_download_bytes:
                            raise DatasetError("RSS 超過下載大小限制")
                    return bytes(body)
            except httpx.HTTPError as exc:
                raise DatasetError("RSS 下載失敗") from exc
        raise DatasetError("RSS 重新導向次數過多")

    async def collect(
        self,
        sources: list[FeedSource],
    ) -> tuple[list[ArticleRecord], FeedCollectionReport]:
        if not sources:
            raise DatasetError("來源清單不可為空")
        source_ids = [source.source_id for source in sources]
        if len(source_ids) != len(set(source_ids)):
            raise DatasetError("來源清單包含重複 source_id")

        collected_at = datetime.now(UTC)
        articles: list[ArticleRecord] = []
        failures: list[FeedFailure] = []
        seen_hashes: set[str] = set()
        source_articles: Counter[str] = Counter()
        duplicates = 0
        succeeded = 0
        for source in sources:
            try:
                feed_items = parse_feed(await self._download(str(source.feed_url)))
            except DatasetError as exc:
                failures.append(FeedFailure(source_id=source.source_id, message=str(exc)))
                continue
            succeeded += 1
            for item in feed_items[: source.max_items]:
                title = _ensure_sentence(item.title)
                summary = _ensure_sentence(item.summary) if source.include_summary else ""
                text = "\n".join(part for part in (title, summary) if part)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                content_hash = sha256(text.encode()).hexdigest()
                if content_hash in seen_hashes:
                    duplicates += 1
                    continue
                seen_hashes.add(content_hash)
                article_id = (
                    f"{source.source_id}_{sha256(item.stable_id.encode()).hexdigest()[:12]}"
                )
                try:
                    articles.append(
                        ArticleRecord.model_validate(
                            {
                                "article_id": article_id,
                                "title": item.title,
                                "text": text,
                                "source_url": item.link,
                                "source_name": source.name,
                                "retrieved_at": collected_at,
                                "published_at": item.published_at,
                                "content_sha256": content_hash,
                                "rights_note": source.rights_note,
                            }
                        )
                    )
                    source_articles[source.source_id] += 1
                except ValidationError:
                    continue
        if not articles:
            raise DatasetError("所有 RSS 來源都沒有產生可用文章")
        articles.sort(key=lambda article: article.article_id)
        return articles, FeedCollectionReport(
            collected_at=collected_at,
            sources_requested=len(sources),
            sources_succeeded=succeeded,
            articles=len(articles),
            duplicates=duplicates,
            source_articles=dict(sorted(source_articles.items())),
            failures=failures,
        )
