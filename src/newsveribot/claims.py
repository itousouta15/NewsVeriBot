import re
from typing import Protocol

from newsveribot.schemas import DetectedClaim

SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?])|[\r\n]+")
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|％|萬|億|元|人|件|年|月|日)?")
DATE_PATTERN = re.compile(
    r"(?:\d{4}\s*年|\d{1,2}\s*月\s*\d{1,2}\s*日|昨天|今日|今天|明天|本週|上週)"
)
ATTRIBUTION_PATTERN = re.compile(r"(?:表示|指出|宣布|聲稱|證實|否認|發布|通過|發現|顯示)")
VERIFIABLE_PATTERN = re.compile(
    r"(?:政策|法案|法律|研究|調查|統計|疫苗|藥物|政府|公司|法院|選舉|補助|稅|成長率|風險)"
)
CAUSAL_PATTERN = re.compile(r"(?:造成|導致|使得|降低|提高|預防|治療|增加|減少)")
OPINION_PATTERN = re.compile(r"^(?:我認為|我覺得|我希望|個人認為|依我看|太扯|好棒|真糟)")


class ClaimDetector(Protocol):
    def detect(self, text: str, *, limit: int) -> list[DetectedClaim]: ...


def split_sentences(text: str) -> list[str]:
    sentences = []
    for part in SENTENCE_BOUNDARY.split(text):
        sentence = " ".join(part.split()).strip()
        if sentence:
            sentences.append(sentence)
    return sentences


class RuleBasedClaimDetector:
    """Transparent baseline to be replaced by the trained model A."""

    threshold = 0.35

    def detect(self, text: str, *, limit: int) -> list[DetectedClaim]:
        detections: list[DetectedClaim] = []
        for sentence in split_sentences(text):
            if len(sentence) < 8 or sentence.endswith(("?", "？")):
                continue

            score = 0.0
            reasons: list[str] = []
            if NUMBER_PATTERN.search(sentence):
                score += 0.35
                reasons.append("包含具體數字")
            if DATE_PATTERN.search(sentence):
                score += 0.2
                reasons.append("包含可驗證時間")
            if ATTRIBUTION_PATTERN.search(sentence):
                score += 0.2
                reasons.append("包含公開宣稱或事件")
            if VERIFIABLE_PATTERN.search(sentence):
                score += 0.2
                reasons.append("涉及可查證領域")
            if CAUSAL_PATTERN.search(sentence):
                score += 0.2
                reasons.append("包含因果或效果宣稱")
            if OPINION_PATTERN.search(sentence):
                score -= 0.5
                reasons.append("帶有明顯主觀語氣")

            score = max(0.0, min(1.0, score))
            if score >= self.threshold:
                detections.append(
                    DetectedClaim(
                        text=sentence,
                        checkworthiness_score=round(score, 3),
                        reasons=reasons,
                    )
                )

        detections.sort(key=lambda item: item.checkworthiness_score, reverse=True)
        return detections[:limit]
