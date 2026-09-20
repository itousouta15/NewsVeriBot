from pathlib import Path

from newsveribot.claim_model import SklearnClaimDetector, save_artifact, train_baseline
from newsveribot.dataset import ClaimAnnotation


def _records(start: int, stop: int) -> list[ClaimAnnotation]:
    records: list[ClaimAnnotation] = []
    for index in range(start, stop):
        common = {
            "article_id": f"article_{index}",
            "group_id": f"event_{index}",
            "source_url": f"https://example.com/{index}",
            "rationale": "測試標註",
        }
        records.extend(
            [
                ClaimAnnotation(
                    id=f"positive_{index}",
                    sentence_index=0,
                    text=f"政府宣布2026年增加第{index}項補助5000元。",
                    label=1,
                    **common,
                ),
                ClaimAnnotation(
                    id=f"negative_{index}",
                    sentence_index=1,
                    text=f"我覺得第{index}項政策真的很不錯。",
                    label=0,
                    **common,
                ),
            ]
        )
    return records


def test_train_save_and_load_baseline(tmp_path: Path) -> None:
    artifact, report = train_baseline(
        _records(0, 8),
        _records(8, 10),
        _records(10, 12),
        seed=42,
        target_recall=0.82,
    )
    model_path = tmp_path / "claim_detector.joblib"
    save_artifact(model_path, artifact)
    detector = SklearnClaimDetector(model_path)
    detections = detector.detect("政府宣布2026年補助增加5000元。", limit=3)

    assert report.dev.recall >= 0.82
    assert report.test_records == 4
    assert detections
    assert detections[0].reasons == ["TF-IDF + Logistic Regression baseline"]
