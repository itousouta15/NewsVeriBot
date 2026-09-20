# 第一批標註資料快照

## 收集資訊

- 收集時間：2026-09-20 14:57 UTC
- 資料用途：模型 A 標註流程 pilot
- 原始資料：公開 RSS/Atom 提供的標題與摘要
- 文章全文：未下載、未保存
- 收集失敗：0
- 內容雜湊重複：0

## 來源分布

| 來源 | Feed | 納入項目 | 內容範圍 |
|---|---|---:|---|
| BBC 中文 | `https://feeds.bbci.co.uk/zhongwen/trad/rss.xml` | 20 | 標題與摘要 |
| 台灣事實查核中心 | `https://tfc-taiwan.org.tw/feed/` | 10 | 標題與摘要 |
| 自由時報 | `https://news.ltn.com.tw/rss/all.xml` | 20 | 僅標題，摘要多為截斷內容 |

## 句子 Audit

| 項目 | 數值 |
|---|---:|
| 文章數 | 50 |
| 待標註句子 | 116 |
| 群組數 | 50 |
| 跨文章重複句 | 0 |
| 平均字數 | 28.76 |
| 最短字數 | 5 |
| 最長字數 | 89 |
| 問句 | 21 |

## 本機產物

- `data/raw/rss_articles.jsonl`
- `data/raw/rss_collection.report.json`
- `data/interim/claim_annotations.jsonl`
- `data/interim/pilot_50.jsonl`（固定 seed 42；50 句、35 個群組）
- `data/interim/pilot_50_events.jsonl`（append-only 人工與 AI 標註事件）
- `data/interim/pilot_50.ai_suggested.jsonl`（AI 初標：22 正例、28 負例）
- `data/interim/pilot_50_ai_review.jsonl`（AI 初標的低信心人工複核清單）
- `data/interim/pilot_50_review_claims.jsonl`（不顯示 AI 答案的 10 句盲審子集）

以上檔案均受 `.gitignore` 排除，避免重新散布來源內容。AI 初標使用獨立的
`ai_assistant/suggestion` 身份，不能冒充人工 gold labels，也不能在未經人工複核前當作研究結果。

## 切分前工作

目前每篇文章暫時各自使用一個 `group_id`。正式切分前必須人工確認跨媒體的同事件報導，將相關項目歸到相同事件群組，避免事件洩漏到 train/dev/test。
