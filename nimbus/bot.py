"""
Nimbus Bot — Telegram interface with inline keyboards, streaming, and rich UX.
"""

import asyncio
import os
import time
import logging
import re
from pathlib import Path

from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from telegram.constants import ParseMode, ChatAction

from .engine import NimbusEngine, StreamEvent, EngineResult
from .sessions import SessionManager
from .store import NimbusStore, TaskStatus
from .security import RateLimiter, PassphraseAuth, AuditLog, CommandFilter

log = logging.getLogger(__name__)

TG_MAX_LEN = 4000


def split_message(text: str) -> list[str]:
    if not text or len(text) <= TG_MAX_LEN:
        return [text] if text else []
    chunks = []
    while text:
        if len(text) <= TG_MAX_LEN:
            chunks.append(text)
            break
        split_at = text.rfind('\n', 0, TG_MAX_LEN)
        if split_at < TG_MAX_LEN // 2:
            split_at = TG_MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip('\n')
    return chunks


class NimbusBot:
    def __init__(self, config: dict):
        self.config = config
        self.tg_config = config["telegram"]
        self.token = self.tg_config["token"]
        self.chat_id = str(self.tg_config["chat_id"])

        # Core components
        self.store = NimbusStore(config.get("paths", {}).get("db", "~/.nimbus/nimbus.db"))
        self.engine = NimbusEngine(config.get("claude", {}))
        self.sessions = SessionManager(self.engine, self.store, config)

        # Security
        sec_config = config.get("security", {})
        rate_cfg = sec_config.get("rate_limit", {})
        self.rate_limiter = RateLimiter(
            max_requests=rate_cfg.get("max_requests", 30),
            window_seconds=rate_cfg.get("window_seconds", 60),
        )
        self.passphrase_auth = PassphraseAuth(
            passphrase=sec_config.get("passphrase")
        )
        self.audit = AuditLog(
            log_path=sec_config.get("audit_log", "~/.nimbus/audit.log")
        )
        self.cmd_filter = CommandFilter(
            blocklist=sec_config.get("bash_blocklist"),
            allowlist=sec_config.get("bash_allowlist"),
        )

        # Upload dir
        self.upload_dir = os.path.expanduser(
            config.get("paths", {}).get("uploads", "~/.nimbus-uploads")
        )
        os.makedirs(self.upload_dir, exist_ok=True)

        # Status message tracking
        self.pinned_msg_id = None
        self.app = None

    def is_authorized(self, chat_id: int) -> bool:
        return str(chat_id) == self.chat_id

    async def check_access(self, update: Update) -> bool:
        """Full access check: chat ID + rate limit + passphrase. Returns True if allowed."""
        chat_id = update.effective_chat.id
        username = update.effective_user.username or ""

        # Chat ID check
        if not self.is_authorized(chat_id):
            self.audit.log_unauthorized(str(chat_id), username)
            return False

        # Rate limit check
        if not self.rate_limiter.is_allowed(str(chat_id)):
            self.audit.log_rate_limited(str(chat_id))
            await update.message.reply_text(
                f"Rate limited. Max {self.rate_limiter.max_requests} requests per {self.rate_limiter.window}s. "
                f"Remaining: {self.rate_limiter.remaining(str(chat_id))}"
            )
            return False

        # Passphrase check
        if not self.passphrase_auth.is_authenticated(str(chat_id)):
            text = update.message.text or ""
            if self.passphrase_auth.attempt(str(chat_id), text):
                self.audit.log_auth_attempt(str(chat_id), True)
                await update.message.reply_text("Authenticated. Welcome to Nimbus.")
                return False  # consume the passphrase message, don't process as task
            else:
                self.audit.log_auth_attempt(str(chat_id), False)
                await update.message.reply_text("Passphrase required. Send your passphrase to continue.")
                return False

        return True

    # ── Keyboards ────────────────────────────────────────────

    def main_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Status", callback_data="cmd:status"),
                InlineKeyboardButton("Tasks", callback_data="cmd:tasks"),
                InlineKeyboardButton("Screen", callback_data="cmd:screen"),
            ],
            [
                InlineKeyboardButton("Projects", callback_data="cmd:projects"),
                InlineKeyboardButton("Agents", callback_data="cmd:agents"),
                InlineKeyboardButton("Bash", callback_data="cmd:bash_prompt"),
            ],
        ])

    def project_keyboard(self) -> InlineKeyboardMarkup:
        projects = self.config.get("projects", {})
        buttons = []
        row = []
        for name, info in projects.items():
            row.append(InlineKeyboardButton(
                name, callback_data=f"project:{name}"
            ))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("Back", callback_data="cmd:main")])
        return InlineKeyboardMarkup(buttons)

    def agent_keyboard(self) -> InlineKeyboardMarkup:
        agents = self.config.get("agents", {})
        buttons = []
        row = []
        for name, info in agents.items():
            label = name
            row.append(InlineKeyboardButton(
                label, callback_data=f"agent:{name}"
            ))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("Back", callback_data="cmd:main")])
        return InlineKeyboardMarkup(buttons)

    def task_actions_keyboard(self, task_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("View Result", callback_data=f"task:view:{task_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"task:cancel:{task_id}"),
            ]
        ])

    def confirm_keyboard(self, action: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes", callback_data=f"confirm:{action}"),
                InlineKeyboardButton("No", callback_data="confirm:cancel"),
            ]
        ])

    # ── Stream Handler ───────────────────────────────────────

    async def _on_stream(self, event: StreamEvent, task):
        """Called for each streaming event — updates a live message in Telegram."""
        if not self.app or not task.telegram_msg_id:
            return

        if event.event_type in ("init", "queued"):
            return

        # Build progress message
        elapsed = int(time.time() - task.created_at)
        prefix = f"Task #{task.id}"
        if task.project:
            prefix += f" [{task.project}]"
        if task.agent:
            prefix += f" @{task.agent}"

        if event.event_type == "assistant":
            content = event.content[:3000]
            text = f"{prefix} ({elapsed}s)\n\n{content}"
        elif event.event_type == "result":
            return  # handled by on_complete
        else:
            text = f"{prefix} ({elapsed}s)\n\n{event.content[:2000]}"

        try:
            await self.app.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=task.telegram_msg_id,
                text=text[:TG_MAX_LEN],
            )
        except Exception:
            pass  # message unchanged or deleted

    async def _on_complete(self, result: EngineResult, task):
        """Called when a task finishes — sends the final formatted response."""
        if not self.app:
            return

        icon = "Done" if result.success else "Failed"
        prefix = f"Task #{task.id} — {icon}"
        if task.project:
            prefix += f" [{task.project}]"
        if task.agent:
            prefix += f" @{task.agent}"

        # Stats line
        stats = f"${result.cost_usd:.4f} | {result.duration_ms/1000:.1f}s | {result.num_turns} turns"

        # Format result
        response = result.result or result.error or "(no output)"
        text = f"{prefix}\n{stats}\n\n{response}"

        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            try:
                if i == 0 and task.telegram_msg_id:
                    await self.app.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=task.telegram_msg_id,
                        text=chunk,
                    )
                else:
                    await self.app.bot.send_message(
                        chat_id=self.chat_id,
                        text=chunk,
                    )
            except Exception as e:
                log.error(f"Failed to send result: {e}")
                await self.app.bot.send_message(
                    chat_id=self.chat_id, text=chunk
                )

        # React to original message
        # Update status board
        await self._update_status_board()

        # Process next queued task
        next_task = self.store.next_queued()
        if next_task:
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=f"Starting queued task #{next_task.id}: {next_task.prompt[:80]}..."
            )

    # ── Command Handlers ─────────────────────────────────────

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return

        await update.message.reply_text(
            "Nimbus — Mobile AI Command Center\n\n"
            "Send any message to run a Claude task.\n\n"
            "Prefixes:\n"
            "  @agent message — Route to agent\n"
            "  #project message — Run in project\n"
            "  @agent #project message — Both\n"
            "  .slash — Claude slash command\n"
            "  $ command — Direct shell\n\n"
            "Use the buttons below or type /help for commands.",
            reply_markup=self.main_keyboard()
        )

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        await update.message.reply_text(
            "Commands:\n"
            "/status — System status + running tasks\n"
            "/tasks — List recent tasks\n"
            "/task <id> — View task result\n"
            "/cancel <id> — Cancel a task\n"
            "/projects — List projects\n"
            "/agents — List available agents\n"
            "/bash <cmd> — Run shell command\n"
            "/deploy <project> — Deploy a project\n"
            "/screen — Terminal screenshot\n"
            "/costs — Today's spending\n"
            "/menu — Show quick action buttons\n\n"
            "Smart Prefixes:\n"
            "  @gohan fix the navbar\n"
            "  #marche add search to products page\n"
            "  @goku #marche optimize the API\n"
            "  $ docker ps\n"
            "  .commit"
        )

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        await self._send_status(update.message)

    async def _send_status(self, message_or_query):
        status = self.sessions.get_status()
        today = status["today"]

        text = (
            "NIMBUS STATUS\n\n"
            f"Running: {status['running']}/{status['max_concurrent']} slots\n"
            f"Queued: {status['queued']}\n\n"
            f"Today:\n"
            f"  Completed: {today.get('completed', 0)}\n"
            f"  Failed: {today.get('failed', 0)}\n"
            f"  Cost: ${today.get('total_cost', 0):.4f}\n"
        )

        if status["running_tasks"]:
            text += "\nActive Tasks:\n"
            for t in status["running_tasks"]:
                elapsed = int(time.time() - t.created_at)
                text += f"  #{t.id} ({elapsed}s) {t.prompt[:40]}...\n"

        if status["queued_tasks"]:
            text += "\nQueued:\n"
            for t in status["queued_tasks"]:
                text += f"  #{t.id} {t.prompt[:40]}...\n"

        if hasattr(message_or_query, 'reply_text'):
            await message_or_query.reply_text(text, reply_markup=self.main_keyboard())
        else:
            await message_or_query.edit_message_text(text, reply_markup=self.main_keyboard())

    async def cmd_tasks(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        tasks = self.store.get_recent_tasks(10)
        if not tasks:
            await update.message.reply_text("No tasks yet.")
            return

        lines = ["Recent Tasks:\n"]
        for t in tasks:
            icon = {"completed": "ok", "failed": "err", "running": ">>",
                    "queued": "..", "cancelled": "xx"}.get(t.status.value, "?")
            proj = f"[{t.project}]" if t.project else ""
            agent = f"@{t.agent}" if t.agent else ""
            cost = f"${t.cost_usd:.3f}" if t.cost_usd else ""
            lines.append(f"  [{icon}] #{t.id} {proj}{agent} {t.prompt[:35]}... {cost}")

        await update.message.reply_text("\n".join(lines))

    async def cmd_task_detail(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /task <id>")
            return

        try:
            task_id = int(args[0])
        except ValueError:
            await update.message.reply_text("Invalid task ID.")
            return

        task = self.store.get_task(task_id)
        if not task:
            await update.message.reply_text(f"Task #{task_id} not found.")
            return

        result = task.result or "(no result yet)"
        text = (
            f"Task #{task.id} — {task.status.value}\n"
            f"Prompt: {task.prompt[:200]}\n"
        )
        if task.project:
            text += f"Project: {task.project}\n"
        if task.agent:
            text += f"Agent: {task.agent}\n"
        text += (
            f"Cost: ${task.cost_usd:.4f}\n"
            f"Duration: {task.duration_ms/1000:.1f}s\n\n"
            f"{result}"
        )

        for chunk in split_message(text):
            await update.message.reply_text(chunk)

    async def cmd_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /cancel <task_id>")
            return
        try:
            task_id = int(args[0])
        except ValueError:
            await update.message.reply_text("Invalid task ID.")
            return

        ok = await self.sessions.cancel_task(task_id)
        await update.message.reply_text(
            f"Task #{task_id} cancelled." if ok else f"Task #{task_id} not found or not cancellable."
        )

    async def cmd_projects(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        projects = self.config.get("projects", {})
        if not projects:
            await update.message.reply_text("No projects configured.")
            return

        lines = ["Projects:\n"]
        for name, info in projects.items():
            lines.append(f"  #{name} — {info.get('description', '')}")

        await update.message.reply_text(
            "\n".join(lines) + "\n\nTap a project or use: #project your message",
            reply_markup=self.project_keyboard()
        )

    async def cmd_agents(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        agents = self.config.get("agents", {})
        if not agents:
            await update.message.reply_text("No agents configured.")
            return

        lines = ["Agents:\n"]
        for name, info in agents.items():
            lines.append(f"  @{name} — {info.get('description', '')}")

        await update.message.reply_text(
            "\n".join(lines) + "\n\nTap an agent or use: @agent your message",
            reply_markup=self.agent_keyboard()
        )

    async def cmd_bash(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self.check_access(update):
            return
        cmd_text = update.message.text.replace("/bash", "", 1).strip()
        if not cmd_text:
            await update.message.reply_text("Usage: /bash <command>")
            return

        # Command filtering
        allowed, reason = self.cmd_filter.is_allowed(cmd_text)
        if not allowed:
            self.audit.log_action(str(update.effective_chat.id), "BASH_BLOCKED", f"{reason}: {cmd_text[:100]}")
            await update.message.reply_text(f"Command blocked: {reason}")
            return

        self.audit.log_bash(str(update.effective_chat.id), cmd_text)
        await update.message.reply_text(f"$ {cmd_text[:60]}...")
        cwd = self.config.get("paths", {}).get("working_dir", "~/automation")
        result = await self.engine.run_bash(cmd_text, cwd=cwd)
        for chunk in split_message(result):
            await update.message.reply_text(chunk)

    async def cmd_deploy(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        args = ctx.args
        if not args:
            await update.message.reply_text(
                "Usage: /deploy <project>",
                reply_markup=self.project_keyboard()
            )
            return

        project_name = args[0]
        projects = self.config.get("projects", {})
        if project_name not in projects:
            await update.message.reply_text(f"Unknown project: {project_name}")
            return

        proj = projects[project_name]
        deploy_cmd = proj.get("deploy_cmd")
        if not deploy_cmd:
            # Use Claude to figure out deployment
            prompt = f"Deploy the project at {proj['path']}. Run the build and deploy steps."
        else:
            prompt = f"Run the following deployment for {project_name}: cd {proj['path']} && {deploy_cmd}. Report the result."

        await update.message.reply_text(
            f"Deploying {project_name}...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=f"deploy:cancel:{project_name}")]
            ])
        )

        status_msg = await self.app.bot.send_message(
            chat_id=self.chat_id,
            text=f"Deploy #{project_name} — starting..."
        )

        await self.sessions.submit_task(
            prompt=prompt, project=project_name,
            telegram_msg_id=status_msg.message_id,
            on_stream=self._on_stream,
            on_complete=self._on_complete,
        )

    async def cmd_screen(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Grab recent shell history / process info as a status snapshot."""
        if not self.is_authorized(update.effective_chat.id):
            return
        cwd = self.config.get("paths", {}).get("working_dir", "~/automation")
        output = await self.engine.run_bash(
            "ps aux --sort=-%mem | head -20 && echo '---' && docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true",
            cwd=cwd
        )
        for chunk in split_message(output):
            await update.message.reply_text(chunk)

    async def cmd_costs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        stats = self.store.get_today_stats()
        text = (
            "Today's Costs:\n\n"
            f"  Tasks: {stats.get('total', 0)}\n"
            f"  Completed: {stats.get('completed', 0)}\n"
            f"  Failed: {stats.get('failed', 0)}\n"
            f"  Total Cost: ${stats.get('total_cost', 0):.4f}\n"
            f"  Total Time: {stats.get('total_duration', 0)/1000:.0f}s"
        )
        await update.message.reply_text(text)

    async def cmd_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update.effective_chat.id):
            return
        await update.message.reply_text("Quick actions:", reply_markup=self.main_keyboard())

    # ── Callback Query Handler ───────────────────────────────

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self.is_authorized(query.message.chat_id):
            return
        await query.answer()

        data = query.data

        if data == "cmd:status":
            await self._send_status(query)
        elif data == "cmd:tasks":
            tasks = self.store.get_recent_tasks(8)
            if not tasks:
                await query.edit_message_text("No tasks yet.", reply_markup=self.main_keyboard())
                return
            lines = ["Recent Tasks:\n"]
            for t in tasks:
                icon = {"completed": "ok", "failed": "err", "running": ">>",
                        "queued": "..", "cancelled": "xx"}.get(t.status.value, "?")
                lines.append(f"  [{icon}] #{t.id} {t.prompt[:40]}...")
            await query.edit_message_text("\n".join(lines), reply_markup=self.main_keyboard())
        elif data == "cmd:screen":
            await query.edit_message_text("Capturing screen...")
            cwd = self.config.get("paths", {}).get("working_dir", "~/automation")
            output = await self.engine.run_bash(
                "ps aux --sort=-%mem | head -15 && echo '---' && docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true",
                cwd=cwd
            )
            await query.edit_message_text(output[:TG_MAX_LEN] or "(empty)", reply_markup=self.main_keyboard())
        elif data == "cmd:projects":
            projects = self.config.get("projects", {})
            lines = ["Tap a project to work in it:\n"]
            for name, info in projects.items():
                lines.append(f"  #{name} — {info.get('description', '')}")
            await query.edit_message_text("\n".join(lines), reply_markup=self.project_keyboard())
        elif data == "cmd:agents":
            agents = self.config.get("agents", {})
            lines = ["Tap an agent to assign work:\n"]
            for name, info in agents.items():
                lines.append(f"  @{name} — {info.get('description', '')}")
            await query.edit_message_text("\n".join(lines), reply_markup=self.agent_keyboard())
        elif data == "cmd:main":
            await query.edit_message_text("Quick actions:", reply_markup=self.main_keyboard())
        elif data == "cmd:bash_prompt":
            await query.edit_message_text(
                "Send a shell command with $ prefix:\n\n"
                "  $ docker ps\n"
                "  $ df -h\n"
                "  $ git log --oneline -5",
                reply_markup=self.main_keyboard()
            )
        elif data.startswith("project:"):
            project_name = data.split(":", 1)[1]
            proj = self.config.get("projects", {}).get(project_name, {})
            ctx.user_data["active_project"] = project_name
            buttons = [
                [InlineKeyboardButton("Send Task", callback_data=f"proj_action:task:{project_name}")],
            ]
            if proj.get("deploy_cmd"):
                buttons[0].append(InlineKeyboardButton("Deploy", callback_data=f"proj_action:deploy:{project_name}"))
            if proj.get("test_cmd"):
                buttons[0].append(InlineKeyboardButton("Test", callback_data=f"proj_action:test:{project_name}"))
            buttons.append([InlineKeyboardButton("Back", callback_data="cmd:projects")])

            await query.edit_message_text(
                f"Project: {project_name}\n{proj.get('description', '')}\nPath: {proj.get('path', '?')}\n\nYour next message will run in this project context.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        elif data.startswith("agent:"):
            agent_name = data.split(":", 1)[1]
            agent = self.config.get("agents", {}).get(agent_name, {})
            ctx.user_data["active_agent"] = agent_name
            await query.edit_message_text(
                f"Agent: @{agent_name}\n{agent.get('description', '')}\n\nYour next message will be routed to this agent.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back", callback_data="cmd:agents")]
                ])
            )
        elif data.startswith("task:view:"):
            task_id = int(data.split(":")[-1])
            task = self.store.get_task(task_id)
            if task:
                result = task.result or "(no result)"
                await self.app.bot.send_message(chat_id=self.chat_id, text=result[:TG_MAX_LEN])
        elif data.startswith("task:cancel:"):
            task_id = int(data.split(":")[-1])
            ok = await self.sessions.cancel_task(task_id)
            await query.edit_message_text(
                f"Task #{task_id} {'cancelled' if ok else 'not found'}.",
                reply_markup=self.main_keyboard()
            )
        elif data.startswith("proj_action:deploy:"):
            project_name = data.split(":")[-1]
            proj = self.config.get("projects", {}).get(project_name, {})
            deploy_cmd = proj.get("deploy_cmd", "")
            prompt = f"Deploy {project_name}: cd {proj.get('path', '.')} && {deploy_cmd}" if deploy_cmd else f"Deploy the project at {proj.get('path', '.')}"
            status_msg = await self.app.bot.send_message(
                chat_id=self.chat_id, text=f"Deploying {project_name}..."
            )
            await self.sessions.submit_task(
                prompt=prompt, project=project_name,
                telegram_msg_id=status_msg.message_id,
                on_stream=self._on_stream, on_complete=self._on_complete,
            )
        elif data.startswith("proj_action:test:"):
            project_name = data.split(":")[-1]
            proj = self.config.get("projects", {}).get(project_name, {})
            test_cmd = proj.get("test_cmd", "npm test")
            prompt = f"Run tests for {project_name}: cd {proj.get('path', '.')} && {test_cmd}. Report results."
            status_msg = await self.app.bot.send_message(
                chat_id=self.chat_id, text=f"Testing {project_name}..."
            )
            await self.sessions.submit_task(
                prompt=prompt, project=project_name,
                telegram_msg_id=status_msg.message_id,
                on_stream=self._on_stream, on_complete=self._on_complete,
            )
        elif data.startswith("proj_action:task:"):
            project_name = data.split(":")[-1]
            ctx.user_data["active_project"] = project_name
            await query.edit_message_text(
                f"Send your task for #{project_name}:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back", callback_data=f"project:{project_name}")]
                ])
            )

    # ── File / Photo / Voice Handlers ────────────────────────

    async def handle_document(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self.check_access(update):
            return

        doc = update.message.document
        self.audit.log_file_upload(str(update.effective_chat.id), doc.file_name or "unknown")
        tg_file = await ctx.bot.get_file(doc.file_id)
        filename = doc.file_name or f"upload_{int(time.time())}"
        filepath = os.path.join(self.upload_dir, filename)
        await tg_file.download_to_drive(filepath)

        caption = update.message.caption or ""
        await update.message.reply_text(f"Saved: {filepath}")

        if caption:
            prompt = f"{caption}\n\nFile is at: {filepath}"
            status_msg = await update.message.reply_text("Processing file...")
            project = ctx.user_data.get("active_project")
            agent = ctx.user_data.get("active_agent")
            await self.sessions.submit_task(
                prompt=prompt, project=project, agent=agent,
                telegram_msg_id=status_msg.message_id,
                on_stream=self._on_stream, on_complete=self._on_complete,
            )

    async def handle_photo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self.check_access(update):
            return

        photo = update.message.photo[-1]
        tg_file = await ctx.bot.get_file(photo.file_id)
        filename = f"photo_{int(time.time())}.jpg"
        filepath = os.path.join(self.upload_dir, filename)
        await tg_file.download_to_drive(filepath)

        caption = update.message.caption or ""
        await update.message.reply_text(f"Photo saved: {filepath}")

        if caption:
            prompt = f"{caption}\n\nImage is at: {filepath}"
            status_msg = await update.message.reply_text("Analyzing image...")
            await self.sessions.submit_task(
                prompt=prompt, telegram_msg_id=status_msg.message_id,
                on_stream=self._on_stream, on_complete=self._on_complete,
            )

    async def handle_voice(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self.check_access(update):
            return

        voice = update.message.voice
        tg_file = await ctx.bot.get_file(voice.file_id)
        filename = f"voice_{int(time.time())}.ogg"
        filepath = os.path.join(self.upload_dir, filename)
        await tg_file.download_to_drive(filepath)

        await update.message.reply_text(
            f"Voice saved: {filepath}\n"
            "Voice transcription coming in a future update."
        )

    # ── Main Message Handler ─────────────────────────────────

    async def handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await self.check_access(update):
            return

        text = update.message.text
        if not text:
            return

        # ── Parse smart prefixes ──

        # $ command — direct bash
        if text.startswith('$'):
            cmd = text[1:].strip()
            if cmd:
                # Command filtering
                allowed, reason = self.cmd_filter.is_allowed(cmd)
                if not allowed:
                    self.audit.log_action(str(update.effective_chat.id), "BASH_BLOCKED", f"{reason}: {cmd[:100]}")
                    await update.message.reply_text(f"Command blocked: {reason}")
                    return
                self.audit.log_bash(str(update.effective_chat.id), cmd)
                cwd = self.config.get("paths", {}).get("working_dir", "~/automation")
                result = await self.engine.run_bash(cmd, cwd=cwd)
                for chunk in split_message(f"$ {cmd}\n\n{result}"):
                    await update.message.reply_text(chunk)
                return

        # .slash — Claude slash command
        if text.startswith('.') and not text.startswith('..'):
            text = '/' + text[1:]

        # @agent — extract agent
        agent = ctx.user_data.get("active_agent")
        project = ctx.user_data.get("active_project")

        agent_match = re.match(r'^@(\w+)\s+', text)
        if agent_match:
            agent = agent_match.group(1)
            text = text[agent_match.end():]

        # #project — extract project
        project_match = re.match(r'^#(\w[\w-]*)\s+', text)
        if project_match:
            project = project_match.group(1)
            text = text[project_match.end():]

        # Validate agent/project
        if agent and agent not in self.config.get("agents", {}):
            await update.message.reply_text(
                f"Unknown agent: @{agent}\n\nAvailable: {', '.join(self.config.get('agents', {}).keys())}"
            )
            return

        if project and project not in self.config.get("projects", {}):
            await update.message.reply_text(
                f"Unknown project: #{project}\n\nAvailable: {', '.join(self.config.get('projects', {}).keys())}"
            )
            return

        # ── Submit task ──
        label = ""
        if project:
            label += f"[{project}] "
        if agent:
            label += f"@{agent} "

        status_msg = await update.message.reply_text(
            f"{label}Processing...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data="task:cancel:pending")]
            ])
        )

        self.audit.log_task(str(update.effective_chat.id), text, project or "", agent or "")

        task = await self.sessions.submit_task(
            prompt=text, project=project, agent=agent,
            telegram_msg_id=status_msg.message_id,
            on_stream=self._on_stream,
            on_complete=self._on_complete,
        )

        # Update cancel button with real task ID
        try:
            await status_msg.edit_reply_markup(
                reply_markup=self.task_actions_keyboard(task.id)
            )
        except Exception:
            pass

    # ── Status Board ─────────────────────────────────────────

    async def _update_status_board(self):
        """Update the pinned status message."""
        if not self.config.get("status", {}).get("pin_message", True):
            return
        if not self.app:
            return

        status = self.sessions.get_status()
        today = status["today"]

        text = (
            "NIMBUS\n"
            f"Slots: {status['running']}/{status['max_concurrent']} | "
            f"Queue: {status['queued']}\n"
            f"Today: {today.get('completed', 0)} done | "
            f"${today.get('total_cost', 0):.3f} spent"
        )

        try:
            if self.pinned_msg_id:
                await self.app.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.pinned_msg_id,
                    text=text,
                    reply_markup=self.main_keyboard()
                )
            else:
                msg = await self.app.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    reply_markup=self.main_keyboard()
                )
                self.pinned_msg_id = msg.message_id
                try:
                    await self.app.bot.pin_chat_message(
                        chat_id=self.chat_id,
                        message_id=msg.message_id,
                        disable_notification=True
                    )
                except Exception:
                    pass
        except Exception as e:
            log.error(f"Status board update failed: {e}")

    # ── Bot Setup & Run ──────────────────────────────────────

    async def _post_init(self, application):
        """Register bot commands with Telegram."""
        self.app = application
        commands = [
            BotCommand("start", "Welcome + help"),
            BotCommand("help", "All commands"),
            BotCommand("status", "System status"),
            BotCommand("tasks", "Recent tasks"),
            BotCommand("task", "View task detail"),
            BotCommand("cancel", "Cancel a task"),
            BotCommand("projects", "List projects"),
            BotCommand("agents", "List agents"),
            BotCommand("bash", "Run shell command"),
            BotCommand("deploy", "Deploy a project"),
            BotCommand("screen", "Terminal screenshot"),
            BotCommand("costs", "Today's spending"),
            BotCommand("menu", "Quick action buttons"),
        ]
        await application.bot.set_my_commands(commands)
        self.sessions.start()
        await self._update_status_board()
        log.info("Nimbus bot initialized")

    def run(self):
        log.info("Starting Nimbus...")
        app = ApplicationBuilder().token(self.token).post_init(self._post_init).build()

        # Commands
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("tasks", self.cmd_tasks))
        app.add_handler(CommandHandler("task", self.cmd_task_detail))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        app.add_handler(CommandHandler("projects", self.cmd_projects))
        app.add_handler(CommandHandler("agents", self.cmd_agents))
        app.add_handler(CommandHandler("bash", self.cmd_bash))
        app.add_handler(CommandHandler("deploy", self.cmd_deploy))
        app.add_handler(CommandHandler("screen", self.cmd_screen))
        app.add_handler(CommandHandler("costs", self.cmd_costs))
        app.add_handler(CommandHandler("menu", self.cmd_menu))

        # Callbacks
        app.add_handler(CallbackQueryHandler(self.handle_callback))

        # Media
        app.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))

        # Text (catch-all)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        log.info("Nimbus is polling...")
        app.run_polling(drop_pending_updates=True)
