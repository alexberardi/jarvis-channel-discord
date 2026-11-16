"""Discord channel for Jarvis.

Holds a Discord bot's connection and hands Jarvis what linked people send: in
a direct message, in the one Jarvis channel, or in a thread of that channel.
Jarvis decides who an account is and what to answer (the SDK's ``Channel``);
this file only knows Discord.

Accounts that are not linked get no sign that anything is here: no reply, no
reaction, no typing indicator, no thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import List, Literal

import discord
from discord import app_commands
from jarvis_command_sdk import (
    Channel,
    ChannelImage,
    IJarvisDaemon,
    IJarvisSecret,
    JarvisSecret,
    JarvisStorage,
    Outgoing,
    split_reply,
)

_log = logging.getLogger(__name__)
_storage = JarvisStorage("discord")

PROVIDER = "discord"
MAX_REPLY = 1900  # Discord's limit is 2000 characters
MAX_IMAGES = 4  # what one Jarvis chat turn takes
MAX_IMAGE_BYTES = 10 << 20  # a message's photos together: the request to Jarvis is one line of at most 16 MiB, base64
THREAD_NAME = 80
SEEN, DONE, FAILED = "👀", "✅", "❌"
ELSEWHERE = "I only work in direct messages and in the Jarvis channel."
UNREACHABLE = "I can't reach Jarvis right now. Try again in a moment."


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class Bridge:
    """What to do with a Discord message or command. It touches Discord only through the
    objects it is handed, so the tests drive it with stand-ins."""

    def __init__(self, channel: Channel, channel_id: int | None = None) -> None:
        self.channel = channel
        self.channel_id = channel_id
        self.bot_id: int | None = None
        # Accounts Jarvis has answered since we started. Only they see a reaction and the
        # typing indicator while a turn runs, so a stranger sees nothing at all.
        self.known: set[str] = set()

    def place(self, dm: bool, channel_id: int, parent_id: int | None) -> str | None:
        """Where something was said, as the conversation's place, or None where we don't listen."""
        if dm:
            return f"dm:{channel_id}"
        if self.channel_id is None:
            return None
        if channel_id == self.channel_id:
            return f"ch:{channel_id}"
        if parent_id == self.channel_id:
            return f"th:{channel_id}"
        return None

    async def on_message(self, m) -> None:
        if m.author.bot:
            return
        dm = m.guild is None
        top = not dm and self.channel_id is not None and m.channel.id == self.channel_id
        # A message in the channel gets a thread of its own, and Discord gives a thread started
        # from a message that message's id: so the conversation is the thread's from the start.
        place = f"th:{m.id}" if top else self.place(dm, m.channel.id, getattr(m.channel, "parent_id", None))
        if place is None:
            return
        text = m.content or ""
        if self.bot_id is not None:
            text = re.sub(rf"<@!?{self.bot_id}>", "", text)
        text = text.strip()
        photos = [a for a in m.attachments if (a.content_type or "").startswith("image/")]
        if not text and not photos:
            return

        uid = str(m.author.id)
        known = uid in self.known
        if known:
            await _try(m.add_reaction(SEEN))
        images = await _read_images(photos)
        if not text and not images:
            return
        async with m.channel.typing() if known else contextlib.nullcontext():
            reply = await self.channel.message(uid, place, text, images)
        if reply is None:
            if known:
                await _try(m.add_reaction(FAILED))
            return
        if not reply.linked:
            self.known.discard(uid)
            return
        self.known.add(uid)

        dest = m.channel
        if top:
            try:
                dest = await m.create_thread(name=clip(text, THREAD_NAME) or "Jarvis")
            except discord.HTTPException as exc:
                _log.warning("discord: could not start a thread, answering in the channel: %s", exc)
        for part in split_reply(reply.say, MAX_REPLY):
            if part:
                await dest.send(part)
        await _try(m.add_reaction(FAILED if reply.failed else DONE))

    async def on_command(self, i, name: str, **args: str) -> None:
        """A /jarvis command. Its answer is shown only to the person who asked."""
        await i.response.defer(ephemeral=True)
        place = self.place(i.guild_id is None, i.channel_id, getattr(i.channel, "parent_id", None))
        if place is None:
            text = ELSEWHERE
        else:
            reply = await self.channel.command(str(i.user.id), place, name, **args)
            text = reply.text if reply else UNREACHABLE
        await i.followup.send(text, ephemeral=True)


async def _try(action) -> None:
    """A nicety (a reaction) that must not cost the answer when Discord refuses it."""
    try:
        await action
    except discord.HTTPException as exc:
        _log.debug("discord: %s", exc)


async def _read_images(attachments) -> list[ChannelImage]:
    out: list[ChannelImage] = []
    total = 0
    for a in attachments[:MAX_IMAGES]:
        if total + a.size > MAX_IMAGE_BYTES:
            continue
        try:
            data = await a.read()
        except discord.HTTPException as exc:
            _log.warning("discord: could not fetch a photo: %s", exc)
            continue
        total += len(data)
        out.append(ChannelImage(data, a.content_type.split(";")[0].strip()))
    return out


def _commands(bridge: Bridge) -> app_commands.Group:
    g = app_commands.Group(name="jarvis", description="Jarvis")

    @g.command(name="link", description="Link this Discord account with a code from the Jarvis app")
    @app_commands.describe(code="The code the Jarvis app shows you")
    async def link(i: discord.Interaction, code: str) -> None:
        await bridge.on_command(i, "link", code=code)

    @g.command(name="new", description="Start a fresh conversation here")
    async def new(i: discord.Interaction) -> None:
        await bridge.on_command(i, "new")

    @g.command(name="node", description="Choose the node Jarvis answers through")
    @app_commands.describe(name="The node's name")
    async def node(i: discord.Interaction, name: str) -> None:
        await bridge.on_command(i, "node", name=name)

    @g.command(name="notify", description="Send my reminders to my direct messages")
    async def notify(i: discord.Interaction, state: Literal["on", "off"]) -> None:
        await bridge.on_command(i, "notify", state=state)

    @g.command(name="status", description="Show how this account is linked")
    async def status(i: discord.Interaction) -> None:
        await bridge.on_command(i, "status")

    return g


class _Client(discord.Client):
    def __init__(self, bridge: Bridge) -> None:
        intents = discord.Intents(guilds=True, guild_messages=True, dm_messages=True, message_content=True)
        # Nothing we send mentions anyone, whatever the text says.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.bridge = bridge
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(_commands(bridge))
        self._deliver: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self.bridge.bot_id = self.user.id
        await self.tree.sync()
        self._deliver = asyncio.create_task(self.bridge.channel.deliver(self.remind))

    async def close(self) -> None:
        if self._deliver:
            self._deliver.cancel()
        await super().close()

    async def on_message(self, m: discord.Message) -> None:
        await self.bridge.on_message(m)

    async def remind(self, msg: Outgoing) -> None:
        """A reminder, to its owner's direct messages. Raising has Jarvis offer it again."""
        try:
            user = await self.fetch_user(int(msg.external_user_id))
            for part in split_reply(msg.text, MAX_REPLY):
                await user.send(part)
        except (discord.Forbidden, discord.NotFound, ValueError) as exc:
            # Their direct messages are closed or the account is gone: asking again won't help.
            _log.warning("discord: dropped a reminder that can't be delivered: %s", exc)


class DiscordChannel(IJarvisDaemon):
    @property
    def name(self) -> str:
        return "discord"

    @property
    def description(self) -> str:
        return "Talk to Jarvis from Discord: direct messages, one channel, photos, commands and reminders"

    @property
    def required_secrets(self) -> List[IJarvisSecret]:
        return [
            JarvisSecret("DISCORD_BOT_TOKEN", "Your Discord application's bot token", "integration", "string",
                         friendly_name="Bot token"),
            JarvisSecret("DISCORD_CHANNEL_ID", "ID of the one server channel Jarvis answers in. "
                         "Leave empty for direct messages only.", "integration", "string",
                         required=False, is_sensitive=False, friendly_name="Jarvis channel ID"),
        ]

    async def run(self) -> None:
        token = (_storage.get_secret("DISCORD_BOT_TOKEN") or "").strip()
        if not token:
            raise RuntimeError("DISCORD_BOT_TOKEN is not set")
        raw = (_storage.get_secret("DISCORD_CHANNEL_ID") or "").strip()
        if raw and not raw.isdigit():
            raise RuntimeError("DISCORD_CHANNEL_ID is not a channel ID (digits only)")
        client = _Client(Bridge(Channel(PROVIDER), int(raw) if raw else None))
        async with client:
            try:
                await client.start(token)
            except discord.PrivilegedIntentsRequired:
                raise RuntimeError("Discord refused the connection: turn on Message Content Intent for the bot "
                                   "(discord.com/developers/applications, Bot tab)") from None
