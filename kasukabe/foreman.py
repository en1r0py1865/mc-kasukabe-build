"""Foreman — orchestrates the build pipeline state machine."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from kasukabe.agents.architect import Architect
from kasukabe.agents.builder import Builder
from kasukabe.agents.inspector import Inspector
from kasukabe.agents.planner import Planner
from kasukabe.models import PipelineBlocked, SessionState
from kasukabe.video_processor import VideoProcessingError, extract_keyframes

MAX_ITERATIONS = 3
COMPLETION_THRESHOLD = 0.85

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


class Foreman:
    """Orchestrates the full build pipeline from input to completion.

    State machine:
      INIT → [VIDEO_PROCESS] → ARCHITECT → (PLANNER → BUILDER → INSPECTOR)× ≤3 → DONE
    """

    def __init__(
        self,
        workspace_root: Path | str = "workspace",
        api_key: str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def run(
        self,
        input_path: str,
        origin: tuple[int, int, int] = (100, 64, 200),
        size: tuple[int, int, int] = (0, 0, 0),
    ) -> SessionState:
        """Run the full pipeline for a given input.

        Args:
            input_path: Path to an image (jpg/png) or video (mp4/mov/etc.).
            origin: World coordinates where the build starts (x, y, z).
            size: Desired build size (W, H, L); (0,0,0) means auto-detect.

        Returns:
            Final SessionState with completion_rate set.

        Raises:
            PipelineBlocked: If any stage cannot proceed.
        """
        session = self._init_session(input_path, origin, size)
        self._log(session, f"Session {session.session_id} started. Input: {input_path}")

        try:
            # Phase 0: video pre-processing
            if self._is_video(input_path):
                session.phase = "VIDEO_PROCESS"
                self._run_video_process(session)

            # Phase 1: Architect (once per session)
            session.phase = "ARCHITECT"
            self._run_architect(session)

            # Phases 2–4: iterate Planner → Builder → Inspector
            for iteration in range(1, MAX_ITERATIONS + 1):
                session.iteration = iteration
                fix_commands = self._read_fix_commands(session) if iteration > 1 else None

                session.phase = "PLANNER"
                self._run_planner(session, fix_commands)

                session.phase = "BUILDER"
                self._run_builder(session)

                session.phase = "INSPECTOR"
                self._run_inspector(session)

                session.completion_rate = self._read_completion_rate(session)
                self._log(
                    session,
                    f"Iteration {iteration}: completion_rate={session.completion_rate:.1%}",
                )

                if session.completion_rate >= COMPLETION_THRESHOLD:
                    self._log(session, "Threshold reached — stopping iterations.")
                    break

                if not self._read_should_continue(session):
                    self._log(session, "Inspector says no further iteration needed.")
                    break

            session.phase = "DONE"

        except PipelineBlocked as exc:
            session.phase = "FAILED"
            session.failure_reason = str(exc)
            self._write_summary(session)
            raise

        self._write_summary(session)
        return session

    # ── Phase runners ─────────────────────────────────────────────────────────

    def _run_video_process(self, session: SessionState) -> None:
        frames_dir = session.workspace_dir / "frames"
        self._log(session, "Extracting video frames…")
        try:
            frames = extract_keyframes(session.input_path, frames_dir)
            self._log(session, f"Extracted {len(frames)} frames.")
        except VideoProcessingError as exc:
            raise PipelineBlocked(f"Video processing failed: {exc}") from exc

    def _run_architect(self, session: SessionState) -> None:
        self._log(session, "Running Architect (vision analysis)…")
        architect = Architect(api_key=self._api_key)
        architect.analyze(session)
        self._log(session, "Architect done → blueprint.json written.")

    def _run_planner(self, session: SessionState, fix_commands: list[str] | None) -> None:
        self._log(session, f"Running Planner (iteration {session.iteration})…")
        planner = Planner(api_key=self._api_key)
        planner.plan(session, fix_commands=fix_commands)
        self._log(session, "Planner done → commands.txt written.")

    def _run_builder(self, session: SessionState) -> None:
        self._log(session, f"Running Builder (iteration {session.iteration})…")
        builder = Builder()
        log = builder.execute(session)
        ok = log.get("commands_ok", 0)
        failed = log.get("commands_failed", 0)
        self._log(session, f"Builder done — {ok} ok, {failed} failed.")

    def _run_inspector(self, session: SessionState) -> None:
        self._log(session, f"Running Inspector (iteration {session.iteration})…")
        inspector = Inspector(api_key=self._api_key)
        report = inspector.inspect(session)
        rate = report.get("completion_rate", 0.0)
        self._log(session, f"Inspector done — completion_rate={rate:.1%}.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _init_session(
        self,
        input_path: str,
        origin: tuple[int, int, int],
        size: tuple[int, int, int],
    ) -> SessionState:
        session_id = uuid.uuid4().hex[:12]
        workspace_dir = self.workspace_root / session_id
        workspace_dir.mkdir(parents=True, exist_ok=True)

        session = SessionState(
            session_id=session_id,
            input_path=input_path,
            origin=origin,
            size=size,
            workspace_dir=workspace_dir,
        )

        # Write input_meta.json
        (workspace_dir / "input_meta.json").write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "source_path": str(Path(input_path).resolve()),
                    "source_type": "video" if self._is_video(input_path) else "image",
                    "origin": list(origin),
                    "size": list(size),
                }
            ),
            encoding="utf-8",
        )
        return session

    def _is_video(self, path: str) -> bool:
        return Path(path).suffix.lower() in _VIDEO_EXTENSIONS

    def _read_completion_rate(self, session: SessionState) -> float:
        report_path = session.workspace_dir / "diff_report.json"
        if not report_path.exists():
            return 0.0
        try:
            return json.loads(report_path.read_text())["completion_rate"]
        except Exception:  # noqa: BLE001
            return 0.0

    def _read_should_continue(self, session: SessionState) -> bool:
        report_path = session.workspace_dir / "diff_report.json"
        if not report_path.exists():
            return True
        try:
            return bool(json.loads(report_path.read_text()).get("should_continue", True))
        except Exception:  # noqa: BLE001
            return True

    def _read_fix_commands(self, session: SessionState) -> list[str] | None:
        report_path = session.workspace_dir / "diff_report.json"
        if not report_path.exists():
            return None
        try:
            cmds = json.loads(report_path.read_text()).get("fix_commands", [])
            return cmds if cmds else None
        except Exception:  # noqa: BLE001
            return None

    def _write_summary(self, session: SessionState) -> None:
        (session.workspace_dir / "foreman_summary.json").write_text(
            json.dumps(
                {
                    "session_id": session.session_id,
                    "phase": session.phase,
                    "iterations": session.iteration,
                    "completion_rate": session.completion_rate,
                    "failure_reason": session.failure_reason,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _log(self, session: SessionState, message: str) -> None:
        """Print a timestamped log line."""
        print(f"[kasukabe:{session.session_id[:8]}] {message}")
