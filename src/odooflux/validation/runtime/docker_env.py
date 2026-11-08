"""Docker CLI runtime adapter: the RuntimeEnvironment contract, version 1 (REQ-VAL-004, REQ-SEC-001, REQ-SEC-002).

Customer code never runs on the host. Each run gets a labelled PostgreSQL container and a labelled Odoo
container, both with ``--network none``. The module copies are mounted read-only under the addons path. The
database and Odoo share one labelled socket volume, so no TCP is used. Every resource carries
``odooflux.run=<run id>``, and ``teardown`` removes everything with that label.

The argv builders are pure functions so that the argument contract can be tested without a daemon.
Images are referenced by the digest the local daemon reports (``RepoDigests``); the adapter never pulls.
"""

import json
import re
import secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.validation.runtime import log_classifier
from odooflux.validation.runtime.log_classifier import ClassifiedError

CONTRACT_VERSION = 1
LABEL_KEY = "odooflux.run"
IMAGES_FILE = KNOWLEDGE_ROOT / "compatibility" / "runtime_images.json"
SOCKET_DIR = "/var/run/postgresql"
DATA_DIR = "/var/lib/odoo"
ADDONS_DIR = "/mnt/extra-addons"
DB_NAME = "odoo"
DB_USER = "odoo"
READY_MARKER = "init process complete"
READINESS_TIMEOUT_S = 90
DEFAULT_EXCERPT_LINES = 40
MODULE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
TAGS = re.compile(r"^[A-Za-z0-9_/.:,+\-]+$")
DIGEST_PREFIX = "@sha256:"


@dataclass(frozen=True)
class Limits:
    cpu: float = 2.0            # cores (--cpus)
    memory_mb: int = 2048       # --memory and --memory-swap (no swap)
    wall_time_s: int = 900      # subprocess timeout; on expiry the container is killed (killed_reason=timeout)
    network: str = "none"       # only 'none' is implemented
    pids: int = 512             # --pids-limit

    def __post_init__(self):
        if self.network != "none":
            raise ValueError("only network 'none' is implemented; 'allowlist' is not available")
        if self.cpu <= 0 or self.memory_mb <= 0 or self.wall_time_s <= 0 or self.pids <= 0:
            raise ValueError("limits must be positive")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class EnvironmentUnavailable(Exception):
    """The runtime cannot be used. ``code`` is the reason class (docker_unavailable, image_unavailable, ...)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail

    @property
    def reason(self) -> str:
        return f"{self.code}: {self.detail}" if self.detail else self.code


@dataclass
class EnvHandle:
    run_id: str
    version: str
    image: str                 # digest reference of the Odoo image
    postgres_image: str        # digest reference of the PostgreSQL image
    socket_volume: str
    data_volume: str
    modules: tuple             # ((host module directory, module name), ...)
    limits: Limits
    state_dir: str
    steps: list = field(default_factory=list)
    postgres_container: str = ""


@dataclass
class RuntimeRun:
    run_id: str
    step: str
    version: str
    image: str
    postgres_image: str
    container: str
    exit_code: int
    duration_ms: int
    log_path: str
    log_excerpt: str
    errors: list
    killed_reason: Optional[str]
    limits: Limits


# ---------------------------------------------------------------------------------------------------------------
# Pure helpers and argv builders (no Docker access)
# ---------------------------------------------------------------------------------------------------------------

def label(run_id: str) -> str:
    return f"{LABEL_KEY}={run_id}"


def socket_volume_name(run_id: str) -> str:
    return f"odooflux-{run_id}-socket"


def data_volume_name(run_id: str) -> str:
    return f"odooflux-{run_id}-data"


def _limit_flags(limits: Limits) -> list:
    return ["--network", limits.network, "--cpus", str(limits.cpu), "--memory", f"{limits.memory_mb}m",
            "--memory-swap", f"{limits.memory_mb}m", "--pids-limit", str(limits.pids)]


def build_volume_create_argv(run_id: str, volume: str) -> list:
    return ["docker", "volume", "create", "--label", label(run_id), volume]


def build_postgres_argv(run_id: str, container: str, image: str, socket_volume: str, limits: Limits) -> list:
    # Trust authentication applies only to the run's own socket: the container has no network.
    return ["docker", "run", "-d", "--name", container, "--label", label(run_id), *_limit_flags(limits),
            "--security-opt", "no-new-privileges",
            "-v", f"{socket_volume}:{SOCKET_DIR}",
            "-e", f"POSTGRES_USER={DB_USER}", "-e", f"POSTGRES_DB={DB_NAME}",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
            image]


def build_odoo_argv(run_id: str, container: str, image: str, socket_volume: str, data_volume: str,
                    modules: Sequence, odoo_args: Sequence, limits: Limits, db_host: str = SOCKET_DIR) -> list:
    argv = ["docker", "run", "--name", container, "--label", label(run_id), *_limit_flags(limits),
            "--read-only", "--tmpfs", "/tmp:rw,size=256m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{socket_volume}:{SOCKET_DIR}",
            "-v", f"{data_volume}:{DATA_DIR}",
            "-e", f"HOST={db_host}", "-e", f"USER={DB_USER}"]
    for host_dir, name in modules:
        argv += ["-v", f"{host_dir}:{ADDONS_DIR}/{name}:ro"]
    return argv + [image, *odoo_args]


def build_list_argv(run_id: str, kind: str) -> list:
    if kind == "container":
        return ["docker", "ps", "-aq", "--filter", f"label={label(run_id)}"]
    if kind == "volume":
        return ["docker", "volume", "ls", "-q", "--filter", f"label={label(run_id)}"]
    raise ValueError(f"unknown resource kind {kind!r}")


def build_remove_containers_argv(names: Sequence) -> list:
    return ["docker", "rm", "-f", "-v", *names]


def build_remove_volumes_argv(names: Sequence) -> list:
    return ["docker", "volume", "rm", *names]


def build_kill_argv(container: str) -> list:
    return ["docker", "kill", container]


def build_inspect_argv(container: str) -> list:
    return ["docker", "inspect", "--format", "{{json .State}}", container]


def build_logs_argv(container: str) -> list:
    return ["docker", "logs", container]


def build_pg_isready_argv(container: str) -> list:
    return ["docker", "exec", container, "pg_isready", "-h", SOCKET_DIR, "-U", DB_USER, "-d", DB_NAME]


def build_image_inspect_argv(reference: str) -> list:
    return ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", reference]


def load_runtime_images(path: Path = IMAGES_FILE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def image_for_version(version: str, images: Optional[dict] = None) -> Optional[str]:
    """Tag reference (repository:tag) for a version, or None when the version has no runtime image."""
    data = load_runtime_images() if images is None else images
    entry = data.get("images", {}).get(version)
    if not entry:
        return None
    return f"{entry['repository']}:{entry['tag']}"


def postgres_reference(images: Optional[dict] = None) -> str:
    data = load_runtime_images() if images is None else images
    return data["postgres"]["reference"]


def module_mounts(module_dirs: Sequence) -> tuple:
    mounts = []
    for raw in module_dirs:
        path = Path(raw)
        if not path.is_absolute():
            raise ValueError(f"module directory must be absolute: {raw}")
        text = str(path)
        if ":" in text or "," in text:
            raise ValueError(f"module directory path cannot be mounted safely: {raw}")
        if not MODULE_NAME.match(path.name):
            raise ValueError(f"module directory name is not a valid Odoo module name: {path.name!r}")
        mounts.append((text, path.name))
    return tuple(mounts)


def _check_names(module_names: Sequence) -> list:
    for name in module_names:
        if not MODULE_NAME.match(name):
            raise ValueError(f"invalid module name {name!r}")
    return list(module_names)


def _default_runner(argv: Sequence, timeout: Optional[float] = None) -> CommandResult:
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True, errors="replace",
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(returncode=-1, stdout=_as_text(exc.stdout), stderr=_as_text(exc.stderr),
                             timed_out=True)
    except OSError as exc:
        return CommandResult(returncode=127, stdout="", stderr=str(exc))
    return CommandResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _as_text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


class DockerEnvironment:
    """RuntimeEnvironment backend driven by the Docker CLI. ``runner`` is injectable for tests."""

    name = "docker"
    contract_version = CONTRACT_VERSION

    def __init__(self, runner=None, readiness_timeout_s: float = READINESS_TIMEOUT_S,
                 excerpt_lines: int = DEFAULT_EXCERPT_LINES, sleep=time.sleep, clock=time.monotonic):
        self._runner = runner or _default_runner
        self.audit = None  # AuditLog: launch and teardown are recorded when set (REQ-SEC-005)
        self._readiness_timeout_s = readiness_timeout_s
        self._excerpt_lines = excerpt_lines
        self._sleep = sleep
        self._clock = clock

    # --- contract: available ------------------------------------------------------------------------
    def available(self) -> tuple:
        if shutil.which("docker") is None:
            return False, "docker_unavailable: docker CLI not found on PATH"
        result = self._runner(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
        if result.timed_out:
            return False, "docker_unavailable: docker version timed out"
        if result.returncode != 0:
            first = (result.stderr or "daemon not reachable").strip().splitlines()[0]
            return False, f"docker_unavailable: {first}"
        return True, f"docker server {result.stdout.strip()}"

    # --- contract: prepare --------------------------------------------------------------------------
    def prepare(self, version: str, modules_ro_path: Sequence, limits: Limits, *, state_dir) -> EnvHandle:
        reference = image_for_version(version)
        if reference is None:
            raise EnvironmentUnavailable("image_unavailable", f"no runtime image is mapped for {version}")
        mounts = module_mounts(modules_ro_path)
        image = self._pinned(reference)
        pg_image = self._pinned(postgres_reference())
        run_id = "r" + secrets.token_hex(6)
        handle = EnvHandle(run_id=run_id, version=version, image=image, postgres_image=pg_image,
                           socket_volume=socket_volume_name(run_id), data_volume=data_volume_name(run_id),
                           modules=mounts, limits=limits, state_dir=str(state_dir),
                           postgres_container=f"odooflux-{run_id}-pg")
        try:
            for volume in (handle.socket_volume, handle.data_volume):
                self._check(self._runner(build_volume_create_argv(run_id, volume), timeout=60),
                            f"create volume {volume}")
            self._check(self._runner(build_postgres_argv(run_id, handle.postgres_container, pg_image,
                                                         handle.socket_volume, limits), timeout=120),
                        "start the database container")
            self._wait_for_database(handle.postgres_container)
        except BaseException:
            self.teardown(handle)
            raise
        if self.audit is not None:
            self.audit.append("runtime_launched", run_id, details={
                "version": version, "image": image, "postgres_image": pg_image, "network": "none"})
        return handle

    def _pinned(self, reference: str) -> str:
        result = self._runner(build_image_inspect_argv(reference), timeout=30)
        if result.returncode != 0:
            raise EnvironmentUnavailable("image_unavailable",
                                         f"{reference} is not on the local daemon; pull it explicitly first")
        try:
            digests = json.loads(result.stdout.strip() or "[]")
        except json.JSONDecodeError:
            digests = []
        repository = reference.split(":")[0]
        for digest in digests:
            if isinstance(digest, str) and digest.startswith(repository + DIGEST_PREFIX):
                return digest
        raise EnvironmentUnavailable("image_unavailable", f"{reference} has no repository digest")

    def _wait_for_database(self, container: str) -> None:
        deadline = self._clock() + self._readiness_timeout_s
        while True:
            ready = self._runner(build_pg_isready_argv(container), timeout=15).returncode == 0
            if ready:
                logs = self._runner(build_logs_argv(container), timeout=30)
                if READY_MARKER in (logs.stdout + logs.stderr):
                    return
            if self._clock() > deadline:
                raise EnvironmentUnavailable("database_not_ready",
                                             f"{container} did not accept connections in time")
            self._sleep(0.5)

    @staticmethod
    def _check(result: CommandResult, action: str) -> None:
        if result.timed_out or result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()
            raise EnvironmentUnavailable("database_not_ready" if "database" in action else "docker_unavailable",
                                         f"could not {action}: {detail[0] if detail else 'failed'}")

    # --- contract: install, upgrade, run_tests --------------------------------------------------------
    def install(self, handle: EnvHandle, module_names: Sequence) -> RuntimeRun:
        mods = ",".join(_check_names(module_names))
        args = ["odoo", "-d", DB_NAME, "-i", mods, "--without-demo=all", "--no-http", "--stop-after-init"]
        return self._step(handle, "install", args)

    def upgrade(self, handle: EnvHandle, module_names: Sequence) -> RuntimeRun:
        mods = ",".join(_check_names(module_names))
        args = ["odoo", "-d", DB_NAME, "-u", mods, "--without-demo=all", "--no-http", "--stop-after-init"]
        return self._step(handle, "upgrade", args)

    def run_tests(self, handle: EnvHandle, module_names: Sequence, tags: str) -> RuntimeRun:
        mods = ",".join(_check_names(module_names))
        if not TAGS.match(tags or ""):
            raise ValueError(f"invalid test tags {tags!r}")
        args = ["odoo", "-d", DB_NAME, "-u", mods, "--test-enable", "--test-tags", tags,
                "--without-demo=all", "--no-http", "--stop-after-init"]
        return self._step(handle, "tests", args)

    def _step(self, handle: EnvHandle, step: str, odoo_args: list) -> RuntimeRun:
        suffix = f"-{len(handle.steps) + 1}" if step in handle.steps else ""
        container = f"odooflux-{handle.run_id}-{step}{suffix}"
        argv = build_odoo_argv(handle.run_id, container, handle.image, handle.socket_volume, handle.data_volume,
                               handle.modules, odoo_args, handle.limits)
        started = self._clock()
        result = self._runner(argv, timeout=handle.limits.wall_time_s)
        killed = None
        if result.timed_out:
            killed = "timeout"
            self._runner(build_kill_argv(container), timeout=30)
        state = self._container_state(container)
        if killed is None and state.get("OOMKilled") is True:
            killed = "oom"
        exit_code = state.get("ExitCode") if isinstance(state.get("ExitCode"), int) else result.returncode
        logs = self._runner(build_logs_argv(container), timeout=60)
        text = logs.stdout + logs.stderr if (logs.stdout or logs.stderr) else result.stderr
        log_path = self._write_log(handle, step, text)
        handle.steps.append(step)
        errors = log_classifier.classify_text(text, handle.version, killed_reason=killed)
        if exit_code != 0 and not errors:
            first_stderr = (result.stderr or "").strip().splitlines()
            message = f"odoo exited with code {exit_code}" + (f": {first_stderr[0]}" if first_stderr else "")
            errors.append(ClassifiedError(error_class="unknown", pattern_id=None, level="ERROR", message=message))
        return RuntimeRun(
            run_id=handle.run_id, step=step, version=handle.version, image=handle.image,
            postgres_image=handle.postgres_image, container=container, exit_code=exit_code,
            duration_ms=int((self._clock() - started) * 1000), log_path=log_path,
            log_excerpt=log_classifier.excerpt_for(text, self._excerpt_lines), errors=errors,
            killed_reason=killed, limits=handle.limits)

    def _container_state(self, container: str) -> dict:
        result = self._runner(build_inspect_argv(container), timeout=30)
        if result.returncode != 0:
            return {}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _write_log(handle: EnvHandle, step: str, text: str) -> str:
        directory = Path(handle.state_dir) / "runs" / handle.run_id / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{step}.log"
        path.write_text(text, encoding="utf-8")
        return str(path)

    # --- contract: teardown -------------------------------------------------------------------------
    def teardown(self, handle: EnvHandle) -> list:
        """Remove every container and volume that carries the run label. Idempotent. Returns warnings."""
        warnings = []
        containers = self._labelled(handle.run_id, "container", warnings)
        if containers:
            result = self._runner(build_remove_containers_argv(containers), timeout=120)
            if result.returncode != 0:
                warnings.append(f"could not remove containers {containers}: {result.stderr.strip()[:200]}")
        volumes = self._labelled(handle.run_id, "volume", warnings)
        if volumes:
            result = self._runner(build_remove_volumes_argv(volumes), timeout=120)
            if result.returncode != 0:
                warnings.append(f"could not remove volumes {volumes}: {result.stderr.strip()[:200]}")
        remaining_containers = self._labelled(handle.run_id, "container", warnings)
        remaining_volumes = self._labelled(handle.run_id, "volume", warnings)
        if remaining_containers or remaining_volumes:
            warnings.append(
                f"run {handle.run_id} left resources behind; clean up with: "
                f"docker rm -f -v {' '.join(remaining_containers)} ; "
                f"docker volume rm {' '.join(remaining_volumes)}")
        if self.audit is not None:
            self.audit.append("runtime_teardown", handle.run_id, "failed" if warnings else "ok",
                              {"warnings": len(warnings)})
        return warnings

    def _labelled(self, run_id: str, kind: str, warnings: list) -> list:
        result = self._runner(build_list_argv(run_id, kind), timeout=60)
        if result.returncode != 0:
            warnings.append(f"could not list {kind} resources for run {run_id}")
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
