"""Private immutable files on the application server; never expose this directory as static content."""
import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from fastapi import HTTPException


def storage_root() -> Path:
    root = Path(os.getenv('VIDEO_STORAGE_DIR') or '.local/videos').expanduser().resolve()
    project=Path(__file__).resolve().parents[1]
    if root == Path(root.anchor) or (root.is_relative_to(project) and not root.is_relative_to(project/'.local')):
        raise HTTPException(503, 'Храните видео вне публичных каталогов проекта, например в .local/videos')
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        incoming = root / '_incoming'
        incoming.mkdir(exist_ok=True, mode=0o700)
        if incoming.is_symlink():
            raise OSError('Incoming directory must not be a symlink')
        with tempfile.TemporaryFile(dir=incoming):
            pass
    except OSError:
        raise HTTPException(503, 'Каталог видео недоступен для записи') from None
    return root


def object_path(key: str, root: Path | None = None) -> Path:
    root = root or storage_root()
    parts = PurePosixPath(key)
    if parts.is_absolute() or not parts.parts or any(p in ('.', '..') for p in parts.parts) or '\\' in key:
        raise HTTPException(409, 'Недопустимый путь видео')
    candidate = root.joinpath(*parts.parts)
    # Reject symlinks even when they point inside the private directory.
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink():
            raise HTTPException(409, 'Недопустимый путь видео')
    if not candidate.resolve().is_relative_to(root):
        raise HTTPException(409, 'Недопустимый путь видео')
    return candidate


def reserve_bytes() -> int:
    try:
        amount = int(os.getenv('VIDEO_MIN_FREE_BYTES') or 536870912)
        if amount < 0:
            raise ValueError
        return amount
    except ValueError:
        raise HTTPException(503, 'Некорректный резерв дискового пространства') from None


def check_space(root: Path, needed: int) -> None:
    if shutil.disk_usage(root).free < reserve_bytes() + needed:
        raise HTTPException(507, 'Недостаточно свободного места для загрузки видео')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def publish_file(staged: Path, key: str, digest: str) -> None:
    destination = object_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        # Both paths are on the same filesystem. Link publishes only the complete file,
        # atomically, and refuses to replace an already published original.
        os.link(staged, destination)
    except FileExistsError:
        if sha256_file(destination) != digest:
            raise HTTPException(409, 'Содержание уже загруженного видео менять нельзя') from None
    except OSError as exc:
        if exc.errno == 28:
            raise HTTPException(507, 'Диск заполнен') from None
        raise HTTPException(503, 'Не удалось атомарно сохранить видео на диске') from None


def cleanup_abandoned_uploads(root: Path) -> None:
    # An upload is limited to 120 seconds. Only our private staging files older
    # than one day are removed after a crash; submitted originals are retained.
    before = time.time() - 86400
    for path in (root / '_incoming').glob('*.part'):
        if not path.is_symlink() and path.is_file() and path.stat().st_mtime < before:
            path.unlink(missing_ok=True)
