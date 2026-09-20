from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from newsveribot.claims import split_sentences
from newsveribot.dataset import ClaimAnnotation, DatasetError, validate_annotations
from newsveribot.schemas import DetectedClaim

ARTIFACT_VERSION = 1


class ClassificationMetrics(BaseModel):
    accuracy: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_negative: int = Field(ge=0)


class BaselineReport(BaseModel):
    model_type: str = "tfidf_logistic_regression"
    trained_at: datetime
    threshold: float = Field(ge=0, le=1)
    target_recall: float = Field(ge=0, le=1)
    train_records: int
    dev_records: int
    test_records: int
    dev: ClassificationMetrics
    test: ClassificationMetrics


def _labeled_xy(records: list[ClaimAnnotation]) -> tuple[list[str], list[int]]:
    validate_annotations(records, require_labels=True)
    texts: list[str] = []
    labels: list[int] = []
    for record in records:
        if record.label is None:
            raise DatasetError(f"尚未標註：{record.id}")
        texts.append(record.text)
        labels.append(record.label)
    return texts, labels


def _classification_metrics(
    labels: list[int],
    probabilities: list[float],
    threshold: float,
) -> ClassificationMetrics:
    predictions = [int(probability >= threshold) for probability in probabilities]
    pairs = list(zip(labels, predictions, strict=True))
    true_positive = sum(actual == 1 and predicted == 1 for actual, predicted in pairs)
    false_positive = sum(actual == 0 and predicted == 1 for actual, predicted in pairs)
    true_negative = sum(actual == 0 and predicted == 0 for actual, predicted in pairs)
    false_negative = sum(actual == 1 and predicted == 0 for actual, predicted in pairs)
    total = len(labels)
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return ClassificationMetrics(
        accuracy=(true_positive + true_negative) / total if total else 0,
        precision=precision,
        recall=recall,
        f1=f1,
        true_positive=true_positive,
        false_positive=false_positive,
        true_negative=true_negative,
        false_negative=false_negative,
    )


def _positive_probabilities(pipeline: Pipeline[Any], texts: list[str]) -> list[float]:
    raw_probabilities: Any = pipeline.predict_proba(texts)
    return [float(row[1]) for row in raw_probabilities]


def choose_threshold(
    labels: list[int],
    probabilities: list[float],
    *,
    target_recall: float,
) -> float:
    candidates = [step / 100 for step in range(5, 96)]
    scored = [
        (threshold, _classification_metrics(labels, probabilities, threshold))
        for threshold in candidates
    ]
    eligible = [item for item in scored if item[1].recall >= target_recall]
    if eligible:
        return max(eligible, key=lambda item: (item[1].f1, item[1].precision, -item[0]))[0]
    return max(scored, key=lambda item: (item[1].recall, item[1].f1, -item[0]))[0]


def train_baseline(
    train_records: list[ClaimAnnotation],
    dev_records: list[ClaimAnnotation],
    test_records: list[ClaimAnnotation],
    *,
    seed: int,
    target_recall: float,
) -> tuple[dict[str, Any], BaselineReport]:
    train_texts, train_labels = _labeled_xy(train_records)
    dev_texts, dev_labels = _labeled_xy(dev_records)
    test_texts, test_labels = _labeled_xy(test_records)
    if set(train_labels) != {0, 1}:
        raise DatasetError("train split 必須同時包含正例與反例")

    pipeline: Pipeline[Any] = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    max_features=30_000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1_000,
                    random_state=seed,
                ),
            ),
        ]
    )
    pipeline.fit(train_texts, train_labels)
    dev_probabilities = _positive_probabilities(pipeline, dev_texts)
    threshold = choose_threshold(dev_labels, dev_probabilities, target_recall=target_recall)
    test_probabilities = _positive_probabilities(pipeline, test_texts)
    report = BaselineReport(
        trained_at=datetime.now(UTC),
        threshold=threshold,
        target_recall=target_recall,
        train_records=len(train_records),
        dev_records=len(dev_records),
        test_records=len(test_records),
        dev=_classification_metrics(dev_labels, dev_probabilities, threshold),
        test=_classification_metrics(test_labels, test_probabilities, threshold),
    )
    artifact: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "pipeline": pipeline,
        "threshold": threshold,
        "trained_at": report.trained_at.isoformat(),
    }
    return artifact, report


def save_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        joblib.dump(artifact, temporary)
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DatasetError(f"無法寫入模型：{path}") from exc


class SklearnClaimDetector:
    def __init__(self, artifact_path: Path) -> None:
        if not artifact_path.is_file():
            raise ValueError(f"找不到 claim model：{artifact_path}")
        try:
            artifact: Any = joblib.load(artifact_path)
        except (OSError, ValueError, EOFError) as exc:
            raise ValueError(f"無法載入 claim model：{artifact_path}") from exc
        if not isinstance(artifact, dict) or artifact.get("artifact_version") != ARTIFACT_VERSION:
            raise ValueError("claim model artifact 版本不相容")
        pipeline = artifact.get("pipeline")
        threshold = artifact.get("threshold")
        if not hasattr(pipeline, "predict_proba") or not isinstance(threshold, int | float):
            raise ValueError("claim model artifact 格式無效")
        self._pipeline: Any = pipeline
        self._threshold = float(threshold)

    def detect(self, text: str, *, limit: int) -> list[DetectedClaim]:
        sentences = [
            sentence
            for sentence in split_sentences(text)
            if len(sentence) >= 8 and not sentence.endswith(("?", "？"))
        ]
        if not sentences:
            return []
        probabilities = _positive_probabilities(self._pipeline, sentences)
        detections = [
            DetectedClaim(
                text=sentence,
                checkworthiness_score=round(probability, 4),
                reasons=["TF-IDF + Logistic Regression baseline"],
            )
            for sentence, probability in zip(sentences, probabilities, strict=True)
            if probability >= self._threshold
        ]
        detections.sort(key=lambda item: item.checkworthiness_score, reverse=True)
        return detections[:limit]
