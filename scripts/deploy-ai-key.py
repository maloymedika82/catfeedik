"""Copy the existing local AI key to the VPS through SSH stdin without displaying it."""
import argparse
import json
from pathlib import Path
import subprocess


REMOTE = r'''
import json, os
from pathlib import Path
data = json.loads(__PAYLOAD__)
target = Path('/srv/catfeedik/.env.production')
if not target.is_file() or (target.stat().st_mode & 0o077):
    raise SystemExit('Private production environment is missing or has unsafe permissions')
lines = target.read_text().splitlines()
for name in ('AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL', 'AI_MODERATION_ENABLED'):
    value = data[name]
    found = False
    for index, line in enumerate(lines):
        if line.startswith(name + '='):
            lines[index] = name + '=' + value
            found = True
            break
    if not found:
        lines.append(name + '=' + value)
target.write_text('\n'.join(lines) + '\n')
os.chmod(target, 0o600)
print('AI settings installed without displaying credentials.')
'''


def values_from_env(path):
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            name, value = line.split('=', 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    result = {name: values.get(name, '') for name in ('AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL')}
    if not result['AI_API_KEY'] or any('\n' in value or '\r' in value for value in result.values()):
        raise SystemExit('Local AI key is missing or invalid')
    if not result['AI_BASE_URL'].startswith('https://'):
        raise SystemExit('AI provider must use HTTPS')
    result['AI_MODERATION_ENABLED'] = '1'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--identity', required=True)
    args = parser.parse_args()
    payload = json.dumps(json.dumps(values_from_env(Path('.env')), ensure_ascii=True))
    source = REMOTE.replace('__PAYLOAD__', payload)
    result = subprocess.run(
        ['ssh', '-i', args.identity, '-o', 'BatchMode=yes', '-p', str(args.port),
         'root@' + args.host, 'python3 -'],
        input=source, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise SystemExit('AI settings could not be installed over SSH')
    print(result.stdout.strip())


if __name__ == '__main__':
    main()
