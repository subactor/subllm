from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path

from .errors import CredentialFileError, MissingCredentialError
from .policy import CURSOR_API_KEY_ENV, EXTRA_CREDENTIAL_ENV, PROVIDERS, SUBLLM_PROVIDER_ORDER

SUBLLM_ENV_FILE = "SUBLLM_ENV_FILE"
POLICY_ENV_NAMES = (SUBLLM_PROVIDER_ORDER,)
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER_PARTS = (
    "ADD_SIGNATURE_SECRET",
    "SIGNATURE_SECRET",
    "CHANGEME",
    "PLACEHOLDER",
    "<",
    ">",
)


def credential_names() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *(provider.api_key_env for provider in PROVIDERS.values()),
                *EXTRA_CREDENTIAL_ENV,
            )
        )
    )


def allowed_env_names() -> tuple[str, ...]:
    return tuple(dict.fromkeys((*credential_names(), *POLICY_ENV_NAMES)))


def credential_is_valid(provider: str, value: str | None) -> bool:
    candidate = (value or "").strip()
    if not candidate or any(part in candidate.upper() for part in _PLACEHOLDER_PARTS):
        return False
    if provider == "zai":
        if candidate.count(".") != 1:
            return False
        key_id, signature_secret = candidate.split(".", 1)
        return bool(key_id and signature_secret)
    return True


def credential_value(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> str | None:
    if name not in credential_names():
        raise CredentialFileError(f"unsupported variable {name}")
    value = merged_environment(environ=environ, cwd=cwd).get(name, "").strip()
    return value or None


def cursor_api_key(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> str:
    value = credential_value(CURSOR_API_KEY_ENV, environ=environ, cwd=cwd)
    if value is None:
        raise MissingCredentialError(f"no valid credential; configure {CURSOR_API_KEY_ENV}")
    return value


def find_env_file(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    environment = os.environ if environ is None else environ
    working_directory = (cwd or Path.cwd()).resolve()
    configured = environment.get(SUBLLM_ENV_FILE, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = working_directory / path
        return path.absolute()

    for root in (working_directory, *working_directory.parents):
        candidates = [root / "subllm" / ".env"]
        if root.name == "subllm":
            candidates.insert(0, root / ".env")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def _validate_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise CredentialFileError(f"SubLLM credential file does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CredentialFileError(f"SubLLM credential file must not be a symbolic link: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise CredentialFileError(f"SubLLM credential path is not a regular file: {path}")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise CredentialFileError(f"SubLLM credential file must have mode 0600: {path}")


def _unquote(value: str, *, path: Path, line_number: int) -> str:
    if not value or value[0] not in {'"', "'"}:
        return value
    if len(value) < 2 or value[-1] != value[0]:
        raise CredentialFileError(f"unterminated quoted value in {path} at line {line_number}")
    return value[1:-1]


def load_env_file(path: Path, *, allow_other_names: bool = False) -> dict[str, str]:
    path = path.absolute()
    _validate_file(path)
    allowed = set(allowed_env_names())
    credentials: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CredentialFileError(f"cannot read SubLLM credential file: {path}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not _ENV_NAME.fullmatch(name):
            raise CredentialFileError(f"invalid assignment in {path} at line {line_number}")
        if name not in allowed:
            if allow_other_names:
                continue
            raise CredentialFileError(f"unsupported variable {name} in SubLLM credential file: {path}")
        if name in credentials:
            raise CredentialFileError(f"duplicate variable {name} in SubLLM credential file: {path}")
        credentials[name] = _unquote(raw_value.strip(), path=path, line_number=line_number)
    return credentials


def load_shared_environment(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, str]:
    path = find_env_file(environ=environ, cwd=cwd)
    if path is None:
        return {}
    return load_env_file(path)


def merged_environment(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Mapping[str, str]:
    if environ is not None:
        return environ
    merged = load_shared_environment(cwd=cwd)
    merged.update(os.environ)
    return merged


def import_credentials(source_paths: Iterable[Path], target: Path) -> tuple[str, ...]:
    target = target.absolute()
    imported: dict[str, str] = {}
    if target.exists():
        imported.update(load_env_file(target))
    for source in source_paths:
        for name, value in load_env_file(source, allow_other_names=True).items():
            if not value:
                continue
            current = imported.get(name)
            if current is not None and current != value:
                raise CredentialFileError(f"conflicting values for {name}; source credentials were not changed")
            imported[name] = value
    if not any(name in imported for name in credential_names()):
        raise CredentialFileError("no provider credentials found in the source files")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=".subllm-env-",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write("# Local provider credentials. Never commit this file.\n")
            for name in allowed_env_names():
                if name in imported:
                    temporary.write(f"{name}={imported[name]}\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
        os.chmod(target, 0o600)
    except OSError as exc:
        raise CredentialFileError(f"cannot write SubLLM credential file: {target}") from exc
    finally:
        if temporary_name is not None:
            with suppress(FileNotFoundError):
                Path(temporary_name).unlink()
    return tuple(name for name in allowed_env_names() if name in imported)
