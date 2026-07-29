"""Admin and health-check slash commands."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from assistant.config import Settings
from assistant.scheduler.jobs import extraction_job, ics_sync_job, imap_sync_job

logger = logging.getLogger(__name__)

SYNC_TARGETS = {"imap", "calendar", "extract", "all"}


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.settings: Settings = bot.settings  # type: ignore[attr-defined]

    def _deny_unless_allowed(self, interaction: discord.Interaction) -> bool:
        if self.settings.is_user_allowed(interaction.user.id):
            return True
        logger.warning("Denied command from user %s", interaction.user.id)
        return False

    @app_commands.command(name="ping", description="Проверка дали Anabella е online")
    async def ping(self, interaction: discord.Interaction) -> None:
        if not self._deny_unless_allowed(interaction):
            await interaction.response.send_message(
                "Нямаш достъп до този бот.", ephemeral=True
            )
            return
        await interaction.response.send_message("pong", ephemeral=True)

    @app_commands.command(name="sync", description="Force IMAP, calendar или extraction")
    @app_commands.describe(target="Какво да синхронизирам")
    @app_commands.choices(
        target=[
            app_commands.Choice(name="all (imap + calendar + extract)", value="all"),
            app_commands.Choice(name="imap (email + extract)", value="imap"),
            app_commands.Choice(name="calendar", value="calendar"),
            app_commands.Choice(name="extract (payments only)", value="extract"),
        ]
    )
    async def sync(self, interaction: discord.Interaction, target: app_commands.Choice[str]) -> None:
        target_value = target.value
        if not self._deny_unless_allowed(interaction):
            await interaction.response.send_message(
                "Нямаш достъп до този бот.", ephemeral=True
            )
            return
        if target_value not in SYNC_TARGETS:
            await interaction.response.send_message(
                "Невалидна цел. Ползвай: imap, calendar, extract, all.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        async def run_sync() -> None:
            secret_box = self.bot.secret_box  # type: ignore[attr-defined]
            try:
                if target_value in {"imap", "all"}:
                    await imap_sync_job(self.bot, self.settings, secret_box)
                elif target_value == "extract":
                    await extraction_job(self.bot, self.settings)
                if target_value in {"calendar", "all"}:
                    await ics_sync_job(self.bot, self.settings, secret_box)

                channels = ["#general"]
                if target_value in {"imap", "extract", "all"}:
                    channels.append("#payments")
                await interaction.followup.send(
                    f"Sync завърши (`{target_value}`). Виж {', '.join(channels)}.",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("Manual /sync failed for target=%s", target_value)
                await interaction.followup.send(
                    f"Sync (`{target_value}`) се провали — виж логовете на бота.",
                    ephemeral=True,
                )

        asyncio.create_task(run_sync())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
