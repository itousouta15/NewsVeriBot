from typing import cast

import httpx

from newsveribot.claims import RuleBasedClaimDetector
from newsveribot.config import Settings
from newsveribot.extractor import UrlExtractor
from newsveribot.reranker import LexicalReranker
from newsveribot.retriever import FactCheckRetriever
from newsveribot.schemas import AnalyzeRequest, FactCheckCandidate
from newsveribot.service import AnalysisService


class FakeRetriever:
    is_configured = True

    async def search(self, query: str) -> list[FactCheckCandidate]:
        return [
            FactCheckCandidate(
                reviewed_claim=query,
                publisher="測試查核機構",
                review_url="https://example.com/fact-check",
                rating="部分錯誤",
            )
        ]


async def test_text_analysis_runs_end_to_end() -> None:
    async with httpx.AsyncClient() as client:
        settings = Settings(max_claims=3)
        service = AnalysisService(
            settings=settings,
            extractor=UrlExtractor(
                client,
                max_download_bytes=settings.max_download_bytes,
                max_article_chars=settings.max_article_chars,
                max_redirects=settings.max_redirects,
            ),
            detector=RuleBasedClaimDetector(),
            retriever=cast(FactCheckRetriever, FakeRetriever()),
            reranker=LexicalReranker(),
        )
        response = await service.analyze(AnalyzeRequest(text="政府宣布2026年起補助增加5000元。"))

    assert len(response.claims) == 1
    assert response.claims[0].candidates[0].rating == "部分錯誤"
    assert not response.warnings


async def test_text_analysis_enforces_configured_length_limit() -> None:
    async with httpx.AsyncClient() as client:
        settings = Settings(max_article_chars=1_000)
        service = AnalysisService(
            settings=settings,
            extractor=UrlExtractor(
                client,
                max_download_bytes=settings.max_download_bytes,
                max_article_chars=settings.max_article_chars,
                max_redirects=settings.max_redirects,
            ),
            detector=RuleBasedClaimDetector(),
            retriever=cast(FactCheckRetriever, FakeRetriever()),
            reranker=LexicalReranker(),
        )
        response = await service.analyze(AnalyzeRequest(text="政策" * 6_000))

    assert response.source.character_count == 1_000
    assert "尾端文字未納入" in response.warnings[0]
