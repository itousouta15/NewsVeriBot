from pathlib import Path

import httpx
import pytest

from newsveribot.annotation import AnnotationStore
from newsveribot.annotation_app import create_annotation_app
from newsveribot.dataset import ClaimAnnotation, DatasetError, read_jsonl, write_jsonl


def _claims() -> list[ClaimAnnotation]:
    return [
        ClaimAnnotation(
            id=f"claim_{index}",
            article_id=f"article_{index}",
            group_id=f"group_{index}",
            sentence_index=0,
            text=f"政府宣布2026年第{index}項政策。",
            source_url=f"https://example.com/{index}",
        )
        for index in range(4)
    ]


def _store(tmp_path: Path) -> AnnotationStore:
    claims_path = tmp_path / "claims.jsonl"
    write_jsonl(claims_path, _claims())
    return AnnotationStore(claims_path, tmp_path / "events.jsonl", seed=42)


def test_store_keeps_append_only_revisions_and_latest_value(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.next_claim("researcher", "initial")
    assert claim is not None
    store.save(
        claim_id=claim.id,
        annotator_id="researcher",
        pass_id="initial",
        label=1,
        rationale="包含具體政策宣稱",
    )
    store.save(
        claim_id=claim.id,
        annotator_id="researcher",
        pass_id="initial",
        label=0,
        rationale="重新判斷為背景資訊",
    )

    assert len(store.events()) == 2
    assert store.stats("researcher", "initial").completed == 1
    assert store.latest_decisions()[(claim.id, "researcher", "initial")].label == 0


def test_agreement_and_finalize(tmp_path: Path) -> None:
    store = _store(tmp_path)
    labels_a = [1, 1, 0, 0]
    labels_b = [1, 0, 0, 0]
    for claim, label_a, label_b in zip(_claims(), labels_a, labels_b, strict=True):
        store.save(
            claim_id=claim.id,
            annotator_id="a",
            pass_id="initial",
            label=label_a,
            rationale="第一組測試標註",
        )
        store.save(
            claim_id=claim.id,
            annotator_id="b",
            pass_id="initial",
            label=label_b,
            rationale="第二組測試標註",
        )

    report = store.agreement(
        annotator_a="a",
        pass_a="initial",
        annotator_b="b",
        pass_b="initial",
    )
    output = tmp_path / "finalized.jsonl"
    finalized = store.finalize(
        annotator_id="a",
        pass_id="initial",
        output_path=output,
    )

    assert report.overlap == 4
    assert report.agreements == 3
    assert report.cohen_kappa == pytest.approx(0.5)
    assert len(finalized) == 4
    assert all(record.label is not None for record in read_jsonl(output, ClaimAnnotation))


def test_finalize_requires_complete_pass(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _claims()[0]
    store.save(
        claim_id=first.id,
        annotator_id="researcher",
        pass_id="initial",
        label=1,
        rationale="只有一筆標註",
    )
    with pytest.raises(DatasetError, match="未標註"):
        store.finalize(
            annotator_id="researcher",
            pass_id="initial",
            output_path=tmp_path / "finalized.jsonl",
        )


async def test_annotation_api_returns_next_and_saves_decision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    transport = httpx.ASGITransport(app=create_annotation_app(store))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        page_response = await client.get("/")
        first_response = await client.get(
            "/api/next",
            params={"annotator_id": "researcher", "pass_id": "initial"},
        )
        claim = first_response.json()["claim"]
        save_response = await client.post(
            "/api/decisions",
            json={
                "claim_id": claim["id"],
                "annotator_id": "researcher",
                "pass_id": "initial",
                "label": 1,
            },
        )
        next_response = await client.get(
            "/api/next",
            params={"annotator_id": "researcher", "pass_id": "initial"},
        )

    assert page_response.status_code == 200
    assert "NewsVeriBot 標註工作台" in page_response.text
    assert first_response.status_code == 200
    assert save_response.status_code == 200
    assert save_response.json()["rationale"] is None
    assert next_response.json()["stats"]["completed"] == 1
    assert next_response.json()["claim"]["id"] != claim["id"]
