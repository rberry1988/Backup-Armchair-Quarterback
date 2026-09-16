"""Self-update: git pull the latest committed code, reinstall any new
dependencies, rebuild the frontend, then restart so the new code actually
takes effect. Gated behind ENABLE_SELF_UPDATE (see config.py) since it's
meaningfully more powerful than anything else behind the admin gate — it
runs whatever code the next commit happens to contain.

Only meaningful for the standard systemd deployment (see
deploy/install.sh): that script makes the app directory itself a git
checkout the service user owns outright, which is what lets this update
in place with no elevated permissions at all — and the systemd unit's
`Restart=always` is what actually brings the process back after this
deliberately exits. Run any other way (e.g. `uvicorn --reload` in local
dev), the restart step just kills the process with nothing supervising
it to bring it back.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_DIR = REPO_ROOT / "backend"
VENV_PIP = BACKEND_DIR / ".venv" / "bin" / "pip"
VENV_PYTHON = BACKEND_DIR / ".venv" / "bin" / "python"

# Generous: a cold `npm install` after a dependency bump can genuinely take
# a couple of minutes. nginx's proxy_read_timeout is raised to match (see
# deploy/nginx.conf.template) so the request doesn't get cut off first.
STEP_TIMEOUT_SECONDS = 240
# How long to wait after responding before exiting, so the HTTP response
# actually reaches the browser before the process disappears.
RESTART_DELAY_SECONDS = 1.5
OUTPUT_TAIL_CHARS = 4000


def _run(cmd: list[str], cwd: Path) -> dict:
    """Run one step, capturing enough to explain a failure without piping
    an unbounded build log back to the browser."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=STEP_TIMEOUT_SECONDS
        )
        output = (result.stdout + result.stderr).strip()
        return {
            "command": " ".join(cmd),
            "ok": result.returncode == 0,
            "output": output[-OUTPUT_TAIL_CHARS:],
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(cmd),
            "ok": False,
            "output": f"Timed out after {STEP_TIMEOUT_SECONDS}s",
        }
    except OSError as exc:
        return {"command": " ".join(cmd), "ok": False, "output": str(exc)}


def _schedule_restart() -> None:
    def _exit_later() -> None:
        time.sleep(RESTART_DELAY_SECONDS)
        os._exit(0)

    threading.Thread(target=_exit_later, daemon=True).start()


def run_update() -> dict:
    """Best-effort, fully synchronous (the caller's HTTP request blocks for
    the duration): pull, reinstall, rebuild, then schedule a restart. Stops
    at the first failed step rather than leaving things half-upgraded, and
    never touches anything if there was nothing new to pull."""
    if not (REPO_ROOT / ".git").is_dir():
        return {
            "error": "not_a_git_checkout",
            "detail": (
                f"{REPO_ROOT} isn't a git checkout, so there's nothing to pull. This only "
                "works when deploy/install.sh deployed the app (it clones directly into "
                "place for exactly this reason)."
            ),
        }

    before = _run(["git", "rev-parse", "HEAD"], REPO_ROOT)
    if not before["ok"]:
        return {"error": "git_failed", "steps": [before]}

    pull = _run(["git", "pull", "--ff-only"], REPO_ROOT)
    steps = [pull]
    if not pull["ok"]:
        return {"error": "git_pull_failed", "steps": steps}

    after = _run(["git", "rev-parse", "HEAD"], REPO_ROOT)
    steps.append(after)
    changed = after["ok"] and before["output"] != after["output"]

    if not changed:
        return {"changed": False, "steps": steps, "restarting": False}

    # The venv's own pip if this is a real deployment; falling back to
    # `python -m pip` only matters for exercising this function somewhere
    # without a backend/.venv (e.g. tests).
    # --timeout/--retries because pip's defaults give up quickly on a slow
    # mirror, and a dependency bump that downloads several large wheels is
    # exactly when that bites. A blip here used to leave the venv
    # half-upgraded; the preflight below is the backstop for when it still
    # does.
    pip_flags = ["install", "-q", "--timeout", "60", "--retries", "5", "-r", "requirements.txt"]
    pip_cmd = (
        [str(VENV_PIP), *pip_flags] if VENV_PIP.exists() else [sys.executable, "-m", "pip", *pip_flags]
    )
    pip_step = _run(pip_cmd, BACKEND_DIR)
    steps.append(pip_step)
    if not pip_step["ok"]:
        return {"error": "pip_install_failed", "changed": True, "steps": steps, "restarting": False}

    npm_install = _run(["npm", "install", "--no-fund", "--no-audit"], FRONTEND_DIR)
    steps.append(npm_install)
    if not npm_install["ok"]:
        return {"error": "npm_install_failed", "changed": True, "steps": steps, "restarting": False}

    npm_build = _run(["npm", "run", "build"], FRONTEND_DIR)
    steps.append(npm_build)
    if not npm_build["ok"]:
        return {"error": "npm_build_failed", "changed": True, "steps": steps, "restarting": False}

    # Never restart into a build that can't start. If pip died partway
    # through (a network timeout mid-download is the realistic case) the
    # venv is left importable-but-broken, and restarting would take a
    # working app offline with no way back in through the UI — the Admin
    # tab that triggered this is behind the login it just broke. Importing
    # the app in a subprocess is the cheapest honest check that the new
    # code actually runs; failing it leaves the current process serving
    # the old code, which is the safe side to fail on.
    python_cmd = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    preflight = _run([python_cmd, "-c", "import app.main"], BACKEND_DIR)
    steps.append(preflight)
    if not preflight["ok"]:
        return {
            "error": "preflight_failed",
            "detail": (
                "The updated code failed to import, so the restart was skipped and the app is still "
                "running the previous version. This usually means the dependency install didn't "
                "finish — re-run Update, or on the server: "
                "backend/.venv/bin/pip install -r backend/requirements.txt"
            ),
            "changed": True,
            "steps": steps,
            "restarting": False,
        }

    _schedule_restart()
    return {"changed": True, "steps": steps, "restarting": True}
