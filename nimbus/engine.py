"""
Nimbus Engine — Claude Code headless mode runner.
Runs tasks via `claude -p` with structured JSON output and real-time streaming.
"""

import asyncio
import json
import os
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

log = logging.getLogger(__name__)


@dataclass
class EngineResult:
    success: bool
    result: str
    cost_usd: float
    duration_ms: int
    session_id: str
    num_turns: int
    stop_reason: str
    error: Optional[str] = None


@dataclass
class StreamEvent:
    """A single event from the Claude streaming output."""
    event_type: str   # init, assistant, tool_use, tool_result, result, error
    content: str      # human-readable content for this event
    raw: dict         # full JSON payload


class NimbusEngine:
    def __init__(self, config: dict):
        self.default_model = config.get("default_model", "opus")
        self.permission_mode = config.get("permission_mode", "bypassPermissions")
        self.max_budget = config.get("max_budget_usd", 5.0)
        self.timeout = config.get("timeout", 600)
        self.default_effort = config.get("default_effort", "high")

    def _build_cmd(self, prompt: str, project_path: str = None,
                   agent: str = None, system_prompt: str = None,
                   model: str = None, streaming: bool = True) -> list[str]:
        cmd = ["claude", "-p", prompt]

        if streaming:
            cmd += ["--output-format", "stream-json", "--verbose"]
        else:
            cmd += ["--output-format", "json"]

        cmd += ["--permission-mode", self.permission_mode]
        cmd += ["--model", model or self.default_model]
        cmd += ["--effort", self.default_effort]
        cmd += ["--max-budget-usd", str(self.max_budget)]

        if system_prompt:
            cmd += ["--system-prompt", system_prompt]

        if agent:
            cmd += ["--agent", agent]

        return cmd

    async def run_task(self, prompt: str, project_path: str = None,
                       agent: str = None, system_prompt: str = None,
                       model: str = None) -> EngineResult:
        """Run a task and return the final result (non-streaming)."""
        cmd = self._build_cmd(
            prompt, project_path, agent, system_prompt, model, streaming=False
        )
        cwd = os.path.expanduser(project_path) if project_path else None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            output = stdout.decode().strip()
            if not output:
                return EngineResult(
                    success=False, result="", cost_usd=0, duration_ms=0,
                    session_id="", num_turns=0, stop_reason="error",
                    error=stderr.decode().strip() or "No output from Claude"
                )

            data = json.loads(output)

            if data.get("is_error"):
                return EngineResult(
                    success=False, result=data.get("result", ""),
                    cost_usd=data.get("total_cost_usd", 0),
                    duration_ms=data.get("duration_ms", 0),
                    session_id=data.get("session_id", ""),
                    num_turns=data.get("num_turns", 0),
                    stop_reason=data.get("stop_reason", "error"),
                    error=data.get("result", "Unknown error")
                )

            return EngineResult(
                success=True,
                result=data.get("result", ""),
                cost_usd=data.get("total_cost_usd", 0),
                duration_ms=data.get("duration_ms", 0),
                session_id=data.get("session_id", ""),
                num_turns=data.get("num_turns", 0),
                stop_reason=data.get("stop_reason", "end_turn")
            )

        except asyncio.TimeoutError:
            return EngineResult(
                success=False, result="", cost_usd=0, duration_ms=self.timeout * 1000,
                session_id="", num_turns=0, stop_reason="timeout",
                error=f"Task timed out after {self.timeout}s"
            )
        except Exception as e:
            return EngineResult(
                success=False, result="", cost_usd=0, duration_ms=0,
                session_id="", num_turns=0, stop_reason="error",
                error=str(e)
            )

    async def run_task_streaming(
        self, prompt: str, project_path: str = None,
        agent: str = None, system_prompt: str = None,
        model: str = None
    ) -> AsyncIterator[StreamEvent]:
        """Run a task with streaming — yields events as Claude works."""
        cmd = self._build_cmd(
            prompt, project_path, agent, system_prompt, model, streaming=True
        )
        cwd = os.path.expanduser(project_path) if project_path else None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
        except Exception as e:
            yield StreamEvent(
                event_type="result",
                content=f"Failed to start Claude: {e}",
                raw={"type": "result", "is_error": True, "result": str(e),
                     "total_cost_usd": 0, "duration_ms": 0, "session_id": "",
                     "num_turns": 0, "stop_reason": "error"}
            )
            return

        deadline = asyncio.get_event_loop().time() + self.timeout

        try:
            async for line in proc.stdout:
                if asyncio.get_event_loop().time() > deadline:
                    log.warning("Streaming task timed out")
                    yield StreamEvent(
                        event_type="result",
                        content=f"Task timed out after {self.timeout}s",
                        raw={"type": "result", "is_error": True,
                             "result": f"Task timed out after {self.timeout}s",
                             "total_cost_usd": 0, "duration_ms": self.timeout * 1000,
                             "session_id": "", "num_turns": 0, "stop_reason": "timeout"}
                    )
                    break

                line = line.decode().strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event = self._parse_stream_event(data)
                if event:
                    yield event

        except (asyncio.CancelledError, GeneratorExit):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return
        except Exception as e:
            log.error(f"Streaming error: {e}")
            yield StreamEvent(
                event_type="result",
                content=f"Streaming error: {e}",
                raw={"type": "result", "is_error": True, "result": str(e),
                     "total_cost_usd": 0, "duration_ms": 0, "session_id": "",
                     "num_turns": 0, "stop_reason": "error"}
            )
        finally:
            try:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
            except Exception:
                pass

    def _parse_stream_event(self, data: dict) -> Optional[StreamEvent]:
        event_type = data.get("type", "")

        if event_type == "system" and data.get("subtype") == "init":
            return StreamEvent(
                event_type="init",
                content=f"Session started (model: {data.get('model', '?')})",
                raw=data
            )

        elif event_type == "assistant":
            msg = data.get("message", {})
            content_parts = msg.get("content", [])
            text_parts = []
            for part in content_parts:
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "tool_use":
                    tool_name = part.get("name", "?")
                    tool_input = part.get("input", {})
                    # Summarize tool use
                    if tool_name == "Bash":
                        cmd = tool_input.get("command", "")[:100]
                        text_parts.append(f"[Running: {cmd}]")
                    elif tool_name == "Edit":
                        fp = tool_input.get("file_path", "?")
                        text_parts.append(f"[Editing: {os.path.basename(fp)}]")
                    elif tool_name == "Write":
                        fp = tool_input.get("file_path", "?")
                        text_parts.append(f"[Creating: {os.path.basename(fp)}]")
                    elif tool_name == "Read":
                        fp = tool_input.get("file_path", "?")
                        text_parts.append(f"[Reading: {os.path.basename(fp)}]")
                    elif tool_name in ("Glob", "Grep"):
                        text_parts.append("[Searching...]")
                    else:
                        text_parts.append(f"[Tool: {tool_name}]")

            content = "\n".join(text_parts)
            if content.strip():
                return StreamEvent(event_type="assistant", content=content, raw=data)

        elif event_type == "result":
            result_text = data.get("result", "")
            cost = data.get("total_cost_usd", 0)
            duration = data.get("duration_ms", 0)
            turns = data.get("num_turns", 0)

            summary = f"{result_text}\n\n---\n"
            summary += f"Cost: ${cost:.4f} | {duration/1000:.1f}s | {turns} turn(s)"
            return StreamEvent(event_type="result", content=summary, raw=data)

        return None

    async def run_bash(self, command: str, cwd: str = None, timeout: int = 30) -> str:
        """Run a shell command directly (no Claude)."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.expanduser(cwd) if cwd else None
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            output = stdout.decode().strip()
            if stderr.decode().strip():
                output += f"\n\nSTDERR:\n{stderr.decode().strip()}"
            return output or "(no output)"
        except asyncio.TimeoutError:
            return f"Command timed out after {timeout}s"
        except Exception as e:
            return f"Error: {e}"
