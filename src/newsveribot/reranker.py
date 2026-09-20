import re
from typing import Protocol

from newsveribot.schemas import FactCheckCandidate

NORMALIZE_PATTERN = re.compile(r"[^0-9a-z\u3400-\u9fff]+")
NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")


class CandidateReranker(Protocol):
    def rank(
        self,
        claim: str,
        candidates: list[FactCheckCandidate],
        *,
        limit: int,
    ) -> list[FactCheckCandidate]: ...


def _normalize(text: str) -> str:
    return NORMALIZE_PATTERN.sub("", text.lower())


def _ngrams(text: str, size: int = 2) -> set[str]:
    normalized = _normalize(text)
    if len(normalized) <= size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class LexicalReranker:
    """Character bigram baseline with a numeric-consistency signal."""

    def rank(
        self,
        claim: str,
        candidates: list[FactCheckCandidate],
        *,
        limit: int,
    ) -> list[FactCheckCandidate]:
        claim_ngrams = _ngrams(claim)
        claim_numbers = set(NUMBER_PATTERN.findall(claim))
        ranked: list[FactCheckCandidate] = []

        for candidate in candidates:
            title = candidate.title or ""
            semantic_text = f"{candidate.reviewed_claim} {title}"
            score = _jaccard(claim_ngrams, _ngrams(semantic_text))
            candidate_numbers = set(NUMBER_PATTERN.findall(semantic_text))
            if claim_numbers and candidate_numbers:
                if claim_numbers & candidate_numbers:
                    score = min(1.0, score + 0.15)
                else:
                    score *= 0.65
            ranked.append(candidate.model_copy(update={"relevance_score": round(score, 4)}))

        ranked.sort(key=lambda item: item.relevance_score, reverse=True)
        return ranked[:limit]
