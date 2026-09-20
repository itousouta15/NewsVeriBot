import argparse
import asyncio
from pathlib import Path

import httpx

from newsveribot.config import get_settings
from newsveribot.dataset import DatasetError, read_jsonl, write_jsonl
from newsveribot.feeds import FeedCollector, FeedSource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="收集公開 RSS/Atom 標題與摘要")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


async def _collect(manifest: Path, output: Path, report_path: Path) -> None:
    settings = get_settings()
    sources = read_jsonl(manifest, FeedSource)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        collector = FeedCollector(
            client,
            max_download_bytes=settings.max_download_bytes,
            max_redirects=settings.max_redirects,
        )
        articles, report = await collector.collect(sources)
    write_jsonl(output, articles)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(report.model_dump_json(indent=2))


def run() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(_collect(args.manifest, args.output, args.report))
    except DatasetError as exc:
        raise SystemExit(f"error: {exc}") from exc
