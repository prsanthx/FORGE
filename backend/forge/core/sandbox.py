"""Run commands inside the project. pip cannot install onto the machine.

`repo` uses the connected folder. `docker` copies that folder into a container
with no network, so the folder you connected is left untouched.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from contextvars import ContextVar
from pathlib import Path

from forge.settings import ROOT

BLOCKED_TOOLS = {"pip", "pip3", "conda", "uv", "easy_install"}
PIP_MODULES = {"pip", "ensurepip"}
SANDBOX_IMAGE = "forge-sandbox:local"
DOCKERFILE = ROOT / "sandbox" / "Dockerfile"

_runner: ContextVar["CommandRunner | None"] = ContextVar("forge_runner", default=None)


class SandboxError(RuntimeError):
    pass


class CommandRunner:
    def run(self, argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        raise NotImplementedError


def reject_install(argv: list[str]) -> None:
    if not argv:
        raise SandboxError("empty command")
    binary = Path(argv[0]).name
    if binary in BLOCKED_TOOLS:
        raise SandboxError(_pip_message(binary))
    if binary in {"python", "python3"} or argv[0] == sys.executable:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in PIP_MODULES:
            raise SandboxError(_pip_message(argv[2]))


def _pip_message(tool: str) -> str:
    return (
        f"{tool} is blocked. Commands stay inside this project. "
        "Checks run with PYTHONPATH set to the repo and do not install packages."
    )


def project_env(root: Path) -> dict[str, str]:
    """A small environment. API keys and the parent pytest config are not copied in."""
    env: dict[str, str] = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "USER", "TMPDIR", "SYSTEMROOT", "COMSPEC"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env["PYTHONPATH"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    venv_bin = root / ".venv" / "bin"
    venv_scripts = root / ".venv" / "Scripts"
    if (venv_bin / "python").exists():
        env["VIRTUAL_ENV"] = str(root / ".venv")
        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    elif (venv_scripts / "python.exe").exists():
        env["VIRTUAL_ENV"] = str(root / ".venv")
        env["PATH"] = str(venv_scripts) + os.pathsep + env.get("PATH", "")
    return env


def pytest_args(workspace: Path, extra: list[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=line",
        "--noconftest",
        f"--rootdir={workspace}",
        f"--confcutdir={workspace}",
        *extra,
    ]


class LocalRunner(CommandRunner):
    def run(self, argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        reject_install(argv)
        return subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=project_env(cwd),
        )


def docker_argv(argv: list[str]) -> list[str]:
    """Map the host interpreter onto the interpreter inside the sandbox image."""
    binary = Path(argv[0]).name
    rest = argv[1:]
    if binary in {"python", "python3"} or argv[0] == sys.executable:
        return ["python", *rest]
    if binary == "pytest":
        return ["python", "-m", "pytest", *rest]
    return [binary, *rest]


def docker_command(workspace: Path, argv: list[str], image: str = SANDBOX_IMAGE) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{workspace.resolve()}:/work",
        "-w",
        "/work",
        "-e",
        "PYTHONPATH=/work",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        image,
        *docker_argv(argv),
    ]


class DockerRunner(CommandRunner):
    def __init__(self, image: str = SANDBOX_IMAGE):
        self.image = image

    def run(self, argv: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        reject_install(argv)
        return subprocess.run(
            docker_command(cwd, argv, self.image),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )


def current_runner() -> CommandRunner:
    return _runner.get() or LocalRunner()


def use_runner(runner: CommandRunner):
    return _runner.set(runner)


def reset_runner(token) -> None:
    _runner.reset(token)


def docker_ready() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "Docker is not installed, so a sandbox run cannot start."
    proc = subprocess.run(["docker", "info"], text=True, capture_output=True, check=False, timeout=20)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "docker info failed").strip().splitlines()
        return False, "Docker is not running. " + (detail[-1] if detail else "")
    return True, "ok"


def ensure_sandbox_image(image: str = SANDBOX_IMAGE) -> None:
    inspect = subprocess.run(["docker", "image", "inspect", image], text=True, capture_output=True, check=False)
    if inspect.returncode == 0:
        return
    if not DOCKERFILE.is_file():
        raise SandboxError(f"missing sandbox image definition: {DOCKERFILE}")
    build = subprocess.run(
        ["docker", "build", "-t", image, "-f", str(DOCKERFILE), str(DOCKERFILE.parent)],
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    if build.returncode != 0:
        tail = (build.stderr or build.stdout or "docker build failed").strip().splitlines()
        raise SandboxError("Could not build the sandbox image. " + (tail[-1] if tail else ""))


def split_command(command: str) -> list[str]:
    try:
        return shlex.split(command or "")
    except ValueError as exc:
        raise SandboxError(f"could not parse command: {exc}") from exc
