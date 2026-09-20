import json
import os
import threading
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from newsveribot.dataset import ClaimAnnotation, DatasetError, read_jsonl, write_jsonl


class AnnotationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    claim_id: str = Field(min_length=1)
    annotator_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    pass_id: str = Field(
        default="initial", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    label: Literal[0, 1]
    rationale: str | None = Field(default=None, min_length=3, max_length=1_000)
    guideline_version: str = Field(default="1.0", min_length=1)
    annotated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnnotationStats(BaseModel):
    total: int
    completed: int
    remaining: int
    positive: int
    negative: int


class AgreementReport(BaseModel):
    overlap: int
    agreements: int
    observed_agreement: float = Field(ge=0, le=1)
    expected_agreement: float = Field(ge=0, le=1)
    cohen_kappa: float = Field(ge=-1, le=1)
    both_positive: int
    both_negative: int
    a_positive_b_negative: int
    a_negative_b_positive: int


class AnnotationStore:
    def __init__(self, claims_path: Path, events_path: Path, *, seed: int = 42) -> None:
        claims = read_jsonl(claims_path, ClaimAnnotation)
        if not claims:
            raise DatasetError("標註工作台沒有可用句子")
        claim_ids = [claim.id for claim in claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise DatasetError("標註工作台包含重複 claim id")
        self._claims = {claim.id: claim for claim in claims}
        self._ordered_ids = sorted(
            self._claims,
            key=lambda claim_id: sha256(f"{seed}:{claim_id}".encode()).hexdigest(),
        )
        self.events_path = events_path
        self._lock = threading.RLock()

    def events(self) -> list[AnnotationDecision]:
        with self._lock:
            if not self.events_path.exists():
                return []
            return read_jsonl(self.events_path, AnnotationDecision)

    def latest_decisions(self) -> dict[tuple[str, str, str], AnnotationDecision]:
        latest: dict[tuple[str, str, str], AnnotationDecision] = {}
        for event in self.events():
            key = (event.claim_id, event.annotator_id, event.pass_id)
            latest[key] = event
        return latest

    def save(
        self,
        *,
        claim_id: str,
        annotator_id: str,
        pass_id: str,
        label: Literal[0, 1],
        rationale: str | None,
    ) -> AnnotationDecision:
        if claim_id not in self._claims:
            raise DatasetError(f"找不到 claim：{claim_id}")
        claim = self._claims[claim_id]
        decision = AnnotationDecision(
            claim_id=claim_id,
            annotator_id=annotator_id,
            pass_id=pass_id,
            label=label,
            rationale=(rationale.strip() or None) if rationale is not None else None,
            guideline_version=claim.guideline_version,
        )
        with self._lock:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.events_path.open("a", encoding="utf-8", newline="\n") as destination:
                    destination.write(
                        json.dumps(
                            decision.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                        )
                    )
                    destination.write("\n")
                    destination.flush()
                    os.fsync(destination.fileno())
            except OSError as exc:
                raise DatasetError(f"無法寫入標註事件：{self.events_path}") from exc
        return decision

    def stats(self, annotator_id: str, pass_id: str) -> AnnotationStats:
        latest = self.latest_decisions()
        decisions = [
            decision
            for (claim_id, annotator, annotation_pass), decision in latest.items()
            if claim_id in self._claims and annotator == annotator_id and annotation_pass == pass_id
        ]
        labels = Counter(decision.label for decision in decisions)
        completed = len(decisions)
        return AnnotationStats(
            total=len(self._claims),
            completed=completed,
            remaining=len(self._claims) - completed,
            positive=labels[1],
            negative=labels[0],
        )

    def next_claim(self, annotator_id: str, pass_id: str) -> ClaimAnnotation | None:
        latest = self.latest_decisions()
        for claim_id in self._ordered_ids:
            if (claim_id, annotator_id, pass_id) not in latest:
                return self._claims[claim_id]
        return None

    def agreement(
        self,
        *,
        annotator_a: str,
        pass_a: str,
        annotator_b: str,
        pass_b: str,
    ) -> AgreementReport:
        latest = self.latest_decisions()
        labels_a = {
            claim_id: decision.label
            for (claim_id, annotator, annotation_pass), decision in latest.items()
            if annotator == annotator_a and annotation_pass == pass_a
        }
        labels_b = {
            claim_id: decision.label
            for (claim_id, annotator, annotation_pass), decision in latest.items()
            if annotator == annotator_b and annotation_pass == pass_b
        }
        overlap_ids = sorted(set(labels_a) & set(labels_b) & set(self._claims))
        if not overlap_ids:
            raise DatasetError("兩組標註沒有重疊項目")

        pairs = [(labels_a[claim_id], labels_b[claim_id]) for claim_id in overlap_ids]
        both_positive = sum(left == 1 and right == 1 for left, right in pairs)
        both_negative = sum(left == 0 and right == 0 for left, right in pairs)
        a_positive_b_negative = sum(left == 1 and right == 0 for left, right in pairs)
        a_negative_b_positive = sum(left == 0 and right == 1 for left, right in pairs)
        overlap = len(pairs)
        agreements = both_positive + both_negative
        observed = agreements / overlap
        a_positive_rate = sum(left == 1 for left, _ in pairs) / overlap
        b_positive_rate = sum(right == 1 for _, right in pairs) / overlap
        expected = a_positive_rate * b_positive_rate + (1 - a_positive_rate) * (1 - b_positive_rate)
        kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
        return AgreementReport(
            overlap=overlap,
            agreements=agreements,
            observed_agreement=observed,
            expected_agreement=expected,
            cohen_kappa=kappa,
            both_positive=both_positive,
            both_negative=both_negative,
            a_positive_b_negative=a_positive_b_negative,
            a_negative_b_positive=a_negative_b_positive,
        )

    def finalize(
        self,
        *,
        annotator_id: str,
        pass_id: str,
        output_path: Path,
        require_complete: bool = True,
    ) -> list[ClaimAnnotation]:
        latest = self.latest_decisions()
        finalized: list[ClaimAnnotation] = []
        missing: list[str] = []
        for claim_id in self._ordered_ids:
            decision = latest.get((claim_id, annotator_id, pass_id))
            if decision is None:
                missing.append(claim_id)
                continue
            finalized.append(
                self._claims[claim_id].model_copy(
                    update={"label": decision.label, "rationale": decision.rationale}
                )
            )
        if require_complete and missing:
            raise DatasetError(f"尚有 {len(missing)} 筆未標註，無法匯整")
        if not finalized:
            raise DatasetError("沒有可匯整的標註")
        write_jsonl(output_path, finalized)
        return finalized
