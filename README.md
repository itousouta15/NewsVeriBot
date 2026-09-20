# NewsVeriBot

NewsVeriBot 是以證據為中心的繁體中文事實查核輔助系統。它會從文字或網頁中找出值得查核的主張，查詢既有 ClaimReview 資料，並將最相關的查核報告排在前面。

系統不會替使用者宣判內容真假。查無資料只代表目前沒有找到相關查核報告。

## 目前功能

- `POST /v1/analyze` 接受純文字或公開 HTTP(S) URL。
- URL 擷取會限制協定、重新導向、回應大小，並阻擋私有與保留 IP。
- 可解釋的規則式主張偵測 baseline。
- Google Fact Check Tools API adapter；沒有 API key 時安全降級。
- 字元 n-gram 與數字一致性的重排 baseline。
- 模型 A 的文章切句、標註驗證、group-aware split 與訓練 CLI。
- 可載入 TF-IDF + Logistic Regression 模型；未設定時使用規則 baseline。
- Discord `/verify` 指令 adapter。
- 單元測試、Ruff、mypy 與 GitHub Actions CI。

## 快速開始

需求：Python 3.12 與 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --dev
cp .env.example .env
uv run uvicorn newsveribot.api:app --reload
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.example .env
uv run uvicorn newsveribot.api:app --reload
```

健康檢查：

```bash
curl http://127.0.0.1:8000/health
```

文字分析：

```bash
curl -X POST http://127.0.0.1:8000/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"衛生單位宣布，2026年1月起將實施新的疫苗政策。"}'
```

只能提供 `text` 或 `url` 其中一個。設定 `GOOGLE_FACT_CHECK_API_KEY` 後，分析結果才會包含線上查核候選。

## Discord Bot

在 `.env` 設定 `DISCORD_BOT_TOKEN`。開發時可設定 `DISCORD_GUILD_ID`，讓 slash command 立即同步至單一伺服器。

```bash
uv run newsveribot-discord
```

Discord adapter 透過 `NEWSVERIBOT_API_BASE_URL` 呼叫 API，因此應先啟動 API。

## 模型 A 資料與 baseline

先準備符合 `data/README.md` 格式的文章 JSONL：

```bash
uv run newsveribot-claims prepare \
  --input data/raw/articles.jsonl \
  --output data/interim/claim_annotations.jsonl
```

完成 `label` 與 `rationale` 後，驗證並依 `group_id` 切分：

```bash
uv run newsveribot-claims export-csv \
  --input data/interim/claim_annotations.jsonl \
  --output data/interim/claim_annotations.csv
# 在 Excel 或 Google Sheets 填寫 label 與 rationale 後：
uv run newsveribot-claims import-csv \
  --input data/interim/claim_annotations.csv \
  --output data/interim/claim_annotations.jsonl
uv run newsveribot-claims validate --input data/interim/claim_annotations.jsonl
uv run newsveribot-claims split \
  --input data/interim/claim_annotations.jsonl \
  --output-dir data/processed \
  --seed 42
```

訓練 baseline：

```bash
uv run newsveribot-claims train \
  --data-dir data/processed \
  --model-output models/claim_detector.joblib \
  --report-output reports/model_a_baseline.json \
  --target-recall 0.82
```

將 `NEWSVERIBOT_CLAIM_MODEL_PATH` 指向模型檔後，API 啟動時會載入它。Joblib 可以執行序列化物件，只能載入自己訓練或可信來源提供的檔案。

## 本機標註工作台

`prepare` 產生待標註 JSONL 後，可啟動瀏覽器工作台：

```bash
uv run newsveribot-annotate \
  --claims data/interim/claim_annotations.jsonl \
  --events data/interim/annotation_events.jsonl
```

開啟 <http://127.0.0.1:8010>。工作台預設只監聽 loopback，沒有登入機制，不應公開部署。每次儲存都會附加事件，不會覆蓋先前判斷。

同一人可用 `initial` 與 `retest` 兩輪進行盲重標，再計算 intra-rater Cohen's kappa：

```bash
uv run newsveribot-claims sample \
  --input data/interim/claim_annotations.jsonl \
  --output data/interim/retest_sample.jsonl \
  --size 50 --seed 42
uv run newsveribot-annotate \
  --claims data/interim/retest_sample.jsonl \
  --events data/interim/annotation_events.jsonl
# 在網頁將輪次改成 retest
uv run newsveribot-claims agreement \
  --claims data/interim/claim_annotations.jsonl \
  --events data/interim/annotation_events.jsonl \
  --annotator-a researcher_1 --pass-a initial \
  --annotator-b researcher_1 --pass-b retest
```

若有衝突，使用新的 `adjudicated` 輪次完成最終判斷，之後匯整成訓練資料：

```bash
uv run newsveribot-claims finalize \
  --claims data/interim/claim_annotations.jsonl \
  --events data/interim/annotation_events.jsonl \
  --annotator researcher_1 --pass-id adjudicated \
  --output data/interim/claim_annotations.final.jsonl
```

## 品質檢查

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## 研究狀態

目前提供規則式與 TF-IDF 主張偵測 baseline；語義模型 A 與模型 B 尚未訓練。實驗結果必須由固定資料切分與評估腳本產生，不會在程式碼中預填計畫書的目標分數。

資料規範見 `data/README.md`，系統邊界見 `docs/ARCHITECTURE.md`，標註規則見 `docs/ANNOTATION_GUIDELINE.md`。
