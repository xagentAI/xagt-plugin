from __future__ import annotations

import base64
import binascii
import errno
import fcntl
import ipaddress
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


class SecretStore(Protocol):
    def get(self, name: str) -> bytes | None: ...

    def set(self, name: str, value: bytes) -> None: ...

    def set_if_absent(self, name: str, value: bytes) -> bool: ...

    def delete(self, name: str) -> None: ...


@dataclass
class MemorySecretStore:
    values: dict[str, bytes]

    def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    def set(self, name: str, value: bytes) -> None:
        self.values[name] = bytes(value)

    def set_if_absent(self, name: str, value: bytes) -> bool:
        if name in self.values:
            return False
        self.values[name] = bytes(value)
        return True

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class KeyringSecretStore:
    def __init__(self, service_name: str = "clink-node") -> None:
        self.service_name = service_name

    def get(self, name: str) -> bytes | None:
        keyring = _keyring()
        encoded = keyring.get_password(self.service_name, name)
        return base64.urlsafe_b64decode(encoded) if encoded else None

    def set(self, name: str, value: bytes) -> None:
        keyring = _keyring()
        encoded = base64.urlsafe_b64encode(value).decode("ascii")
        keyring.set_password(self.service_name, name, encoded)

    def set_if_absent(self, name: str, value: bytes) -> bool:
        if self.get(name) is not None:
            return False
        self.set(name, value)
        return True

    def delete(self, name: str) -> None:
        keyring = _keyring()
        try:
            keyring.delete_password(self.service_name, name)
        except keyring.errors.PasswordDeleteError:
            pass


class SecretStoreCorrupt(ValueError):
    """The restricted secret document is malformed or non-canonical."""


class RestrictedFileSecretStore:
    """Owner-only JSON store with no-follow reads and atomic replacement."""

    MAX_DOCUMENT_BYTES = 256 * 1024

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _load(self) -> dict[str, str]:
        with self._lock():
            return self._load_unlocked()

    def _load_unlocked(self) -> dict[str, str]:
        _validate_secret_parent(self.path.parent)
        try:
            metadata = os.lstat(self.path)
        except FileNotFoundError:
            return {}
        _validate_secret_file(self.path, metadata)
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PermissionError(
                    f"secret file must not be a symlink: {self.path}"
                ) from None
            raise
        try:
            opened = os.fstat(descriptor)
            _validate_secret_file(self.path, opened)
            if (opened.st_dev, opened.st_ino) != (
                metadata.st_dev,
                metadata.st_ino,
            ):
                raise PermissionError(f"secret file changed: {self.path}")
            raw = _read_descriptor(descriptor, self.MAX_DOCUMENT_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > self.MAX_DOCUMENT_BYTES:
            raise SecretStoreCorrupt("secret document exceeds the allowed size")
        try:
            values = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretStoreCorrupt("secret document is invalid JSON") from exc
        if not isinstance(values, dict) or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in values.items()
        ):
            raise SecretStoreCorrupt("secret document must map names to strings")
        for encoded in values.values():
            _decode_secret_value(encoded)
        return values

    def _save(self, values: dict[str, str]) -> None:
        with self._lock():
            self._save_unlocked(values)

    def _save_unlocked(self, values: dict[str, str]) -> None:
        _validate_secret_parent(self.path.parent)
        encoded = json.dumps(
            values,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = self.path.with_name(
            f".{self.path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
        )
        descriptor = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(temporary, flags, 0o600)
            _write_descriptor(descriptor, encoded)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, self.path)
            directory_descriptor = os.open(
                self.path.parent,
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            _validate_secret_file(self.path, os.lstat(self.path))
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def get(self, name: str) -> bytes | None:
        encoded = self._load().get(name)
        return _decode_secret_value(encoded) if encoded else None

    def set(self, name: str, value: bytes) -> None:
        if not isinstance(value, bytes):
            raise TypeError("secret values must be bytes")
        with self._lock():
            values = self._load_unlocked()
            values[name] = base64.urlsafe_b64encode(value).decode("ascii")
            self._save_unlocked(values)

    def set_if_absent(self, name: str, value: bytes) -> bool:
        if not isinstance(value, bytes):
            raise TypeError("secret values must be bytes")
        with self._lock():
            values = self._load_unlocked()
            if name in values:
                return False
            values[name] = base64.urlsafe_b64encode(value).decode("ascii")
            self._save_unlocked(values)
            return True

    def delete(self, name: str) -> None:
        with self._lock():
            values = self._load_unlocked()
            if name in values:
                del values[name]
                self._save_unlocked(values)

    def _lock(self):
        return _SecretFileLock(self.lock_path, self.path.parent)


class _SecretFileLock:
    def __init__(self, path: Path, parent: Path) -> None:
        self.path = path
        self.parent = parent
        self.descriptor: int | None = None

    def __enter__(self) -> "_SecretFileLock":
        _validate_secret_parent(self.parent)
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR}:
                raise PermissionError(
                    f"secret lock must be a regular file: {self.path}"
                ) from None
            raise
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise PermissionError(
                    f"secret lock must be owner-only: {self.path}"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self.descriptor = descriptor
            return self
        except Exception:
            os.close(descriptor)
            raise

    def __exit__(self, *_args: object) -> None:
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None


def _validate_secret_parent(parent: Path) -> None:
    try:
        metadata = os.lstat(parent)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"secret directory does not exist: {parent}"
        ) from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(
            f"secret directory must be a real directory: {parent}"
        )
    if metadata.st_uid != os.getuid():
        raise PermissionError(
            f"secret directory owner must be uid {os.getuid()}: {parent}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise PermissionError(
            f"secret directory permissions must be 0700: {parent}"
        )


def _validate_secret_file(path: Path, metadata: os.stat_result) -> None:
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PermissionError(f"secret file must be a regular file: {path}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(
            f"secret file owner must be uid {os.getuid()}: {path}"
        )
    if metadata.st_nlink != 1:
        raise PermissionError(
            f"secret file must have exactly one link: {path}"
        )
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise PermissionError(f"secret file permissions must be 0600: {path}")


def _reject_duplicate_json_keys(
    pairs: list[tuple[object, object]],
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            raise SecretStoreCorrupt("secret document has duplicate keys")
        result[key] = value
    return result


def _decode_secret_value(encoded: str | None) -> bytes | None:
    if encoded is None:
        return None
    if not isinstance(encoded, str) or not encoded:
        raise SecretStoreCorrupt("secret value must be non-empty base64")
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SecretStoreCorrupt("secret value is not canonical base64") from exc
    if base64.urlsafe_b64encode(decoded).decode("ascii") != encoded:
        raise SecretStoreCorrupt("secret value is not canonical base64")
    return decoded


def _read_descriptor(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total <= limit:
        chunk = os.read(descriptor, min(65_536, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _write_descriptor(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(descriptor, payload[offset:])


class VaultSecretStore:
    """HashiCorp Vault KV v2 adapter for Server Profile secrets."""

    def __init__(
        self,
        address: str,
        *,
        token: str,
        mount: str = "secret",
        path_prefix: str = "clink",
        timeout_seconds: float = 5,
    ) -> None:
        if not _vault_address_is_safe(address):
            raise ValueError(
                "Vault address must use HTTPS except explicit loopback "
                "development"
            )
        if not token:
            raise ValueError("Vault token is required")
        self.address = address.rstrip("/")
        self.token = token
        self.mount = mount.strip("/")
        self.path_prefix = path_prefix.strip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, name: str) -> bytes | None:
        try:
            response = self._request("GET", "data", name)
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(
                f"Vault secret read failed with HTTP {exc.code}"
            ) from exc
        encoded = (
            response.get("data", {})
            .get("data", {})
            .get("value")
        )
        return base64.urlsafe_b64decode(encoded) if encoded else None

    def set(self, name: str, value: bytes) -> None:
        encoded = base64.urlsafe_b64encode(value).decode("ascii")
        try:
            self._request(
                "POST",
                "data",
                name,
                payload={"data": {"value": encoded}},
            )
        except HTTPError as exc:
            raise RuntimeError(
                f"Vault secret write failed with HTTP {exc.code}"
            ) from exc

    def set_if_absent(self, name: str, value: bytes) -> bool:
        if self.get(name) is not None:
            return False
        self.set(name, value)
        return True

    def delete(self, name: str) -> None:
        try:
            self._request("DELETE", "metadata", name)
        except HTTPError as exc:
            if exc.code != 404:
                raise RuntimeError(
                    f"Vault secret delete failed with HTTP {exc.code}"
                ) from exc

    def _request(
        self,
        method: str,
        operation: str,
        name: str,
        *,
        payload: dict | None = None,
    ) -> dict:
        path = "/".join(
            part
            for part in (self.path_prefix, name.strip("/"))
            if part
        )
        url = (
            f"{self.address}/v1/{quote(self.mount, safe='')}/"
            f"{operation}/{quote(path, safe='/')}"
        )
        body = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "X-Vault-Token": self.token,
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}


class EnvelopeCipher:
    VERSION = 1
    KEY_NAME = "node-envelope-key-v1"

    def __init__(self, store: SecretStore) -> None:
        self.store = store

    def _key(self) -> bytes:
        key = self.store.get(self.KEY_NAME)
        if key is None:
            candidate = secrets.token_bytes(32)
            set_if_absent = getattr(self.store, "set_if_absent", None)
            if callable(set_if_absent):
                set_if_absent(self.KEY_NAME, candidate)
            else:
                self.store.set(self.KEY_NAME, candidate)
            key = self.store.get(self.KEY_NAME)
            if key is None:
                raise RuntimeError("Clink envelope key was not persisted")
        if len(key) != 32:
            raise ValueError("Clink envelope key must be 32 bytes")
        return key

    def encrypt(self, plaintext: bytes, *, purpose: str) -> str:
        AESGCM = _aesgcm()
        nonce = secrets.token_bytes(12)
        associated_data = f"clink:{self.VERSION}:{purpose}".encode("utf-8")
        ciphertext = AESGCM(self._key()).encrypt(
            nonce,
            plaintext,
            associated_data,
        )
        envelope = bytes([self.VERSION]) + nonce + ciphertext
        return base64.urlsafe_b64encode(envelope).decode("ascii")

    def decrypt(self, encoded: str, *, purpose: str) -> bytes:
        AESGCM = _aesgcm()
        envelope = base64.urlsafe_b64decode(encoded)
        if not envelope or envelope[0] != self.VERSION:
            raise ValueError("unsupported Clink encrypted envelope")
        nonce = envelope[1:13]
        ciphertext = envelope[13:]
        associated_data = f"clink:{self.VERSION}:{purpose}".encode("utf-8")
        return AESGCM(self._key()).decrypt(
            nonce,
            ciphertext,
            associated_data,
        )


def _vault_address_is_safe(value: str) -> bool:
    if not value or value != value.strip() or "?" in value or "#" in value:
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except (UnicodeError, ValueError):
        return False
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    if parsed.hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def _keyring():
    try:
        import keyring
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "OS keychain support requires the keyring package"
        ) from exc
    return keyring


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "encrypted local state requires the cryptography package"
        ) from exc
    return AESGCM
