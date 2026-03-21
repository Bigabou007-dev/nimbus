"""
Nimbus Sessions — Multi-session task manager.
Manages concurrent Claude tasks with queuing and parallel execution.
"""

import asyncio
import os
import time
import logging
from typing import Optional, Callable, Awaitable

from .store import NimbusStore, Task, TaskStatus
from .engine import NimbusEngine, EngineResult, StreamEvent

log = logging.getLogger(__name__)

# Max parallel Claude tasks
MAX_CONCURRENT = 3


class SessionManager:
    def __init__(self, engine: NimbusEngine, store: NimbusStore, config: dict):
        self.engine = engine
        self.store = store
        self.config = config
        self.active_tasks: dict[int, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._slots_used = 0
        self._queue_processor: Optional[asyncio.Task] = None

    @property
    def slots_available(self) -> int:
        return MAX_CONCURRENT - self._slots_used

    def start(self):
        """Start the background queue processor."""
        if self._queue_processor is None or self._queue_processor.done():
            self._queue_processor = asyncio.create_task(self._process_queue())
            log.info("Session queue processor started")

    async def submit_task(
        self, prompt: str, project: str = None, agent: str = None,
        telegram_msg_id: int = None,
        on_stream: Callable[[StreamEvent, Task], Awaitable] = None,
        on_complete: Callable[[EngineResult, Task], Awaitable] = None
    ) -> Task:
        """Submit a new task. Returns immediately with the Task object."""
        task = self.store.create_task(
            prompt=prompt, project=project, agent=agent,
            telegram_msg_id=telegram_msg_id
        )
        log.info(f"Task #{task.id} created: {prompt[:60]}...")

        # Try to run immediately if we have capacity
        if self.slots_available > 0:
            asyncio.create_task(
                self._run_task(task, on_stream, on_complete)
            )
        else:
            log.info(f"Task #{task.id} queued (all slots busy)")
            if on_stream:
                await on_stream(
                    StreamEvent("queued", f"Task #{task.id} queued — {self.slots_available}/{MAX_CONCURRENT} slots available", {}),
                    task
                )

        return task

    async def _run_task(
        self, task: Task,
        on_stream: Callable[[StreamEvent, Task], Awaitable] = None,
        on_complete: Callable[[EngineResult, Task], Awaitable] = None
    ):
        """Execute a task with the semaphore."""
        async with self.semaphore:
            self._slots_used += 1
            try:
                await self._execute_task(task, on_stream, on_complete)
            finally:
                self._slots_used -= 1

    async def _execute_task(
        self, task: Task,
        on_stream: Callable[[StreamEvent, Task], Awaitable] = None,
        on_complete: Callable[[EngineResult, Task], Awaitable] = None
    ):
        """Core task execution logic."""
        self.store.update_task(task.id, status=TaskStatus.RUNNING)
        task.status = TaskStatus.RUNNING

        # Resolve project path
        project_path = None
        system_prompt = None
        if task.project and task.project in self.config.get("projects", {}):
            proj = self.config["projects"][task.project]
            project_path = proj.get("path")

        # Resolve agent system prompt
        if task.agent and task.agent in self.config.get("agents", {}):
            agent_config = self.config["agents"][task.agent]
            prompt_file = agent_config.get("prompt_file", "")
            if prompt_file:
                prompt_file = os.path.expanduser(prompt_file)
                if os.path.exists(prompt_file):
                    with open(prompt_file) as f:
                        system_prompt = f.read()

        try:
            # Stream events to Telegram
            final_result = None
            async for event in self.engine.run_task_streaming(
                prompt=task.prompt,
                project_path=project_path,
                system_prompt=system_prompt,
            ):
                if on_stream:
                    await on_stream(event, task)

                if event.event_type == "result":
                    raw = event.raw
                    final_result = EngineResult(
                        success=not raw.get("is_error", False),
                        result=raw.get("result", ""),
                        cost_usd=raw.get("total_cost_usd", 0),
                        duration_ms=raw.get("duration_ms", 0),
                        session_id=raw.get("session_id", ""),
                        num_turns=raw.get("num_turns", 0),
                        stop_reason=raw.get("stop_reason", "end_turn")
                    )

            if final_result:
                status = TaskStatus.COMPLETED if final_result.success else TaskStatus.FAILED
                self.store.update_task(
                    task.id,
                    status=status,
                    result=final_result.result[:10000],
                    cost_usd=final_result.cost_usd,
                    duration_ms=final_result.duration_ms,
                    session_id=final_result.session_id,
                    finished_at=time.time()
                )
                if on_complete:
                    await on_complete(final_result, task)
            else:
                self.store.update_task(
                    task.id, status=TaskStatus.FAILED,
                    result="No result received", finished_at=time.time()
                )

        except asyncio.CancelledError:
            self.store.update_task(
                task.id, status=TaskStatus.CANCELLED, finished_at=time.time()
            )
            log.info(f"Task #{task.id} cancelled")
        except Exception as e:
            log.error(f"Task #{task.id} error: {e}")
            self.store.update_task(
                task.id, status=TaskStatus.FAILED,
                result=str(e), finished_at=time.time()
            )
            if on_complete:
                await on_complete(
                    EngineResult(
                        success=False, result=str(e), cost_usd=0,
                        duration_ms=0, session_id="", num_turns=0,
                        stop_reason="error", error=str(e)
                    ),
                    task
                )

    async def cancel_task(self, task_id: int) -> bool:
        """Cancel a running task."""
        if task_id in self.active_tasks:
            self.active_tasks[task_id].cancel()
            del self.active_tasks[task_id]
            return True
        task = self.store.get_task(task_id)
        if task and task.status == TaskStatus.QUEUED:
            self.store.update_task(task_id, status=TaskStatus.CANCELLED, finished_at=time.time())
            return True
        return False

    async def _process_queue(self):
        """Background loop that picks up queued tasks."""
        while True:
            try:
                task = self.store.next_queued()
                if task and self.slots_available > 0:
                    log.info(f"Queue processor picking up task #{task.id}")
                    asyncio.create_task(self._run_task(task))
            except Exception as e:
                log.error(f"Queue processor error: {e}")
            await asyncio.sleep(2)

    def get_status(self) -> dict:
        running = self.store.get_running_tasks()
        queued = self.store.get_queued_tasks()
        stats = self.store.get_today_stats()
        return {
            "running": len(running),
            "queued": len(queued),
            "slots_available": self.slots_available,
            "max_concurrent": MAX_CONCURRENT,
            "today": stats,
            "running_tasks": running,
            "queued_tasks": queued,
        }
