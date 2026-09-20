import csv
import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, model_validator

from newsveribot.claims import split_sentences

ANNOTATION_CSV_FIELDS = (
    "id",
    "article_id",
    "group_id",
    "sentence_index",
    "text",
    "label",
    "rationale",
    "source_url",
    "guideline_version",
)


class DatasetError(ValueError):
    """A dataset is invalid or cannot be split safely."""


class ArticleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    group_id: str | None = Field(default=None, min_length=1)
    title: str | None = None
    text: str = Field(min_length=1)
    source_url: AnyHttpUrl
    source_name: str = Field(min_length=1)
    retrieved_at: datetime
    published_at: datetime | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rights_note: str = Field(min_length=1)


class ClaimAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    article_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    sentence_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    label: Literal[0, 1] | None = None
    rationale: str | None = None
    source_url: AnyHttpUrl
    guideline_version: str = Field(default="1.0", min_length=1)

    @model_validator(mode="after")
    def rationale_requires_label(self) -> Self:
        if self.rationale and self.label is None:
            raise ValueError("有 rationale 時必須先填 label")
        return self


class DatasetSummary(BaseModel):
    records: int
    groups: int
    positive: int
    negative: int
    unlabeled: int


class DuplicateSentenceGroup(BaseModel):
    text_sha256: str
    record_ids: list[str]


class AnnotationAudit(BaseModel):
    summary: DatasetSummary
    minimum_characters: int
    maximum_characters: int
    mean_characters: float
    questions: int
    duplicate_records: int
    duplicate_groups: list[DuplicateSentenceGroup]


def read_jsonl[RecordT: BaseModel](path: Path, model: type[RecordT]) -> list[RecordT]:
    records: list[RecordT] = []
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, raw_line in enumerate(source, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    records.append(model.model_validate(payload))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise DatasetError(f"{path}:{line_number}: {exc}") from exc
    except OSError as exc:
        raise DatasetError(f"無法讀取資料檔：{path}") from exc
    return records


def write_jsonl(path: Path, records: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as destination:
            for record in records:
                payload = record.model_dump(mode="json", exclude_none=False)
                destination.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                destination.write("\n")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DatasetError(f"無法寫入資料檔：{path}") from exc


def write_annotation_csv(path: Path, records: list[ClaimAnnotation]) -> None:
    validate_annotations(records, require_labels=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=ANNOTATION_CSV_FIELDS)
            writer.writeheader()
            for record in records:
                payload = record.model_dump(mode="json")
                writer.writerow(
                    {
                        field: "" if payload.get(field) is None else payload.get(field)
                        for field in ANNOTATION_CSV_FIELDS
                    }
                )
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DatasetError(f"無法寫入 CSV：{path}") from exc


def read_annotation_csv(path: Path) -> list[ClaimAnnotation]:
    records: list[ClaimAnnotation] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None or set(reader.fieldnames) != set(ANNOTATION_CSV_FIELDS):
                raise DatasetError("CSV 欄位與標註格式不符")
            for row_number, row in enumerate(reader, start=2):
                try:
                    payload: dict[str, object] = dict(row)
                    payload["label"] = int(row["label"]) if row.get("label") else None
                    payload["sentence_index"] = row.get("sentence_index")
                    payload["rationale"] = row.get("rationale") or None
                    records.append(ClaimAnnotation.model_validate(payload))
                except (ValueError, ValidationError) as exc:
                    raise DatasetError(f"{path}:{row_number}: {exc}") from exc
    except OSError as exc:
        raise DatasetError(f"無法讀取 CSV：{path}") from exc
    validate_annotations(records, require_labels=False)
    return records


def prepare_annotations(
    articles: list[ArticleRecord],
    *,
    minimum_chars: int = 4,
) -> list[ClaimAnnotation]:
    if minimum_chars < 1:
        raise DatasetError("minimum_chars 必須大於 0")

    article_ids: set[str] = set()
    annotations: list[ClaimAnnotation] = []
    for article in articles:
        if article.article_id in article_ids:
            raise DatasetError(f"重複的 article_id：{article.article_id}")
        article_ids.add(article.article_id)
        seen_sentences: set[str] = set()
        group_id = article.group_id or article.article_id
        for sentence_index, sentence in enumerate(split_sentences(article.text)):
            if len(sentence) < minimum_chars or sentence in seen_sentences:
                continue
            seen_sentences.add(sentence)
            annotations.append(
                ClaimAnnotation(
                    id=f"{article.article_id}_s{sentence_index:04d}",
                    article_id=article.article_id,
                    group_id=group_id,
                    sentence_index=sentence_index,
                    text=sentence,
                    source_url=article.source_url,
                )
            )
    if not annotations:
        raise DatasetError("沒有產生可標註句子")
    return annotations


def validate_annotations(
    records: list[ClaimAnnotation],
    *,
    require_labels: bool,
) -> DatasetSummary:
    if not records:
        raise DatasetError("標註資料不可為空")

    ids: set[str] = set()
    sentence_keys: set[tuple[str, int]] = set()
    labels: Counter[int | None] = Counter()
    groups: set[str] = set()
    for record in records:
        if record.id in ids:
            raise DatasetError(f"重複的標註 id：{record.id}")
        ids.add(record.id)
        sentence_key = (record.article_id, record.sentence_index)
        if sentence_key in sentence_keys:
            raise DatasetError(f"文章句子重複：{record.article_id}#{record.sentence_index}")
        sentence_keys.add(sentence_key)
        if require_labels and record.label is None:
            raise DatasetError(f"尚未標註：{record.id}")
        labels[record.label] += 1
        groups.add(record.group_id)

    return DatasetSummary(
        records=len(records),
        groups=len(groups),
        positive=labels[1],
        negative=labels[0],
        unlabeled=labels[None],
    )


def audit_annotations(records: list[ClaimAnnotation]) -> AnnotationAudit:
    summary = validate_annotations(records, require_labels=False)
    text_groups: dict[str, list[str]] = defaultdict(list)
    lengths: list[int] = []
    questions = 0
    for record in records:
        normalized = "".join(record.text.lower().split())
        text_hash = sha256(normalized.encode()).hexdigest()
        text_groups[text_hash].append(record.id)
        lengths.append(len(record.text))
        questions += int(record.text.endswith(("?", "？")))
    duplicate_groups = [
        DuplicateSentenceGroup(text_sha256=text_hash, record_ids=sorted(record_ids))
        for text_hash, record_ids in sorted(text_groups.items())
        if len(record_ids) > 1
    ]
    return AnnotationAudit(
        summary=summary,
        minimum_characters=min(lengths),
        maximum_characters=max(lengths),
        mean_characters=sum(lengths) / len(lengths),
        questions=questions,
        duplicate_records=sum(len(group.record_ids) - 1 for group in duplicate_groups),
        duplicate_groups=duplicate_groups,
    )


def split_annotations(
    records: list[ClaimAnnotation],
    *,
    seed: int,
    train_ratio: float = 0.8,
    dev_ratio: float = 0.1,
) -> dict[str, list[ClaimAnnotation]]:
    summary = validate_annotations(records, require_labels=True)
    test_ratio = 1.0 - train_ratio - dev_ratio
    if not 0 < train_ratio < 1 or not 0 < dev_ratio < 1 or not 0 < test_ratio < 1:
        raise DatasetError("train/dev/test 比例都必須大於 0，且總和必須為 1")
    if summary.groups < 3:
        raise DatasetError("至少需要 3 個 group 才能建立 train/dev/test")

    grouped: dict[str, list[ClaimAnnotation]] = defaultdict(list)
    for record in records:
        grouped[record.group_id].append(record)

    group_ids = sorted(grouped)
    random.Random(seed).shuffle(group_ids)
    target_sizes = {
        "train": len(records) * train_ratio,
        "dev": len(records) * dev_ratio,
        "test": len(records) * test_ratio,
    }
    splits: dict[str, list[ClaimAnnotation]] = {"train": [], "dev": [], "test": []}
    split_groups: dict[str, set[str]] = {"train": set(), "dev": set(), "test": set()}

    # Place larger groups first and choose the split furthest below its target size.
    group_ids.sort(key=lambda group_id: len(grouped[group_id]), reverse=True)
    for index, group_id in enumerate(group_ids):
        remaining_groups = len(group_ids) - index
        empty_splits = [name for name, values in split_groups.items() if not values]
        if empty_splits and remaining_groups <= len(empty_splits):
            destination = empty_splits[0]
        else:
            destination = max(
                splits,
                key=lambda name: target_sizes[name] - len(splits[name]),
            )
        splits[destination].extend(grouped[group_id])
        split_groups[destination].add(group_id)

    for name, split in splits.items():
        labels = {record.label for record in split}
        if labels != {0, 1}:
            raise DatasetError(f"{name} split 必須同時包含正例與反例，請增加資料或調整 seed")
        split.sort(key=lambda record: (record.article_id, record.sentence_index))

    if any(split_groups[left] & split_groups[right] for left, right in _split_pairs()):
        raise DatasetError("group 洩漏到多個 split")
    return splits


def blind_sample_annotations(
    records: list[ClaimAnnotation],
    *,
    size: int,
    seed: int,
) -> list[ClaimAnnotation]:
    validate_annotations(records, require_labels=False)
    if size < 1:
        raise DatasetError("sample size 必須大於 0")
    if size > len(records):
        raise DatasetError("sample size 不可超過資料筆數")
    selected = random.Random(seed).sample(records, size)
    blinded = [record.model_copy(update={"label": None, "rationale": None}) for record in selected]
    blinded.sort(key=lambda record: record.id)
    return blinded


def _split_pairs() -> tuple[tuple[str, str], ...]:
    return (("train", "dev"), ("train", "test"), ("dev", "test"))
