import asyncio

import discord
import httpx
from discord import app_commands

from newsveribot.config import get_settings
from newsveribot.schemas import AnalysisResponse

EMBED_COLOR = 0x2563EB


def _truncate(text: str, length: int) -> str:
    if len(text) <= length:
        return text
    return f"{text[: length - 1]}…"


def _format_claim(index: int, response: AnalysisResponse) -> tuple[str, str]:
    analysis = response.claims[index]
    lines = [f"可信查核價值分數：{analysis.claim.checkworthiness_score:.2f}"]
    if analysis.candidates:
        for rank, candidate in enumerate(analysis.candidates, start=1):
            label = candidate.title or candidate.reviewed_claim
            rating = f"，評定：{candidate.rating}" if candidate.rating else ""
            lines.append(
                f"{rank}. [{_truncate(label, 160)}]({candidate.review_url})"
                f"（{candidate.publisher}{rating}）"
            )
    else:
        lines.append("尚未找到相關查核報告。這不代表主張為真。")
    return _truncate(analysis.claim.text, 256), _truncate("\n".join(lines), 1024)


def build_embed(response: AnalysisResponse) -> discord.Embed:
    embed = discord.Embed(
        title=response.source.title or "NewsVeriBot 分析結果",
        description=response.disclaimer,
        color=EMBED_COLOR,
    )
    for index in range(min(len(response.claims), 5)):
        name, value = _format_claim(index, response)
        embed.add_field(name=name, value=value, inline=False)
    if not response.claims:
        embed.add_field(name="結果", value="沒有找到明確且值得查核的主張。", inline=False)
    if response.warnings:
        embed.add_field(
            name="注意",
            value=_truncate("\n".join(f"• {warning}" for warning in response.warnings), 1024),
            inline=False,
        )
    return embed


class NewsVeriBotClient(discord.Client):
    def __init__(self, *, api_base_url: str, guild_id: int | None) -> None:
        super().__init__(intents=discord.Intents.none())
        self.tree = app_commands.CommandTree(self)
        self.api_base_url = api_base_url.rstrip("/")
        self.guild_id = guild_id
        self.http_client = httpx.AsyncClient(timeout=30, trust_env=False)

    async def setup_hook(self) -> None:
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def close(self) -> None:
        await self.http_client.aclose()
        await super().close()


def create_bot(api_base_url: str, guild_id: int | None) -> NewsVeriBotClient:
    bot = NewsVeriBotClient(api_base_url=api_base_url, guild_id=guild_id)

    @bot.tree.command(name="verify", description="分析新聞文字或公開網址")
    @app_commands.describe(target="要分析的新聞文字或 HTTP(S) 網址")
    async def verify(interaction: discord.Interaction, target: str) -> None:
        await interaction.response.defer(thinking=True)
        payload = (
            {"url": target} if target.startswith(("http://", "https://")) else {"text": target}
        )
        try:
            api_response = await bot.http_client.post(
                f"{bot.api_base_url}/v1/analyze",
                json=payload,
            )
            api_response.raise_for_status()
            result = AnalysisResponse.model_validate(api_response.json())
        except (httpx.HTTPError, ValueError) as exc:
            await interaction.followup.send(
                f"分析服務目前無法完成請求：{_truncate(str(exc), 300)}",
                ephemeral=True,
            )
            return
        await interaction.followup.send(embed=build_embed(result))

    return bot


async def _start() -> None:
    settings = get_settings()
    if settings.discord_bot_token is None:
        raise RuntimeError("尚未設定 DISCORD_BOT_TOKEN")
    bot = create_bot(settings.api_base_url, settings.discord_guild_id)
    await bot.start(settings.discord_bot_token.get_secret_value())


def run() -> None:
    asyncio.run(_start())
