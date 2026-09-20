from newsveribot.claims import RuleBasedClaimDetector, split_sentences


def test_split_sentences_handles_chinese_punctuation() -> None:
    assert split_sentences("第一句。第二句！第三句？") == ["第一句。", "第二句！", "第三句？"]


def test_detector_finds_verifiable_claim_and_ignores_opinion() -> None:
    detector = RuleBasedClaimDetector()
    results = detector.detect(
        "政府宣布2026年1月起補助提高20%。我覺得這個政策很棒。",
        limit=5,
    )
    assert len(results) == 1
    assert results[0].text == "政府宣布2026年1月起補助提高20%。"
    assert results[0].checkworthiness_score >= 0.8


def test_detector_respects_limit() -> None:
    detector = RuleBasedClaimDetector()
    results = detector.detect("研究顯示風險提高20%。政府宣布補助增加30%。", limit=1)
    assert len(results) == 1
