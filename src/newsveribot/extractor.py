import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[set[IpAddress]]]

ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
USER_AGENT = "NewsVeriBot/0.1 (+https://github.com/itousouta15/NewsVeriBot)"


class ExtractionError(ValueError):
    """The remote document could not be safely extracted."""


class UnsafeUrlError(ExtractionError):
    """The requested URL may access a non-public network resource."""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    url: str
    text: str
    title: str | None
    truncated: bool


def _resolve_sync(hostname: str, port: int) -> set[IpAddress]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ExtractionError("無法解析網址的主機名稱") from exc

    addresses: set[IpAddress] = set()
    for record in records:
        raw_address = str(record[4][0])
        try:
            addresses.add(ipaddress.ip_address(raw_address.split("%", maxsplit=1)[0]))
        except ValueError as exc:
            raise ExtractionError("主機名稱解析結果不是有效 IP") from exc
    return addresses


async def resolve_host(hostname: str, port: int) -> set[IpAddress]:
    return await asyncio.to_thread(_resolve_sync, hostname, port)


def _is_public_address(address: IpAddress) -> bool:
    return address.is_global


async def validate_public_url(url: str, resolver: Resolver = resolve_host) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("網址格式無效") from exc

    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("僅接受 HTTP 或 HTTPS 網址")
    if not parsed.hostname:
        raise UnsafeUrlError("網址缺少主機名稱")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("網址不可包含帳號或密碼")

    addresses = await resolver(parsed.hostname, port)
    if not addresses:
        raise UnsafeUrlError("主機名稱沒有可用的 IP")
    if any(not _is_public_address(address) for address in addresses):
        raise UnsafeUrlError("網址指向私有或保留網路")
    return url


def extract_text_from_html(html: str) -> tuple[str, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title = None
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split()) or None

    for element in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
        element.decompose()

    container = soup.select_one("article, main") or soup.body or soup
    paragraphs: list[str] = []
    seen: set[str] = set()
    for element in container.find_all(["h1", "h2", "p", "li", "blockquote"]):
        text = " ".join(element.get_text(" ", strip=True).split())
        if len(text) < 2 or text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)

    if not paragraphs:
        fallback = " ".join(container.get_text(" ", strip=True).split())
        if fallback:
            paragraphs.append(fallback)

    return "\n".join(paragraphs), title


class UrlExtractor:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_download_bytes: int,
        max_article_chars: int,
        max_redirects: int,
        resolver: Resolver = resolve_host,
    ) -> None:
        self._client = client
        self._max_download_bytes = max_download_bytes
        self._max_article_chars = max_article_chars
        self._max_redirects = max_redirects
        self._resolver = resolver

    async def extract(self, url: str) -> ExtractedDocument:
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            await validate_public_url(current_url, self._resolver)
            try:
                async with self._client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
                ) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise ExtractionError("重新導向回應缺少 Location")
                        if redirect_count >= self._max_redirects:
                            raise ExtractionError("重新導向次數過多")
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if content_type.lower() not in ALLOWED_CONTENT_TYPES:
                        raise ExtractionError("網址不是可分析的 HTML 或純文字內容")

                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self._max_download_bytes:
                        raise ExtractionError("網頁內容超過下載大小限制")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_download_bytes:
                            raise ExtractionError("網頁內容超過下載大小限制")
                    encoding = response.encoding or "utf-8"
            except httpx.HTTPError as exc:
                raise ExtractionError("無法下載網頁內容") from exc
            except ValueError as exc:
                raise ExtractionError("網頁回應標頭無效") from exc

            decoded = bytes(body).decode(encoding, errors="replace")
            if content_type.lower() == "text/plain":
                text, title = re.sub(r"\s+", " ", decoded).strip(), None
            else:
                text, title = extract_text_from_html(decoded)
            truncated = len(text) > self._max_article_chars
            text = text[: self._max_article_chars].strip()
            if not text:
                raise ExtractionError("網頁中找不到可分析的文字")
            return ExtractedDocument(
                url=current_url,
                text=text,
                title=title,
                truncated=truncated,
            )

        raise ExtractionError("重新導向次數過多")
