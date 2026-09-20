from newsveribot.reranker import LexicalReranker
from newsveribot.schemas import FactCheckCandidate


def _candidate(text: str) -> FactCheckCandidate:
    return FactCheckCandidate(
        reviewed_claim=text,
        publisher="測試查核機構",
        review_url="https://example.com/review",
    )


def test_reranker_prefers_matching_claim_and_number() -> None:
    reranker = LexicalReranker()
    candidates = [
        _candidate("疫苗接種率已達80%"),
        _candidate("政府將發放5000元補助"),
        _candidate("政府將發放1000元補助"),
    ]
    ranked = reranker.rank("政府宣布將發放5000元補助", candidates, limit=3)
    assert ranked[0].reviewed_claim == "政府將發放5000元補助"
    assert ranked[0].relevance_score > ranked[1].relevance_score
