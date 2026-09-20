from pathlib import Path

from newsveribot.dataset import (
    ArticleRecord,
    ClaimAnnotation,
    audit_annotations,
    blind_sample_annotations,
    prepare_annotations,
    read_annotation_csv,
    read_jsonl,
    split_annotations,
    validate_annotations,
    write_annotation_csv,
    write_jsonl,
)


def _annotation(group: int, label: int) -> ClaimAnnotation:
    kind = "positive" if label else "negative"
    return ClaimAnnotation(
        id=f"article_{group}_{kind}",
        article_id=f"article_{group}",
        group_id=f"event_{group}",
        sentence_index=label,
        text=(f"政府宣布2026年增加第{group}項補助。" if label else f"我覺得第{group}項政策很好。"),
        label=label,
        rationale="測試標註",
        source_url=f"https://example.com/{group}",
    )


def test_prepare_annotations_preserves_group_and_removes_duplicates() -> None:
    article = ArticleRecord(
        article_id="article_1",
        group_id="event_1",
        title="測試",
        text="政府宣布2026年增加補助。政府宣布2026年增加補助。這是另一句測試文字。",
        source_url="https://example.com/1",
        source_name="Example",
        retrieved_at="2026-09-20T12:00:00+08:00",
        rights_note="測試資料",
    )
    records = prepare_annotations([article])
    assert len(records) == 2
    assert {record.group_id for record in records} == {"event_1"}


def test_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "annotations.jsonl"
    expected = [_annotation(1, 0), _annotation(1, 1)]
    write_jsonl(path, expected)
    actual = read_jsonl(path, ClaimAnnotation)
    assert actual == expected
    assert validate_annotations(actual, require_labels=True).positive == 1


def test_csv_round_trip_supports_unlabeled_rows(tmp_path: Path) -> None:
    path = tmp_path / "annotations.csv"
    expected = [_annotation(1, 1).model_copy(update={"label": None, "rationale": None})]
    write_annotation_csv(path, expected)
    actual = read_annotation_csv(path)
    assert actual == expected


def test_split_keeps_groups_isolated() -> None:
    records = [_annotation(group, label) for group in range(12) for label in (0, 1)]
    splits = split_annotations(records, seed=42)
    groups = {
        name: {record.group_id for record in split_records}
        for name, split_records in splits.items()
    }
    assert groups["train"].isdisjoint(groups["dev"])
    assert groups["train"].isdisjoint(groups["test"])
    assert groups["dev"].isdisjoint(groups["test"])
    assert sum(len(split_records) for split_records in splits.values()) == len(records)


def test_validation_allows_missing_rationale() -> None:
    record = _annotation(1, 1).model_copy(update={"rationale": None})
    assert validate_annotations([record], require_labels=True).positive == 1


def test_blind_sample_is_deterministic_and_removes_answers() -> None:
    records = [_annotation(group, label) for group in range(6) for label in (0, 1)]
    first = blind_sample_annotations(records, size=5, seed=42)
    second = blind_sample_annotations(records, size=5, seed=42)
    assert [record.id for record in first] == [record.id for record in second]
    assert all(record.label is None and record.rationale is None for record in first)


def test_audit_reports_duplicate_text_without_exposing_it() -> None:
    records = [_annotation(1, 1), _annotation(2, 1), _annotation(3, 0)]
    records[1] = records[1].model_copy(update={"text": records[0].text})
    report = audit_annotations(records)
    assert report.duplicate_records == 1
    assert report.duplicate_groups[0].record_ids == [records[0].id, records[1].id]
    assert len(report.duplicate_groups[0].text_sha256) == 64
