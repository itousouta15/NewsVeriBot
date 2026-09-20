from typing import Any, Protocol

import httpx
from pydantic import SecretStr, ValidationError

from newsveribot.schemas import FactCheckCandidate

FACT_CHECK_ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


class FactCheckError(RuntimeError):
    """The fact-check provider failed or returned invalid data."""


class FactCheckRetriever(Protocol):
    @property
    def is_configured(self) -> bool: ...

    async def search(self, query: str) -> list[FactCheckCandidate]: ...


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class GoogleFactCheckClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: SecretStr | None,
        *,
        page_size: int,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._page_size = page_size

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None and bool(self._api_key.get_secret_value())

    async def search(self, query: str) -> list[FactCheckCandidate]:
        if not self.is_configured or self._api_key is None:
            return []

        try:
            response = await self._client.get(
                FACT_CHECK_ENDPOINT,
                params={
                    "query": query,
                    "languageCode": "zh",
                    "pageSize": self._page_size,
                    "key": self._api_key.get_secret_value(),
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FactCheckError("查核資料服務目前無法使用") from exc

        root = _object(payload)
        raw_claims = root.get("claims", [])
        if not isinstance(raw_claims, list):
            raise FactCheckError("查核資料格式無效")

        candidates: list[FactCheckCandidate] = []
        for raw_claim in raw_claims:
            claim = _object(raw_claim)
            reviewed_claim = str(claim.get("text") or "").strip()
            reviews = claim.get("claimReview", [])
            if not reviewed_claim or not isinstance(reviews, list):
                continue
            for raw_review in reviews:
                review = _object(raw_review)
                publisher = _object(review.get("publisher"))
                review_url = review.get("url")
                publisher_name = str(publisher.get("name") or "未知查核機構").strip()
                if not isinstance(review_url, str) or not review_url:
                    continue
                try:
                    candidates.append(
                        FactCheckCandidate.model_validate(
                            {
                                "reviewed_claim": reviewed_claim,
                                "publisher": publisher_name,
                                "review_url": review_url,
                                "title": _optional_text(review.get("title")),
                                "claimant": _optional_text(claim.get("claimant")),
                                "claim_date": _optional_text(claim.get("claimDate")),
                                "review_date": _optional_text(review.get("reviewDate")),
                                "rating": _optional_text(review.get("textualRating")),
                                "language_code": _optional_text(review.get("languageCode")),
                            }
                        )
                    )
                except ValidationError:
                    continue
        return candidates


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
