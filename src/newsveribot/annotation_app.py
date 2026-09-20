import argparse
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from newsveribot.annotation import AnnotationDecision, AnnotationStats, AnnotationStore
from newsveribot.dataset import ClaimAnnotation, DatasetError

Identifier = Annotated[str, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    annotator_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    pass_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    label: Literal[0, 1]
    rationale: str | None = Field(default=None, min_length=3, max_length=1_000)


class NextAnnotationResponse(BaseModel):
    claim: ClaimAnnotation | None
    stats: AnnotationStats


def create_annotation_app(store: AnnotationStore) -> FastAPI:
    application = FastAPI(
        title="NewsVeriBot Annotation Workbench",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.exception_handler(DatasetError)
    async def dataset_error_handler(_: Request, exc: DatasetError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = files("newsveribot.static").joinpath("annotator.html").read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @application.get("/api/next", response_model=NextAnnotationResponse)
    async def next_annotation(
        annotator_id: Identifier, pass_id: Identifier
    ) -> NextAnnotationResponse:
        return NextAnnotationResponse(
            claim=store.next_claim(annotator_id, pass_id),
            stats=store.stats(annotator_id, pass_id),
        )

    @application.get("/api/stats", response_model=AnnotationStats)
    async def stats(annotator_id: Identifier, pass_id: Identifier) -> AnnotationStats:
        return store.stats(annotator_id, pass_id)

    @application.post("/api/decisions", response_model=AnnotationDecision)
    async def save_decision(payload: DecisionRequest) -> AnnotationDecision:
        return store.save(
            claim_id=payload.claim_id,
            annotator_id=payload.annotator_id,
            pass_id=payload.pass_id,
            label=payload.label,
            rationale=payload.rationale,
        )

    return application


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NewsVeriBot 本機標註工作台")
    parser.add_argument("--claims", type=Path, required=True, help="prepare 產生的 claim JSONL")
    parser.add_argument("--events", type=Path, required=True, help="append-only 標註事件 JSONL")
    parser.add_argument("--seed", type=int, default=42, help="句子顯示順序")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--allow-network", action="store_true")
    return parser


def run() -> None:
    parser = _parser()
    args = parser.parse_args()
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if args.host not in loopback_hosts and not args.allow_network:
        parser.error("標註工作台無認證；非 loopback 綁定必須明確加上 --allow-network")
    store = AnnotationStore(args.claims, args.events, seed=args.seed)
    uvicorn.run(create_annotation_app(store), host=args.host, port=args.port)
