"""Discord bot client."""

import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from assistant.config import Settings
from assistant.crypto import SecretBox
from assistant.ingest.imap_idle import start_imap_idle_monitors
from assistant.scheduler.jobs import ics_sync_job

logger = logging.getLogger(__name__)


def _log_background_task(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Background sync task failed")


def _spawn_background(coro) -> None:
    task = asyncio.create_task(coro)
    task.add_done_callback(_log_background_task)


class AssistantBot(commands.Bot):
    def __init__(self, settings: Settings, secret_box: SecretBox) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.secret_box = secret_box
        self.scheduler: AsyncIOScheduler | None = None
        self._startup_done = False

    async def setup_hook(self) -> None:
        await self.load_extension("assistant.discord_bot.cogs.admin")
        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        command_names = [command.name for command in synced]
        logger.info(
            "Synced %d slash command(s) to guild %s: %s",
            len(synced),
            guild.id,
            ", ".join(command_names) or "(none)",
        )

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        if self._startup_done:
            return
        self._startup_done = True
        if self.scheduler is not None:
            self.scheduler.start()
            logger.info("Starting calendar sync on startup and IMAP IDLE monitors")
            _spawn_background(
                ics_sync_job(
                    self,
                    self.settings,
                    self.secret_box,
                    notify_if_unchanged=True,
                )
            )
            _spawn_background(start_imap_idle_monitors(self, self.settings, self.secret_box))

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        logger.exception("App command error: %s", error)
        message = "Възникна грешка при обработката на командата."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def create_bot(settings: Settings, secret_box: SecretBox) -> AssistantBot:
    return AssistantBot(settings, secret_box)
