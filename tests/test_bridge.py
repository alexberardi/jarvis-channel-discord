"""The bridge against stand-ins for Discord and for Jarvis: who gets an answer, where, and
that an account Jarvis doesn't know sees no sign of the bot."""

import asyncio
import contextlib
from types import SimpleNamespace

import discord
from jarvis_command_sdk import ChannelReply, CommandReply

from daemons.discord.daemon import MAX_IMAGE_BYTES, MAX_REPLY, Bridge, DiscordChannel, _Client, _read_images

JARVIS_CHANNEL = 500


class FakeJarvis:
    """Channel's stand-in: answers from a script and records what it was asked."""

    def __init__(self, reply=ChannelReply(linked=True, say="hi")):
        self.reply, self.asked, self.commands = reply, [], []

    async def message(self, uid, place, text="", images=()):
        self.asked.append((uid, place, text, list(images)))
        return self.reply

    async def command(self, uid, place, name, **args):
        self.commands.append((uid, place, name, args))
        return CommandReply(text="done")


class Place:
    def __init__(self, id, parent_id=None):
        self.id, self.parent_id, self.sent, self.typed = id, parent_id, [], 0

    async def send(self, text):
        self.sent.append(text)

    @contextlib.asynccontextmanager
    async def typing(self):
        self.typed += 1
        yield


class Photo:
    def __init__(self, data=b"jpeg", content_type="image/jpeg"):
        self.data, self.content_type, self.size = data, content_type, len(data)

    async def read(self):
        return self.data


class Msg:
    def __init__(self, text="hello", where=None, dm=False, uid=7, bot=False, attachments=(), id=900):
        self.id, self.content, self.attachments = id, text, list(attachments)
        self.author = SimpleNamespace(id=uid, bot=bot)
        self.guild = None if dm else object()
        self.channel = where or Place(42)
        self.reactions, self.thread = [], None

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def create_thread(self, name):
        self.thread = Place(self.id, parent_id=self.channel.id)
        self.thread.name = name
        return self.thread


def bridge(jarvis=None, channel_id=JARVIS_CHANNEL):
    b = Bridge(jarvis or FakeJarvis(), channel_id)
    b.bot_id = 1
    return b


def run(coro):
    return asyncio.run(coro)


def test_a_direct_message_is_answered_where_it_was_sent():
    b, m = bridge(), Msg("what's for dinner", dm=True)
    run(b.on_message(m))
    assert b.channel.asked == [("7", "dm:42", "what's for dinner", [])]
    assert m.channel.sent == ["hi"]
    assert m.reactions == ["✅"]


def test_a_stranger_sees_no_sign_of_the_bot():
    b = bridge(FakeJarvis(ChannelReply(linked=False)))
    m = Msg(where=Place(JARVIS_CHANNEL))
    run(b.on_message(m))
    assert b.channel.asked  # Jarvis decides who is linked, so it is asked
    assert (m.channel.sent, m.reactions, m.channel.typed, m.thread) == ([], [], 0, None)


def test_only_someone_jarvis_has_answered_sees_it_working():
    b = bridge()
    first, second = Msg(dm=True), Msg(dm=True)
    run(b.on_message(first))
    run(b.on_message(second))
    assert (first.channel.typed, first.reactions) == (0, ["✅"])
    assert (second.channel.typed, second.reactions) == (1, ["👀", "✅"])


def test_an_account_that_was_unlinked_is_a_stranger_again():
    b = bridge()
    run(b.on_message(Msg(dm=True)))
    b.channel.reply = ChannelReply(linked=False)
    run(b.on_message(Msg(dm=True)))
    assert b.known == set()


def test_a_message_in_the_channel_is_answered_in_its_own_thread():
    b = bridge()
    m = Msg("<@1> plan   the week", where=Place(JARVIS_CHANNEL), id=901)
    run(b.on_message(m))
    assert b.channel.asked[0][1:3] == ("th:901", "plan   the week")
    assert (m.thread.name, m.thread.sent, m.channel.sent) == ("plan the week", ["hi"], [])
    # What is said in that thread next continues the same conversation.
    run(b.on_message(Msg("and the weekend", where=m.thread)))
    assert b.channel.asked[1][1] == "th:901"


def test_other_channels_bots_and_empty_messages_are_ignored():
    b = bridge()
    for m in (Msg(where=Place(77)), Msg(dm=True, bot=True), Msg("", dm=True), Msg("<@1>", dm=True),
              Msg("", dm=True, attachments=[Photo(content_type="audio/ogg")])):
        run(b.on_message(m))
    run(bridge(channel_id=None).on_message(Msg(where=Place(JARVIS_CHANNEL))))
    assert b.channel.asked == []


def test_photos_go_along_and_a_long_reply_is_split():
    b = bridge(FakeJarvis(ChannelReply(linked=True, say="word " * 600)))
    m = Msg("", dm=True, attachments=[Photo(b"a"), Photo(b"b", "image/png; charset=binary"), Photo(content_type=None)])
    run(b.on_message(m))
    assert [(i.data, i.mime) for i in b.channel.asked[0][3]] == [(b"a", "image/jpeg"), (b"b", "image/png")]
    assert len(m.channel.sent) == 2 and all(len(p) <= MAX_REPLY for p in m.channel.sent)


def test_photos_past_the_size_limit_are_left_out():
    big = Photo(b"x")
    big.size = MAX_IMAGE_BYTES
    got = run(_read_images([Photo(b"a"), big, Photo(b"c")]))
    assert [i.data for i in got] == [b"a", b"c"]


def test_a_failed_turn_says_why_and_jarvis_out_of_reach_says_nothing():
    b = bridge(FakeJarvis(ChannelReply(linked=True, say="The model is not running.", failed=True)))
    m = Msg(dm=True)
    run(b.on_message(m))
    assert (m.channel.sent, m.reactions) == (["The model is not running."], ["❌"])
    b.channel.reply = None
    m = Msg(dm=True)
    run(b.on_message(m))
    assert (m.channel.sent, m.reactions) == ([], ["👀", "❌"])


class Interaction:
    def __init__(self, guild_id=None, channel_id=42, parent_id=None):
        self.guild_id, self.channel_id, self.user = guild_id, channel_id, SimpleNamespace(id=7)
        self.channel = SimpleNamespace(parent_id=parent_id)
        self.deferred, self.said = [], []
        self.response = SimpleNamespace(defer=self._defer)
        self.followup = SimpleNamespace(send=self._send)

    async def _defer(self, ephemeral):
        self.deferred.append(ephemeral)

    async def _send(self, text, ephemeral):
        self.said.append((text, ephemeral))


def test_a_command_is_answered_privately():
    b, i = bridge(), Interaction()
    run(b.on_command(i, "link", code="ABCD2345"))
    assert b.channel.commands == [("7", "dm:42", "link", {"code": "ABCD2345"})]
    assert (i.deferred, i.said) == ([True], [("done", True)])


def test_a_command_in_a_thread_names_the_thread_and_elsewhere_is_refused():
    b = bridge()
    run(b.on_command(Interaction(guild_id=9, channel_id=901, parent_id=JARVIS_CHANNEL), "new"))
    assert b.channel.commands[0][1] == "th:901"
    i = Interaction(guild_id=9, channel_id=77)
    run(b.on_command(i, "new"))
    assert len(b.channel.commands) == 1 and "direct messages" in i.said[0][0]


def test_the_client_asks_for_no_more_than_it_needs_and_mentions_nobody():
    async def build():
        return _Client(bridge())

    c = run(build())
    on = {name for name, value in c.intents if value}
    assert on == {"guilds", "guild_messages", "dm_messages", "message_content"}
    assert c.allowed_mentions.to_dict() == discord.AllowedMentions.none().to_dict()
    assert sorted(cmd.name for cmd in c.tree.get_command("jarvis").commands) == ["link", "new", "node", "notify", "status"]


def test_the_daemon_declares_its_secrets():
    secrets = {s.key: s for s in DiscordChannel().required_secrets}
    assert secrets["DISCORD_BOT_TOKEN"].is_sensitive and secrets["DISCORD_BOT_TOKEN"].required
    assert not secrets["DISCORD_CHANNEL_ID"].required and not secrets["DISCORD_CHANNEL_ID"].is_sensitive
