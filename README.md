# Nimbus

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)](pyproject.toml)

**Code from anywhere. Your server runs Claude Code. Your phone gives the orders.**

Nimbus turns a Telegram chat into a full AI development command center. Send a message from your phone, and Claude Code runs headlessly on your server — reading files, editing code, running tests, deploying projects — then reports back with clean, structured results and cost tracking.

No laptop. No SSH app. No IDE. Just your phone and a Telegram chat.

<!-- TODO: Add demo GIF here -->
<!-- ![Nimbus Demo](docs/demo.gif) -->

---

### Who is this for?

- **Solo developers** managing VPS infrastructure who want to deploy and debug from the couch
- **Indie hackers** running multiple projects who need quick access without opening a laptop
- **Agency owners** juggling client projects who want one command center for everything
- **Anyone with a Claude Max subscription** who wants their AI agent available 24/7

---

## How It Works

```
You (phone)                       Your VPS
    |                                |
    |  "@backend #api fix the        |
    |   auth timeout bug"            |
    |  ─────────────────────────►    |
    |                           claude -p (headless)
    |                             reads files
    |                             edits code
    |                             runs tests
    |    ◄─────────────────────      |
    |  "Fixed. Updated retry         |
    |   logic in auth.service.ts.    |
    |   All tests pass.              |
    |   $0.04 | 12s | 3 turns"      |
```

## Quick Start

### Prerequisites

- A VPS or server with [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Python 3.10+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Your Telegram chat ID (from [@userinfobot](https://t.me/userinfobot))

### Install

```bash
git clone https://github.com/Bigabou007-dev/nimbus.git
cd nimbus

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your Telegram token and chat ID

# Install and start (creates venv, systemd service, survives reboots)
chmod +x setup.sh && ./setup.sh
```

Or with pip:

```bash
pip install nimbus-ai
nimbus --config config.yaml
```

That's it. Open Telegram and send a message to your bot.

## Usage

### Smart Prefixes

Type naturally. Nimbus parses your intent:

```
fix the login bug                    → Claude task in default dir
#myproject add search to products    → runs in project context
@frontend fix the navbar             → routes to an agent persona
@backend #api optimize the queries   → agent + project combined
$ docker ps                          → direct shell, no Claude
.commit                              → Claude slash command (/commit)
```

### Inline Keyboards

Tap `/menu` for quick-action buttons — no typing needed:

```
[ Status ] [ Tasks ] [ Screen ]
[Projects] [Agents] [  Bash  ]
```

Tap a project and get Deploy / Test / Send Task buttons. Tap an agent to route your next message through a specific persona.

### Commands

| Command | Description |
|---|---|
| `/status` | System health, running tasks, queue depth |
| `/tasks` | Recent task history with costs |
| `/task 42` | Full result of task #42 |
| `/cancel 42` | Cancel a running or queued task |
| `/projects` | List projects (tap to select) |
| `/agents` | List agents (tap to assign) |
| `/bash ls -la` | Run a shell command directly |
| `/deploy api` | Deploy a project |
| `/screen` | Capture current terminal output |
| `/costs` | Today's spending breakdown |
| `/menu` | Quick-action buttons |

### File Uploads

Send files directly from your phone. Add a caption to tell Claude what to do:

- Photo + *"fix this CSS bug"* → Claude sees the screenshot and fixes the code
- JSON file + *"validate and format this"* → saves to VPS, Claude processes it
- Document + *"summarize the key points"* → file available at a known path

## Comparison

|  | Nimbus | Claude Code Channels | OpenClaw |
|---|---|---|---|
| **Engine** | `claude -p` headless (structured JSON) | Interactive CLI bridge | Multi-LLM skill system |
| **Concurrency** | 3 parallel tasks + queue | Single session | Single session |
| **Output** | Formatted results + cost/duration | Raw terminal | Varies by skill |
| **Project context** | Multi-project switching | CWD only | CWD only |
| **Agent personas** | Built-in routing system | None | Skill-based |
| **Data persistence** | SQLite task history + metrics | None | None |
| **File uploads** | Photos, docs, voice | None | Some skills |
| **Offline resilience** | Queue persists | Messages lost | Messages lost |
| **Setup** | `pip install` + 1 YAML file | Bun + claude.ai login | Docker + plugins |
| **Codebase** | 5 Python files | Plugin architecture | 100+ skills |
| **Community** | New | Official (Anthropic) | 250K+ stars |

Nimbus is new and small. OpenClaw is a massive ecosystem. Channels is backed by Anthropic. We're not trying to replace either — we're filling the gap for developers who want a **lean, focused, phone-first** Claude Code controller with zero bloat.

## Configuration

### Projects

```yaml
projects:
  frontend:
    path: "~/code/frontend"
    description: "React frontend"
    deploy_cmd: "npm run build && vercel --prod"
    test_cmd: "npm test"
  api:
    path: "~/code/api"
    description: "NestJS backend"
    test_cmd: "npm run test:e2e"
```

Target them with `#frontend fix the header` or tap in `/projects`.

### Agents

Agent personas are system prompts that shape Claude's behavior for specific domains:

```yaml
agents:
  frontend:
    description: "Frontend — React, CSS, UI/UX"
    prompt_file: "~/prompts/frontend.md"
  backend:
    description: "Backend — APIs, databases, infra"
    prompt_file: "~/prompts/backend.md"
  reviewer:
    description: "Code reviewer — security, performance"
    prompt_file: "~/prompts/reviewer.md"
```

Route with `@reviewer check the auth module` or tap in `/agents`.

## Architecture

```
nimbus/
├── nimbus/
│   ├── __init__.py
│   ├── __main__.py         # Entry point + YAML config loader
│   ├── bot.py              # Telegram bot (handlers, keyboards, callbacks)
│   ├── engine.py           # Claude headless runner (claude -p)
│   ├── sessions.py         # Multi-session manager (concurrency + queue)
│   └── store.py            # SQLite task store (history, metrics, costs)
├── config.example.yaml     # Template configuration
├── setup.sh                # One-command install
├── pyproject.toml
├── requirements.txt
└── LICENSE
```

**5 files. No framework magic. Fork it and read it in 20 minutes.**

### How tasks flow

1. You send a message in Telegram
2. Nimbus parses smart prefixes (`@agent`, `#project`, `$bash`)
3. Task is submitted to the session manager
4. If a slot is available (max 3 concurrent), it runs via `claude -p --output-format stream-json`
5. Streaming events update your Telegram message in real-time
6. Final result is sent back with cost, duration, and turn count
7. Task is saved to SQLite for history and cost tracking
8. If all slots are busy, the task is queued and runs automatically when a slot opens

## Running as a Service

The `setup.sh` script creates a systemd user service that starts on boot, auto-restarts on crash, and survives SSH disconnects:

```bash
systemctl --user status nimbus      # check status
systemctl --user restart nimbus     # restart
systemctl --user stop nimbus        # stop
journalctl --user -u nimbus -f      # live logs
```

## Security

- **Chat ID authorization**: Only your Telegram account can interact with the bot. All other messages are silently dropped.
- **No credentials in code**: Token and chat ID live in `config.yaml`, which is gitignored. Nothing sensitive in the source.
- **Local execution**: All processing happens on your server. Message content passes through the Telegram Bot API (a third-party service) and the Claude API. No other external services are involved.
- **Permission modes**: The example config defaults to `default` mode (Claude asks for approval before destructive actions). You can set `bypassPermissions` for trusted, isolated environments — but understand the risk.
- **SQL injection protected**: All database queries use parameterized statements.

## Cost Tracking

Every task logs its Claude API cost to SQLite:

```
/costs
─────────────
Today:
  Tasks: 14
  Completed: 12
  Failed: 2
  Total Cost: $0.4821
  Total Time: 342s
```

Use `/tasks` for per-task breakdown, or query `~/.nimbus/nimbus.db` directly.

## Limitations

Nimbus is a phone-to-server relay, not a full IDE replacement. Keep these in mind:

- **Not for long pair-programming sessions** — best for quick tasks, deploys, and fixes
- **Telegram message limits** — very large outputs get chunked across multiple messages
- **No syntax highlighting** — results are plain text (code blocks where possible)
- **Single user** — designed for one developer, one bot, one server
- **Claude API costs apply** — every task uses your Claude subscription or API credits

## Roadmap

- [ ] Demo GIF and video walkthrough
- [ ] Voice-to-text transcription (Whisper)
- [ ] Telegram Mini App dashboard
- [ ] Git PR integration (create/review PRs from chat)
- [ ] Webhook triggers (GitHub, CI/CD → Nimbus)
- [ ] Multi-user / team mode
- [ ] Task templates (saved prompts)
- [ ] Cron-scheduled recurring tasks
- [ ] PyPI publication

## Contributing

PRs welcome. The codebase is intentionally lean — 5 Python files, no framework dependencies beyond `python-telegram-bot`.

```bash
git clone https://github.com/Bigabou007-dev/nimbus.git
cd nimbus
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml  # add your tokens
python -m nimbus --debug
```

## License

MIT — use it however you want.

---

Built in Abidjan by [Lagoon Tech Systems](https://lagoontechsystems.com). Born from managing 7 production projects from a phone.

If Nimbus saves you a laptop-open, consider giving the repo a star.
