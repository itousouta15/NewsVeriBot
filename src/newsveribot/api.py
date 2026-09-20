from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Protocol, cast

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from newsveribot import __version__
from newsveribot.claim_model import SklearnClaimDetector
from newsveribot.claims import ClaimDetector, RuleBasedClaimDetector
from newsveribot.config import Settings, get_settings
from newsveribot.extractor import ExtractionError, UrlExtractor
from newsveribot.reranker import LexicalReranker
from newsveribot.retriever import GoogleFactCheckClient
from newsveribot.schemas import AnalysisResponse, AnalyzeRequest, HealthResponse
from newsveribot.service import AnalysisService


class Analyzer(Protocol):
    async def analyze(self, request: AnalyzeRequest) -> AnalysisResponse: ...


def build_service(settings: Settings, client: httpx.AsyncClient) -> AnalysisService:
    detector: ClaimDetector
    if settings.claim_model_path is None:
        detector = RuleBasedClaimDetector()
    else:
        detector = SklearnClaimDetector(settings.claim_model_path)
    return AnalysisService(
        settings=settings,
        extractor=UrlExtractor(
            client,
            max_download_bytes=settings.max_download_bytes,
            max_article_chars=settings.max_article_chars,
            max_redirects=settings.max_redirects,
        ),
        detector=detector,
        retriever=GoogleFactCheckClient(
            client,
            settings.fact_check_api_key,
            page_size=settings.fact_check_page_size,
        ),
        reranker=LexicalReranker(),
    )


def create_app(service: Analyzer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if service is not None:
            app.state.analysis_service = service
            yield
            return

        settings = get_settings()
        timeout = httpx.Timeout(settings.http_timeout_seconds)
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.analysis_service = build_service(settings, client)
            yield

    application = FastAPI(
        title="NewsVeriBot API",
        description="Fact-checking assistant that does not make final truth judgments.",
        version=__version__,
        lifespan=lifespan,
    )

    def get_analyzer(request: Request) -> Analyzer:
        return cast(Analyzer, request.app.state.analysis_service)

    @application.exception_handler(ExtractionError)
    async def extraction_error_handler(_: Request, exc: ExtractionError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @application.post("/v1/analyze", response_model=AnalysisResponse)
    async def analyze(
        payload: AnalyzeRequest,
        analyzer: Annotated[Analyzer, Depends(get_analyzer)],
    ) -> AnalysisResponse:
        return await analyzer.analyze(payload)

    return application


app = create_app()


def run() -> None:
    uvicorn.run("newsveribot.api:app", host="0.0.0.0", port=8000)
