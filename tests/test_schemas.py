import pytest
from pydantic import ValidationError

from newsveribot.schemas import AnalyzeRequest


def test_request_accepts_text_only() -> None:
    request = AnalyzeRequest(text="這是一段待分析文字")
    assert request.text == "這是一段待分析文字"
    assert request.url is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": "內容", "url": "https://example.com"},
        {"text": "   "},
    ],
)
def test_request_requires_exactly_one_input(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        AnalyzeRequest.model_validate(payload)
