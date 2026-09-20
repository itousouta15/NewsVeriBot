from fastapi.testclient import TestClient

from newsveribot.api import create_app
from newsveribot.schemas import AnalysisResponse, AnalyzeRequest, SourceDocument
from newsveribot.service import DISCLAIMER


class StubAnalyzer:
    async def analyze(self, request: AnalyzeRequest) -> AnalysisResponse:
        return AnalysisResponse(
            source=SourceDocument(
                input_kind="text",
                character_count=len(request.text or ""),
            ),
            claims=[],
            warnings=[],
            disclaimer=DISCLAIMER,
        )


def test_health_endpoint() -> None:
    with TestClient(create_app(StubAnalyzer())) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_analyze_endpoint_validates_and_returns_result() -> None:
    with TestClient(create_app(StubAnalyzer())) as client:
        response = client.post("/v1/analyze", json={"text": "待分析內容"})
    assert response.status_code == 200
    assert response.json()["source"]["character_count"] == 5


def test_analyze_endpoint_rejects_ambiguous_input() -> None:
    with TestClient(create_app(StubAnalyzer())) as client:
        response = client.post(
            "/v1/analyze",
            json={"text": "內容", "url": "https://example.com"},
        )
    assert response.status_code == 422
