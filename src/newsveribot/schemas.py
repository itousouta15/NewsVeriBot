from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=20_000)
    url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def require_exactly_one_input(self) -> Self:
        has_text = self.text is not None and bool(self.text.strip())
        has_url = self.url is not None
        if has_text == has_url:
            raise ValueError("請提供 text 或 url 其中一個")
        return self


class DetectedClaim(BaseModel):
    text: str
    checkworthiness_score: float = Field(ge=0, le=1)
    reasons: list[str]


class FactCheckCandidate(BaseModel):
    reviewed_claim: str
    publisher: str
    review_url: AnyHttpUrl
    title: str | None = None
    claimant: str | None = None
    claim_date: str | None = None
    review_date: str | None = None
    rating: str | None = None
    language_code: str | None = None
    relevance_score: float = Field(default=0, ge=0, le=1)


class ClaimAnalysis(BaseModel):
    claim: DetectedClaim
    candidates: list[FactCheckCandidate]


class SourceDocument(BaseModel):
    input_kind: Literal["text", "url"]
    url: AnyHttpUrl | None = None
    title: str | None = None
    character_count: int = Field(ge=0)


class AnalysisResponse(BaseModel):
    source: SourceDocument
    claims: list[ClaimAnalysis]
    warnings: list[str]
    disclaimer: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
