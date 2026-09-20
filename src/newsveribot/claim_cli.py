import argparse
import json
import sys
from pathlib import Path

from newsveribot.annotation import AnnotationStore
from newsveribot.claim_model import save_artifact, train_baseline
from newsveribot.dataset import (
    ArticleRecord,
    ClaimAnnotation,
    DatasetError,
    blind_sample_annotations,
    prepare_annotations,
    read_annotation_csv,
    read_jsonl,
    split_annotations,
    validate_annotations,
    write_annotation_csv,
    write_jsonl,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NewsVeriBot 模型 A 資料與 baseline 工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="將文章 JSONL 切成待標註句子")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--minimum-chars", type=int, default=4)

    validate = subparsers.add_parser("validate", help="驗證標註 JSONL")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--allow-unlabeled", action="store_true")

    export_csv = subparsers.add_parser("export-csv", help="將標註 JSONL 匯出為 Excel 相容 CSV")
    export_csv.add_argument("--input", type=Path, required=True)
    export_csv.add_argument("--output", type=Path, required=True)

    import_csv = subparsers.add_parser("import-csv", help="將標註 CSV 驗證並轉回 JSONL")
    import_csv.add_argument("--input", type=Path, required=True)
    import_csv.add_argument("--output", type=Path, required=True)

    split = subparsers.add_parser("split", help="依 group 建立 train/dev/test")
    split.add_argument("--input", type=Path, required=True)
    split.add_argument("--output-dir", type=Path, required=True)
    split.add_argument("--seed", type=int, default=42)
    split.add_argument("--train-ratio", type=float, default=0.8)
    split.add_argument("--dev-ratio", type=float, default=0.1)

    sample = subparsers.add_parser("sample", help="建立不含原標籤的可重現抽樣")
    sample.add_argument("--input", type=Path, required=True)
    sample.add_argument("--output", type=Path, required=True)
    sample.add_argument("--size", type=int, required=True)
    sample.add_argument("--seed", type=int, default=42)

    train = subparsers.add_parser("train", help="訓練 TF-IDF + Logistic Regression baseline")
    train.add_argument("--data-dir", type=Path, required=True)
    train.add_argument("--model-output", type=Path, required=True)
    train.add_argument("--report-output", type=Path, required=True)
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--target-recall", type=float, default=0.82)

    agreement = subparsers.add_parser("agreement", help="計算兩組標註的 Cohen's kappa")
    agreement.add_argument("--claims", type=Path, required=True)
    agreement.add_argument("--events", type=Path, required=True)
    agreement.add_argument("--annotator-a", required=True)
    agreement.add_argument("--pass-a", default="initial")
    agreement.add_argument("--annotator-b", required=True)
    agreement.add_argument("--pass-b", default="initial")

    finalize = subparsers.add_parser("finalize", help="將指定標註輪次匯整成訓練 JSONL")
    finalize.add_argument("--claims", type=Path, required=True)
    finalize.add_argument("--events", type=Path, required=True)
    finalize.add_argument("--annotator", required=True)
    finalize.add_argument("--pass-id", default="initial")
    finalize.add_argument("--output", type=Path, required=True)
    finalize.add_argument("--allow-incomplete", action="store_true")
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _execute(args: argparse.Namespace) -> None:
    if args.command == "prepare":
        articles = read_jsonl(args.input, ArticleRecord)
        annotations = prepare_annotations(articles, minimum_chars=args.minimum_chars)
        write_jsonl(args.output, annotations)
        _print_json({"articles": len(articles), "sentences": len(annotations)})
        return

    if args.command == "validate":
        records = read_jsonl(args.input, ClaimAnnotation)
        summary = validate_annotations(records, require_labels=not args.allow_unlabeled)
        _print_json(summary.model_dump())
        return

    if args.command == "export-csv":
        records = read_jsonl(args.input, ClaimAnnotation)
        write_annotation_csv(args.output, records)
        _print_json({"records": len(records), "output": str(args.output)})
        return

    if args.command == "import-csv":
        records = read_annotation_csv(args.input)
        write_jsonl(args.output, records)
        _print_json({"records": len(records), "output": str(args.output)})
        return

    if args.command == "split":
        records = read_jsonl(args.input, ClaimAnnotation)
        splits = split_annotations(
            records,
            seed=args.seed,
            train_ratio=args.train_ratio,
            dev_ratio=args.dev_ratio,
        )
        for name, split_records in splits.items():
            write_jsonl(args.output_dir / f"{name}.jsonl", split_records)
        _print_json({name: len(split_records) for name, split_records in splits.items()})
        return

    if args.command == "sample":
        records = read_jsonl(args.input, ClaimAnnotation)
        sampled = blind_sample_annotations(records, size=args.size, seed=args.seed)
        write_jsonl(args.output, sampled)
        _print_json({"records": len(sampled), "output": str(args.output), "seed": args.seed})
        return

    if args.command == "train":
        if not 0 < args.target_recall <= 1:
            raise DatasetError("target-recall 必須介於 0 與 1 之間")
        train_records = read_jsonl(args.data_dir / "train.jsonl", ClaimAnnotation)
        dev_records = read_jsonl(args.data_dir / "dev.jsonl", ClaimAnnotation)
        test_records = read_jsonl(args.data_dir / "test.jsonl", ClaimAnnotation)
        artifact, baseline_report = train_baseline(
            train_records,
            dev_records,
            test_records,
            seed=args.seed,
            target_recall=args.target_recall,
        )
        save_artifact(args.model_output, artifact)
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(
            baseline_report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        _print_json(baseline_report.model_dump(mode="json"))
        return

    if args.command == "agreement":
        store = AnnotationStore(args.claims, args.events)
        agreement_report = store.agreement(
            annotator_a=args.annotator_a,
            pass_a=args.pass_a,
            annotator_b=args.annotator_b,
            pass_b=args.pass_b,
        )
        _print_json(agreement_report.model_dump())
        return

    if args.command == "finalize":
        store = AnnotationStore(args.claims, args.events)
        finalized = store.finalize(
            annotator_id=args.annotator,
            pass_id=args.pass_id,
            output_path=args.output,
            require_complete=not args.allow_incomplete,
        )
        _print_json({"records": len(finalized), "output": str(args.output)})
        return

    raise DatasetError(f"未知指令：{args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _execute(args)
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def run() -> None:
    raise SystemExit(main())
