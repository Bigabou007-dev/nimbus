#!/usr/bin/env python3
"""
Nimbus Marketing Content Generator
Generates all marketing assets: X thread, Reddit posts, video script, and descriptions.
"""

import json
import os
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

REPO_URL = "https://github.com/Bigabou007-dev/nimbus"


def generate_x_thread():
    """Generate X (Twitter) launch thread."""
    tweets = [
        # Tweet 1 — Hook
        (
            "I built an open-source tool that lets me code from my phone.\n\n"
            "No laptop. No IDE. Just a Telegram message.\n\n"
            "I send \"fix the login bug\" from my couch, and Claude Code fixes it on my server.\n\n"
            "It's called Nimbus. Here's how it works:"
        ),
        # Tweet 2 — The problem
        (
            "The problem:\n\n"
            "I manage 7 production projects from a VPS in Abidjan.\n\n"
            "Sometimes I need to deploy a fix at midnight. Or check server health from a taxi. "
            "Or run a quick command while I'm away from my desk.\n\n"
            "Opening a laptop isn't always an option."
        ),
        # Tweet 3 — The solution
        (
            "The solution:\n\n"
            "Nimbus runs Claude Code in headless mode (claude -p) on your server.\n\n"
            "You send a Telegram message. Claude reads files, edits code, runs tests, deploys. "
            "Results come back to your phone with cost tracking.\n\n"
            "No tmux hacking. Structured JSON. Real streaming."
        ),
        # Tweet 4 — Smart prefixes
        (
            "The UX is dead simple:\n\n"
            "  fix the login bug → runs Claude\n"
            "  #myproject add search → targets a project\n"
            "  @backend optimize queries → routes to an agent\n"
            "  $ docker ps → direct shell\n\n"
            "Inline keyboard buttons for common actions. No typing needed."
        ),
        # Tweet 5 — What makes it different
        (
            "Why not just use Claude Code Channels?\n\n"
            "Channels is single-session, no file uploads, messages lost when offline, requires Bun.\n\n"
            "Nimbus:\n"
            "- 3 parallel tasks + queue\n"
            "- SQLite task history + cost tracking\n"
            "- Agent personas\n"
            "- File uploads from phone\n"
            "- Rate limiting + audit logs\n"
            "- 6 Python files"
        ),
        # Tweet 6 — Security
        (
            "Security:\n\n"
            "- Chat ID authorization (silent reject)\n"
            "- Optional passphrase auth\n"
            "- Rate limiting (30 req/min)\n"
            "- Command blocklist (blocks rm -rf /, shutdown, etc.)\n"
            "- Full audit logging\n"
            "- Works behind Tailscale — zero public ports\n\n"
            "Your code never leaves your server."
        ),
        # Tweet 7 — CTA
        (
            f"Nimbus is MIT licensed. 6 files. Zero framework magic.\n\n"
            f"pip install nimbus-ai\n\n"
            f"Or clone and run setup.sh — one command.\n\n"
            f"{REPO_URL}\n\n"
            "If you manage servers from your phone, give it a star.\n\n"
            "#OpenSource #ClaudeCode #AI #DevTools"
        ),
    ]

    output = ""
    for i, tweet in enumerate(tweets, 1):
        output += f"--- TWEET {i}/{len(tweets)} ({len(tweet)} chars) ---\n"
        output += tweet + "\n\n"

    path = OUTPUT_DIR / "x_thread.txt"
    path.write_text(output)
    print(f"X thread saved to {path}")
    return tweets


def generate_reddit_posts():
    """Generate Reddit posts for r/ClaudeAI and r/selfhosted."""

    claude_ai_post = {
        "subreddit": "r/ClaudeAI",
        "title": "I built an open-source tool to control Claude Code from my phone via Telegram",
        "body": (
            "I manage 7 production projects from a VPS and got tired of needing my laptop "
            "every time I wanted to run a quick fix or deploy.\n\n"
            "So I built **Nimbus** — a Telegram bot that runs Claude Code in headless mode "
            "(`claude -p --output-format stream-json`) on your server.\n\n"
            "## How it works\n\n"
            "1. Send a message in Telegram\n"
            "2. Nimbus runs it through Claude Code headlessly\n"
            "3. Results stream back to your phone with cost + duration\n\n"
            "## Key features\n\n"
            "- **Smart prefixes**: `@agent`, `#project`, `$ bash` — type naturally\n"
            "- **3 concurrent tasks** with automatic queuing\n"
            "- **Agent personas** — route tasks to specialized prompts\n"
            "- **Project switching** — target specific repos\n"
            "- **Cost tracking** — every task logged to SQLite\n"
            "- **File uploads** — send photos/docs from your phone\n"
            "- **Security** — rate limiting, passphrase auth, audit logs, command filtering\n\n"
            "## Why not Claude Code Channels?\n\n"
            "Channels dropped 2 days ago and it's cool, but it's single-session, "
            "no file uploads, requires Bun, and messages are lost when offline. "
            "Nimbus uses headless mode for structured JSON output, runs 3 tasks in parallel, "
            "and persists everything to SQLite.\n\n"
            "## The codebase\n\n"
            "6 Python files. No framework magic. Read the whole thing in 20 minutes.\n\n"
            f"**GitHub**: {REPO_URL}\n\n"
            "MIT licensed. Feedback welcome — this is v0.1.0.\n\n"
            "Built in Abidjan, Ivory Coast."
        )
    }

    selfhosted_post = {
        "subreddit": "r/selfhosted",
        "title": "Nimbus: Control your VPS from your phone via Telegram + Claude Code AI",
        "body": (
            "I built a Telegram bot that gives me full control of my VPS from my phone. "
            "It uses Claude Code's headless mode to run AI-powered tasks — reading files, "
            "editing code, running commands, deploying projects.\n\n"
            "**The pitch**: Send \"deploy my app\" from Telegram, and Claude Code runs on your "
            "server, executes the deployment, and reports back with results.\n\n"
            "## Self-hosting details\n\n"
            "- Runs as a **systemd user service** (survives reboots via linger)\n"
            "- **SQLite** for task history and cost tracking\n"
            "- **YAML config** for projects, agents, and workflows\n"
            "- Works great behind **Tailscale** — zero public ports needed\n"
            "- Bot polls Telegram API outbound — no inbound ports required\n\n"
            "## Security\n\n"
            "- Chat ID auth (silent reject for strangers)\n"
            "- Optional passphrase gate\n"
            "- Rate limiting (configurable)\n"
            "- Dangerous command blocklist (rm -rf, shutdown, etc.)\n"
            "- Full audit logging to file\n"
            "- Command allowlist mode (restrict to docker/git/npm only)\n\n"
            "## Requirements\n\n"
            "- A VPS with Claude Code CLI installed\n"
            "- Python 3.10+\n"
            "- A Telegram bot token\n"
            "- Claude Max subscription or API key\n\n"
            f"**GitHub**: {REPO_URL}\n\n"
            "6 Python files, MIT licensed, pip installable. "
            "Happy to answer questions about the architecture."
        )
    }

    for post in [claude_ai_post, selfhosted_post]:
        filename = post["subreddit"].replace("/", "_") + ".txt"
        path = OUTPUT_DIR / filename
        content = f"SUBREDDIT: {post['subreddit']}\n"
        content += f"TITLE: {post['title']}\n"
        content += f"---\n{post['body']}"
        path.write_text(content)
        print(f"Reddit post saved to {path}")

    return [claude_ai_post, selfhosted_post]


def generate_video_script():
    """Generate script for faceless YouTube Short / TikTok."""

    scenes = [
        {
            "duration": 3,
            "text": "I code from my phone.",
            "subtext": "No laptop. No IDE.",
            "bg_color": "#0a0a0a",
            "text_color": "#ffffff",
        },
        {
            "duration": 4,
            "text": "I send a message\nin Telegram...",
            "subtext": '"fix the login bug"',
            "bg_color": "#0a0a0a",
            "text_color": "#ffffff",
        },
        {
            "duration": 5,
            "text": "Claude Code runs\non my server",
            "subtext": "Reads files. Edits code.\nRuns tests. Deploys.",
            "bg_color": "#1a1a2e",
            "text_color": "#00ff88",
        },
        {
            "duration": 4,
            "text": "Results come back\nto my phone",
            "subtext": '"Fixed. 3 files changed.\nAll tests pass. $0.04"',
            "bg_color": "#1a1a2e",
            "text_color": "#ffffff",
        },
        {
            "duration": 4,
            "text": "3 parallel tasks\nCost tracking\nAgent routing",
            "subtext": "Built-in security",
            "bg_color": "#0d1117",
            "text_color": "#58a6ff",
        },
        {
            "duration": 3,
            "text": "6 Python files.\nMIT licensed.",
            "subtext": "github.com/Bigabou007-dev/nimbus",
            "bg_color": "#0a0a0a",
            "text_color": "#ffffff",
        },
        {
            "duration": 4,
            "text": "Nimbus",
            "subtext": "Your AI agent.\nAlways on. Always yours.",
            "bg_color": "#000000",
            "text_color": "#ffffff",
        },
    ]

    # Save as JSON for the video generator
    path = OUTPUT_DIR / "video_script.json"
    path.write_text(json.dumps(scenes, indent=2))
    print(f"Video script saved to {path}")

    # Also save human-readable version
    readable = "NIMBUS — Faceless Video Script (YouTube Short / TikTok)\n"
    readable += f"Total duration: ~{sum(s['duration'] for s in scenes)}s\n"
    readable += "=" * 50 + "\n\n"
    for i, scene in enumerate(scenes, 1):
        readable += f"SCENE {i} ({scene['duration']}s)\n"
        readable += f"  Main: {scene['text']}\n"
        readable += f"  Sub:  {scene['subtext']}\n"
        readable += f"  Look: {scene['bg_color']} bg, {scene['text_color']} text\n\n"

    path_readable = OUTPUT_DIR / "video_script_readable.txt"
    path_readable.write_text(readable)

    return scenes


def generate_youtube_metadata():
    """Generate YouTube title, description, tags."""
    metadata = {
        "title": "I Control My AI Coding Agent From My Phone | Nimbus",
        "description": (
            "Nimbus lets you control Claude Code from your phone via Telegram.\n\n"
            "Send a message, and Claude Code runs headlessly on your server — "
            "reading files, editing code, running tests, deploying projects.\n\n"
            "Features:\n"
            "- 3 parallel AI tasks + queue\n"
            "- Smart prefixes: @agent, #project, $ bash\n"
            "- Cost tracking per task\n"
            "- File uploads from phone\n"
            "- Agent personas\n"
            "- Rate limiting + audit logs\n"
            "- Works behind Tailscale\n\n"
            f"GitHub: {REPO_URL}\n\n"
            "MIT Licensed. 6 Python files.\n\n"
            "#ClaudeCode #AI #Programming #DevTools #OpenSource #Telegram"
        ),
        "tags": [
            "claude code", "ai coding", "telegram bot", "devops",
            "programming", "open source", "ai agent", "remote coding",
            "mobile development", "vps", "self hosted", "claude ai",
            "anthropic", "coding from phone", "nimbus"
        ]
    }

    path = OUTPUT_DIR / "youtube_metadata.json"
    path.write_text(json.dumps(metadata, indent=2))
    print(f"YouTube metadata saved to {path}")
    return metadata


if __name__ == "__main__":
    print("Generating Nimbus marketing content...\n")
    generate_x_thread()
    generate_reddit_posts()
    generate_video_script()
    generate_youtube_metadata()
    print("\nDone. All content in marketing/output/")
