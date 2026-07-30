"""Admin and health-check slash commands."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from assistant.config import Settings
from assistant.scheduler.jobs import (
    event_extraction_job,
    ics_sync_job,
    imap_sync_job,
    payment_extraction_job,
)

logger = logging.getLogger(__name__)

SYNC_TARGETS = {"imap", "calendar", "extract", "events", "payments", "all"}


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
            app_commands.Choice(name="all (imap + calendar + extract + events)", value="all"),
            app_commands.Choice(name="imap (email + extract + events)", value="imap"),
            app_commands.Choice(name="calendar", value="calendar"),
            app_commands.Choice(name="payments (Payment label only)", value="payments"),
            app_commands.Choice(name="extract (#payments or #events)", value="extract"),
            app_commands.Choice(name="events (DevBG/Udemy/LocalAGI only)", value="events"),
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
                "Невалидна цел. Ползвай: imap, calendar, payments, extract, events, all.",
                ephemeral=True,
            )
            return
        if interaction.channel_id is None:
            await interaction.response.send_message(
                "Не мога да определя канала за отговор.", ephemeral=True
            )
            return

        reply_channel_id = interaction.channel_id
        post_in_channel = target_value in {"events", "extract", "payments"}
        await interaction.response.defer(
            ephemeral=not post_in_channel,
            thinking=True,
        )

        async def run_sync() -> None:
            secret_box = self.bot.secret_box  # type: ignore[attr-defined]
            try:
                if target_value in {"imap", "all"}:
                    await imap_sync_job(self.bot, self.settings, secret_box)
                elif target_value == "payments":
                    await payment_extraction_job(
                        self.bot,
                        self.settings,
                        reply_channel_id=reply_channel_id,
                        interaction=interaction,
                    )
                elif target_value == "extract":
                    if reply_channel_id == self.settings.discord_channel_payments:
                        await payment_extraction_job(
                            self.bot,
                            self.settings,
                            reply_channel_id=reply_channel_id,
                            interaction=interaction,
                        )
                    elif reply_channel_id == self.settings.discord_channel_events:
                        await event_extraction_job(
                            self.bot,
                            self.settings,
                            reply_channel_id=reply_channel_id,
                            interaction=interaction,
                        )
                    else:
                        await interaction.edit_original_response(
                            content=(
                                "📋 **`/sync extract`** работи само в `#payments` или `#events`.\n"
                                "Ползвай **`/sync payments`** или **`/sync events`**."
                            )
                        )
                elif target_value == "events":
                    await event_extraction_job(
                        self.bot,
                        self.settings,
                        reply_channel_id=reply_channel_id,
                        interaction=interaction,
                    )
                if target_value in {"calendar", "all"}:
                    await ics_sync_job(self.bot, self.settings, secret_box)

                if not post_in_channel:
                    await interaction.followup.send(
                        f"Sync завърши (`{target_value}`).",
                        ephemeral=True,
                    )
            except Exception:
                logger.exception("Manual /sync failed for target=%s", target_value)
                error_text = f"Sync (`{target_value}`) се провали — виж логовете на бота."
                if post_in_channel:
                    await interaction.edit_original_response(content=error_text)
                else:
                    await interaction.followup.send(error_text, ephemeral=True)

        asyncio.create_task(run_sync())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
