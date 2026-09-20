# 資料管理

`raw/`、`interim/`、`processed/` 的實際資料預設不進 Git，只保留資料字典、產生腳本與不可逆雜湊。

## 原則

- 優先保存 URL、擷取時間、內容雜湊與必要短片段，不重新散布完整新聞正文。
- 每筆資料記錄來源、授權或使用依據。
- train/dev/test 依文章、事件與時間切分，避免同事件洩漏。
- 使用者輸入不得混入訓練集，除非另行取得明確同意並完成去識別化。
- API key、Discord token 和任何個資不得放入資料檔。

## 建議格式

原始文章使用 JSON Lines，每列必須記錄來源與使用依據：

```json
{"article_id":"news_001","group_id":"event_001","title":"範例","text":"文章全文","source_url":"https://example.com/news/1","source_name":"範例來源","retrieved_at":"2026-09-20T12:00:00+08:00","rights_note":"僅供研究標註，不重新散布"}
```

`group_id` 代表同一事件或高度相關報導。未填時會使用 `article_id`，但正式資料應盡可能人工整理事件群組。

主張標註也使用 JSON Lines：

```json
{"id":"news_001_s0003","article_id":"news_001","group_id":"event_001","sentence_index":3,"text":"2026年起新法上路。","label":1,"rationale":"具體時間與政策宣稱","source_url":"https://example.com/article","guideline_version":"1.0"}
```

重排資料以 query group 保存，禁止將同一 query 的 candidates 拆到不同資料集合。

待標註 JSONL 可用 `newsveribot-claims export-csv` 轉成帶 UTF-8 BOM 的 CSV，在 Excel 或 Google Sheets 填寫後，再用 `import-csv` 驗證並轉回 JSONL。研究流程一律以驗證後的 JSONL 為準。

瀏覽器工作台不直接修改 claim JSONL，而是將每次判斷附加至 `annotation_events.jsonl`。事件包含 claim、標註者、輪次、標籤、理由、準則版本與 UTC 時間，可保留修訂歷史並計算一致性。使用 `finalize` 選定最終輪次後才產生訓練資料。

## 模型 A 流程

```text
articles.jsonl
  -> newsveribot-claims prepare
  -> claim_annotations.jsonl（人工填 label/rationale）
     或 newsveribot-annotate -> annotation_events.jsonl -> finalize
  -> newsveribot-claims validate
  -> newsveribot-claims split
  -> train.jsonl / dev.jsonl / test.jsonl
  -> newsveribot-claims train
```

切分會以 `group_id` 為單位，並要求每個 split 都同時具有正例與反例。閾值只在 dev set 選擇，test set 不參與模型或閾值調整。
