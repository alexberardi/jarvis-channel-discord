# jarvis-channel-discord

Talk to Jarvis from Discord. You run your own Discord bot; this package keeps its connection
open from one of your nodes and hands Jarvis what linked people send. Nothing is opened on your
network: the bot connects out to Discord.

It is a Jarvis Automation package (one daemon) that nodes install through Pantry.

## What it does

- **Direct messages.** Message the bot and Jarvis answers there.
- **One channel.** In the channel you choose, Jarvis answers each message in a thread of its own.
  What you say in that thread continues the same conversation.
- **Photos.** Attach a photo and ask about it. Up to four per message, 10 MB together.
- **Commands.** `/jarvis link`, `new`, `node`, `notify` and `status`. Answers are shown only to you.
- **Reminders.** If you turn them on (`/jarvis notify on`), reminders, alarms and timers you set
  are also sent to your direct messages. Off by default.
- **Reactions.** ✅ when Jarvis has answered, ❌ when it could not. Once Jarvis has answered you,
  you also see 👀 and the typing indicator while it works.

Jarvis never starts a conversation. The only thing it sends unasked is a reminder, to the person
who set it, and only if they turned that on.

Not yet: voice messages and live voice in a voice channel.

## Who gets an answer

- **Only linked accounts.** Each person links their own Discord account with a one-time code
  from the Jarvis app. Everyone else gets no sign that the bot is listening: no reply, no
  reaction, no typing indicator, no thread.
- **A linked Discord account acts as that Jarvis user.** Treat it like a login: turn on two-factor
  authentication for the Discord account, keep the server private and invite nobody you don't trust.
- **Replies never mention anyone**, whatever the text says.
- The bot answers only in direct messages, the one channel you set, and that channel's threads.

## Setup

Do this once, as the household's admin. Never paste the bot token into a chat.

1. **Create a private server** in Discord (Add a Server, Create My Own). Create a text channel
   for Jarvis, for example `#jarvis`. Skip the channel if you only want direct messages.
2. **Create the application.** At <https://discord.com/developers/applications> choose
   New Application. On its **Bot** tab:
   - choose **Reset Token**, copy the token and keep it in your password manager;
   - turn **Public Bot** off, so nobody else can add it;
   - under **Privileged Gateway Intents** turn **Message Content Intent** on. Leave the other
     two off. Without it the bot cannot read what people type.
3. **Invite the bot.** Under **OAuth2**, URL Generator, tick the scopes `bot` and
   `applications.commands`, then these permissions: View Channels, Send Messages, Create Public
   Threads, Send Messages in Threads, Read Message History, Add Reactions. Open the generated URL
   and pick your server.
4. **Install this package** on one node from the Jarvis app's store. A household runs it on one
   node only.
5. **Enter the settings** in the app, under the package's settings:
   - **Bot token**: the token from step 2.
   - **Jarvis channel ID**: optional. Turn on Developer Mode in Discord (User Settings, Advanced),
     right-click the channel and choose Copy Channel ID. Leave empty for direct messages only.
6. **Link yourself.** In the Jarvis app open your channels, make a link code for Discord, then in
   Discord run `/jarvis link` with that code. The code lasts ten minutes and works once.

The bot shows as online when the node has connected it. To message it directly, you must share a
server with it.

## How it works

`daemons/discord/daemon.py` is an `IJarvisDaemon`: the node starts it once and restarts it if it
stops. It talks to Jarvis only through the SDK's `Channel` helper: who an account is, the chat
turn, the commands' answers and the reminders are all Jarvis's. This package only knows Discord.

## Development

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install "jarvis-command-sdk @ git+https://github.com/alexberardi/jarvis-command-sdk@main" \
  "jarvis-developer-toolkit @ git+https://github.com/alexberardi/jarvis-developer-toolkit@main" \
  "discord.py>=2.4,<3" pytest
jdt test . --install-deps
python -m pytest tests
```

The tests drive the bridge with stand-ins for Discord and for Jarvis; none connects anywhere.

## Credit

How this channel behaves (direct messages and one channel, a thread per conversation, the
commands, silence towards accounts that are not linked, opt-in reminders) and much of the setup
guide follow the Discord bridge that opticon454 contributed to jarvis-server (pull request 649).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
