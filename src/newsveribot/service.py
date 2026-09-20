import asyncio

from newsveribot.claims import ClaimDetector
from newsveribot.config import Settings
from newsveribot.extractor import UrlExtractor
from newsveribot.reranker import CandidateReranker
from newsveribot.retriever import FactCheckError, FactCheckRetriever
from newsveribot.schemas import (
    AnalysisResponse,
    AnalyzeRequest,
    ClaimAnalysis,
    DetectedClaim,
    SourceDocument,
)

DISCLAIMER = "此為 AI 與規則輔助分析，不代表最終真假判定；請開啟來源並人工確認。"


class AnalysisService:
    def __init__(
        self,
        *,
        settings: Settings,
        extractor: UrlExtractor,
        detector: ClaimDetector,
        retriever: FactCheckRetriever,
        reranker: CandidateReranker,
    ) -> None:
        self._settings = settings
        self._extractor = extractor
        self._detector = detector
        self._retriever = retriever
        self._reranker = reranker

    async def analyze(self, request: AnalyzeRequest) -> AnalysisResponse:
        warnings: list[str] = []
        if request.url is not None:
            document = await self._extractor.extract(str(request.url))
            text = document.text
            if document.truncated:
                warnings.append("內容已達分析長度上限，尾端文字未納入。")
            source = SourceDocument.model_validate(
                {
                    "input_kind": "url",
                    "url": document.url,
                    "title": document.title,
                    "character_count": len(text),
                }
            )
        else:
            text = (request.text or "").strip()
            if len(text) > self._settings.max_article_chars:
                text = text[: self._settings.max_article_chars].strip()
                warnings.append("內容已達分析長度上限，尾端文字未納入。")
            source = SourceDocument(input_kind="text", character_count=len(text))

        detected = self._detector.detect(text, limit=self._settings.max_claims)
        if not detected:
            warnings.append("目前的 baseline 沒有找到明確且值得查核的主張。")
            return AnalysisResponse(
                source=source,
                claims=[],
                warnings=warnings,
                disclaimer=DISCLAIMER,
            )

        if not self._retriever.is_configured:
            warnings.append("尚未設定 Google Fact Check API key，因此未查詢線上查核報告。")
            analyses = [ClaimAnalysis(claim=claim, candidates=[]) for claim in detected]
        else:
            tasks = [self._analyze_claim(claim) for claim in detected]
            results = await asyncio.gather(*tasks)
            analyses = [result[0] for result in results]
            warnings.extend(message for _, message in results if message is not None)

        return AnalysisResponse(
            source=source,
            claims=analyses,
            warnings=list(dict.fromkeys(warnings)),
            disclaimer=DISCLAIMER,
        )

    async def _analyze_claim(
        self,
        claim: DetectedClaim,
    ) -> tuple[ClaimAnalysis, str | None]:
        try:
            candidates = await self._retriever.search(claim.text)
        except FactCheckError as exc:
            return ClaimAnalysis(claim=claim, candidates=[]), str(exc)

        ranked = self._reranker.rank(claim.text, candidates, limit=3)
        warning = None
        if not ranked:
            warning = "至少一項主張尚未找到相關查核報告；這不代表該主張為真。"
        return ClaimAnalysis(claim=claim, candidates=ranked), warning
