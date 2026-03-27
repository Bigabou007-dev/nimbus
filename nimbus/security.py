"""
Nimbus Security — Rate limiting, passphrase auth, audit logging, command filtering.
"""

import hashlib
import hmac
import logging
import os
import time
from collections import defaultdict

log = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter per chat ID."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, chat_id: str) -> bool:
        now = time.time()
        key = str(chat_id)

        # Prune old entries
        self._requests[key] = [
            t for t in self._requests[key] if now - t < self.window
        ]

        if len(self._requests[key]) >= self.max_requests:
            return False

        self._requests[key].append(now)
        return True

    def remaining(self, chat_id: str) -> int:
        now = time.time()
        key = str(chat_id)
        active = [t for t in self._requests.get(key, []) if now - t < self.window]
        return max(0, self.max_requests - len(active))


class PassphraseAuth:
    """
    Optional passphrase gate. When enabled, a user must send the correct
    passphrase before the bot responds to any commands. Session persists
    until the bot restarts.
    """

    def __init__(self, passphrase: str = None):
        self.enabled = passphrase is not None and passphrase.strip() != ""
        self._hash = hashlib.sha256(passphrase.encode()).hexdigest() if self.enabled else None
        self._authenticated: set[str] = set()

    def is_authenticated(self, chat_id: str) -> bool:
        if not self.enabled:
            return True
        return str(chat_id) in self._authenticated

    def attempt(self, chat_id: str, passphrase: str) -> bool:
        if not self.enabled:
            return True
        candidate = hashlib.sha256(passphrase.strip().encode()).hexdigest()
        if hmac.compare_digest(candidate, self._hash):
            self._authenticated.add(str(chat_id))
            log.info(f"Chat {chat_id} authenticated via passphrase")
            return True
        log.warning(f"Failed passphrase attempt from chat {chat_id}")
        return False

    def revoke(self, chat_id: str):
        self._authenticated.discard(str(chat_id))


class AuditLog:
    """Append-only audit log for all bot actions."""

    def __init__(self, log_path: str = "~/.nimbus/audit.log"):
        self.log_path = os.path.expanduser(log_path)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def log_action(self, chat_id: str, action: str, detail: str = ""):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp} | chat:{chat_id} | {action}"
        if detail:
            # Truncate long details and strip newlines for single-line entries
            detail_clean = detail.replace("\n", " ")[:200]
            entry += f" | {detail_clean}"
        entry += "\n"

        try:
            with open(self.log_path, "a") as f:
                f.write(entry)
        except Exception as e:
            log.error(f"Audit log write failed: {e}")

    def log_unauthorized(self, chat_id: str, username: str = ""):
        self.log_action(
            str(chat_id),
            "UNAUTHORIZED_ACCESS",
            f"username={username}"
        )

    def log_rate_limited(self, chat_id: str):
        self.log_action(str(chat_id), "RATE_LIMITED")

    def log_task(self, chat_id: str, prompt: str, project: str = "", agent: str = ""):
        detail = prompt[:150]
        if project:
            detail = f"[{project}] {detail}"
        if agent:
            detail = f"@{agent} {detail}"
        self.log_action(str(chat_id), "TASK_SUBMITTED", detail)

    def log_bash(self, chat_id: str, command: str):
        self.log_action(str(chat_id), "BASH_COMMAND", command[:200])

    def log_file_upload(self, chat_id: str, filename: str):
        self.log_action(str(chat_id), "FILE_UPLOAD", filename)

    def log_auth_attempt(self, chat_id: str, success: bool):
        self.log_action(
            str(chat_id),
            "AUTH_SUCCESS" if success else "AUTH_FAILED"
        )


class CommandFilter:
    """
    Blocklist for dangerous shell commands.
    Only applies to /bash and $ prefix commands.
    """

    # Patterns that should never run via the bot
    DEFAULT_BLOCKLIST = [
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=",
        "> /dev/sd",
        ":(){ :|:",       # fork bomb
        "chmod -R 777 /",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "init 0",
        "init 6",
    ]

    def __init__(self, blocklist: list[str] = None, allowlist: list[str] = None):
        self.blocklist = blocklist or self.DEFAULT_BLOCKLIST
        self.allowlist = allowlist  # if set, ONLY these commands are allowed

    def is_allowed(self, command: str) -> tuple[bool, str]:
        cmd_lower = command.lower().strip()

        # If allowlist is set, command must match one of the patterns
        if self.allowlist is not None:
            for pattern in self.allowlist:
                if cmd_lower.startswith(pattern.lower()):
                    return True, ""
            return False, "Command not in allowlist"

        # Check blocklist
        for pattern in self.blocklist:
            if pattern.lower() in cmd_lower:
                return False, f"Blocked: matches dangerous pattern '{pattern}'"

        return True, ""
