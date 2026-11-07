"""Back up the production database and immutable videos without printing secrets.

Run on the VPS from the repository checkout. Backups must also be copied off-host.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    'docker', 'compose', '--env-file', '.env.production',
    '-f', 'compose.production.yaml', '-f', 'compose.funnel.yaml',
]
VOLUME = 'catfeedik-production_videos'


def run(*args, input_file=None, capture=False):
    with input_file.open('rb') if input_file else open(os.devnull, 'rb') as source:
        result = subprocess.run(args, cwd=ROOT, stdin=source,
                                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(f'Command failed: {args[0]} {args[-1]} (exit {result.returncode})')
    return result.stdout.decode().strip() if capture else None


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def dump_database(target):
    with target.open('xb') as output:
        process = subprocess.run(
            [*COMPOSE, 'exec', '-T', 'postgres', 'pg_dump', '-U', 'catfeedik',
             '-d', 'catfeedik', '--format=custom', '--no-owner', '--no-acl'],
            cwd=ROOT, stdout=output, stderr=subprocess.PIPE, check=False,
        )
    if process.returncode:
        raise RuntimeError('PostgreSQL dump failed')


def archive_videos(target, mount):
    if not mount.is_dir() or mount.is_symlink():
        raise RuntimeError('Video volume mount is invalid')
    with tarfile.open(target, 'w:gz') as archive:
        for path in sorted(mount.rglob('*')):
            relative = path.relative_to(mount)
            if relative.parts[0] == '_incoming':
                continue
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise RuntimeError('Unexpected file in video volume')
            archive.add(path, arcname=Path('videos') / relative, recursive=False)


def verify(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name in ('database.dump', 'videos.tar.gz'):
        if digest(directory / name) != manifest['sha256'][name]:
            raise RuntimeError(f'Checksum mismatch: {name}')
    with tarfile.open(directory / 'videos.tar.gz', 'r:gz') as archive:
        for item in archive:
            if not item.name.startswith('videos/') or item.issym() or item.islnk():
                raise RuntimeError('Invalid video archive member')
    run('docker', 'compose', '--env-file', '.env.production',
        '-f', 'compose.production.yaml', '-f', 'compose.funnel.yaml',
        'exec', '-T', 'postgres', 'pg_restore', '--list',
        input_file=directory / 'database.dump')


def restore_test(directory):
    name = 'catfeedik_restore_' + secrets.token_hex(6)
    def postgres(*args, input_file=None):
        return run(*COMPOSE, 'exec', '-T', 'postgres', *args, input_file=input_file)
    postgres('createdb', '-U', 'catfeedik', name)
    try:
        postgres('pg_restore', '-U', 'catfeedik', '-d', name,
                 '--no-owner', '--no-acl', input_file=directory / 'database.dump')
        postgres('psql', '-U', 'catfeedik', '-d', name, '-v', 'ON_ERROR_STOP=1',
                 '-c', 'SELECT count(*) FROM users')
    finally:
        postgres('dropdb', '-U', 'catfeedik', '--if-exists', '--force', name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('/var/backups/catfeedik'))
    parser.add_argument('--verify', type=Path, help='Verify an existing backup')
    parser.add_argument('--restore-test', action='store_true',
                        help='Restore into a disposable database and check its tables')
    args = parser.parse_args()
    if args.verify:
        directory = args.verify.resolve()
        verify(directory)
        if args.restore_test:
            restore_test(directory)
        print('Backup archives and checksums verified' +
              ('; disposable database restored.' if args.restore_test else '.'))
        return
    if not (ROOT / '.env.production').is_file():
        raise RuntimeError('Production environment file is missing')
    output_root = args.output_dir.resolve()
    if output_root == ROOT or output_root.is_relative_to(ROOT):
        raise RuntimeError('Backups must be stored outside the Git checkout')
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_root, 0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = output_root / stamp
    directory.mkdir(mode=0o700)
    try:
        database = directory / 'database.dump'
        videos = directory / 'videos.tar.gz'
        dump_database(database)
        mount = Path(run('docker', 'volume', 'inspect', VOLUME, '--format', '{{.Mountpoint}}', capture=True))
        archive_videos(videos, mount)
        manifest = {
            'created_utc': stamp,
            'git_commit': run('git', 'rev-parse', 'HEAD', capture=True),
            'sha256': {name: digest(directory / name) for name in ('database.dump', 'videos.tar.gz')},
        }
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        for path in directory.iterdir():
            os.chmod(path, 0o600)
        verify(directory)
        if args.restore_test:
            restore_test(directory)
    except Exception:
        print('Backup failed; incomplete directory retained for inspection.', file=sys.stderr)
        raise
    print(f'Backup verified: {directory}')
    print('Copy this directory to separate storage; a VPS-local backup is not disaster recovery.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from None
