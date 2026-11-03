from pathlib import Path
from unittest.mock import Mock

import pytest

from newsveribot.claim_cli import main
from newsveribot.claim_model import SklearnClaimDetector, save_artifact, train_baseline
from newsveribot.dataset import ClaimAnnotation, DatasetError, write_jsonl


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


@pytest.fixture
def fit_spy(monkeypatch: pytest.MonkeyPatch) -> Mock:
    fit = Mock(side_effect=AssertionError("invalid data reached model fitting"))
    monkeypatch.setattr("newsveribot.claim_model.Pipeline.fit", fit)
    return fit


@pytest.mark.parametrize("left,right", [(0, 1), (0, 2), (1, 2)])
@pytest.mark.parametrize("field", ["group_id", "article_id", "id"])
def test_training_rejects_overlapping_splits(
    left: int, right: int, field: str, fit_spy: Mock
) -> None:
    splits = [_records(0, 1), _records(1, 2), _records(2, 3)]
    updates = {field: getattr(splits[left][0], field)}
    if field == "id":
        splits[right][0] = splits[right][0].model_copy(update=updates)
    else:
        # Keep each split internally valid; only the cross-split identity overlaps.
        splits[right] = [
            record.model_copy(update={**updates, "sentence_index": record.sentence_index + 2})
            for record in splits[right]
        ]
    names = ("train", "dev", "test")

    with pytest.raises(DatasetError, match=rf"{names[left]}/{names[right]}.*{field}"):
        train_baseline(*splits, seed=42, target_recall=0.82)

    fit_spy.assert_not_called()


@pytest.mark.parametrize("split_index", range(3))
@pytest.mark.parametrize("label", [0, 1])
def test_training_requires_both_labels_in_every_split(
    split_index: int, label: int, fit_spy: Mock
) -> None:
    splits = [_records(0, 1), _records(1, 2), _records(2, 3)]
    splits[split_index] = [record for record in splits[split_index] if record.label == label]
    name = ("train", "dev", "test")[split_index]

    with pytest.raises(DatasetError, match=rf"{name} split.*正例與反例"):
        train_baseline(*splits, seed=42, target_recall=0.82)

    fit_spy.assert_not_called()


@pytest.mark.parametrize("split_index", range(3))
@pytest.mark.parametrize("invalid_kind", ["empty", "unlabeled"])
def test_training_rejects_invalid_split_with_context(
    split_index: int, invalid_kind: str, fit_spy: Mock
) -> None:
    splits = [_records(0, 1), _records(1, 2), _records(2, 3)]
    if invalid_kind == "empty":
        splits[split_index] = []
    else:
        splits[split_index][0] = splits[split_index][0].model_copy(
            update={"label": None, "rationale": None}
        )
    name = ("train", "dev", "test")[split_index]

    with pytest.raises(DatasetError, match=rf"{name} split"):
        train_baseline(*splits, seed=42, target_recall=0.82)

    fit_spy.assert_not_called()


def test_train_command_rejects_leakage_without_writing_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fit_spy: Mock
) -> None:
    write_jsonl(tmp_path / "train.jsonl", _records(0, 2))
    write_jsonl(tmp_path / "dev.jsonl", _records(1, 3))
    write_jsonl(tmp_path / "test.jsonl", _records(3, 4))
    model_path = tmp_path / "model.joblib"
    report_path = tmp_path / "report.json"

    result = main(
        [
            "train",
            "--data-dir",
            str(tmp_path),
            "--model-output",
            str(model_path),
            "--report-output",
            str(report_path),
        ]
    )

    assert result == 2
    assert "train/dev split 的 group_id 重複：event_1" in capsys.readouterr().err
    assert not model_path.exists()
    assert not report_path.exists()
    fit_spy.assert_not_called()
