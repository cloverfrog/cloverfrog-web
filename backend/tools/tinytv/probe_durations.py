# 片源时长采集工具：用 ffprobe 探测资源，将结果写入独立输出文件；中断后可继续，不覆盖输入清单。
"""Run from the project root: python tools/tinytv/probe_durations.py --help."""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values


def valid_duration(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


# 同一集换了文件路径后必须重新探测，因此断点缓存的键还包含 path。
def record_key(record):
    return record['title'], record['season'], record['episode'], record['path']


def load_sources(path):
    records = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(records, list):
        raise ValueError('Sources must be a JSON array')
    seen = set()
    for record in records:
        key = record_key(record)
        if not isinstance(key[0], str) or not isinstance(key[3], str) or not key[3]:
            raise ValueError('Source title and path must be strings')
        if key[:3] in seen:
            raise ValueError('Duplicate title/season/episode')
        seen.add(key[:3])
    return records


def prepare_records(records, previous):
    """Resume only matching files; changed paths must be probed again."""
    cached = {record_key(record): record.get('duration') for record in previous}
    result = []
    for record in records:
        item = dict(record)
        value = cached.get(record_key(record))
        if not valid_duration(item.get('duration')) and valid_duration(value):
            item['duration'] = value
        result.append(item)
    return result


def save_json(path, data):
    """Checkpoint without exposing a half-written result after interruption."""
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def direct_url(base, root, path):
    return base.rstrip('/') + '/d' + quote(root.rstrip('/') + '/' + path.lstrip('/'), safe='/')


# 限制单文件探测时间，并只接受有效的正数时长，避免错误边界进入频道时间线。
def probe_duration(url, executable='ffprobe', timeout=60):
    command = [
        executable,
        '-v', 'error',
        '-rw_timeout', '15000000',
        '-show_entries', 'format=duration',
        '-of', 'json',
        url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired:
        raise ValueError('Probe timed out') from None
    except subprocess.CalledProcessError as error:
        # ffprobe 的 stderr 可能包含私有媒体地址，错误报告只保留退出码。
        raise ValueError(f'ffprobe failed (exit {error.returncode})') from None
    try:
        value = float(json.loads(result.stdout)['format']['duration'])
        if not valid_duration(value):
            raise ValueError()
        value = round(value, 6)
        if not valid_duration(value):
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise ValueError('No valid duration in ffprobe output') from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Collect source durations, preserving the input and resuming completed work.'
    )
    parser.add_argument('--input', type=Path, default=Path('data/tinytv/sources.json'))
    parser.add_argument('--output', type=Path, default=Path('data/tinytv/sources.probed.json'))
    parser.add_argument('--base-url', help='AList origin; defaults to ALIST_URL in environment/.env')
    parser.add_argument('--root', help='AList mount prefix; defaults to ALIST_ROOT in environment/.env')
    parser.add_argument('--timeout', type=float, default=60, help='Maximum seconds per file (default: 60)')
    parser.add_argument('--limit', type=int, help='Maximum probes in this run; skipped entries do not count')
    parser.add_argument('--ffprobe', default='ffprobe', help='ffprobe executable name or path')
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error('--output must differ from --input')
    if not math.isfinite(args.timeout) or args.timeout <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error('--timeout and --limit must be positive')
    if not shutil.which(args.ffprobe):
        parser.error('ffprobe not found; install FFmpeg or pass --ffprobe')
    # 命令行参数优先，其次为进程环境和 .env；支持临时指定资源入口而不改部署配置。
    env = dotenv_values('.env')
    base = args.base_url or os.getenv('ALIST_URL') or env.get('ALIST_URL') or 'https://alist.cloverfrog.xyz'
    root = args.root if args.root is not None else os.getenv('ALIST_ROOT', env.get('ALIST_ROOT') or '')
    if urlsplit(base).scheme not in ('http', 'https') or not urlsplit(base).netloc:
        parser.error('AList URL must use HTTP or HTTPS')
    errors_path = args.output.with_name(args.output.stem + '.errors.json')
    if errors_path.resolve() == args.input.resolve():
        parser.error('Error report path must differ from input')
    try:
        records = load_sources(args.input)
        previous = load_sources(args.output) if args.output.exists() else []
        records = prepare_records(records, previous)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # 输出持续累积有效时长，错误报告只记录本次尝试；已有有效时长会在重跑时跳过。
        errors = []
        attempts = completed = skipped = 0
        save_json(args.output, records)
        save_json(errors_path, errors)
        # 每处理一条就保存检查点，重新运行时跳过已有有效时长的资源。
        for position, record in enumerate(records, 1):
            if valid_duration(record.get('duration')):
                skipped += 1
                continue
            if args.limit is not None and attempts >= args.limit:
                break
            attempts += 1
            try:
                record['duration'] = probe_duration(
                    direct_url(base, root, record['path']), args.ffprobe, args.timeout
                )
                completed += 1
                print(f'[{position}/{len(records)}] OK {record["duration"]:.6f}s', flush=True)
            except ValueError as error:
                errors.append(
                    {key: record[key] for key in ('title', 'season', 'episode')}
                    | {'error': str(error)}
                )
                print(f'[{position}/{len(records)}] FAILED: {error}', flush=True)
            save_json(args.output, records)
            save_json(errors_path, errors)
        missing = sum(not valid_duration(record.get('duration')) for record in records)
        print(f'Collected: {completed}; skipped: {skipped}; failed: {len(errors)}; remaining: {missing}')
        print(f'Result: {args.output}; errors from this run: {errors_path}')
        return 1 if errors else 0
    except KeyboardInterrupt:
        print('\nStopped. Completed checkpoints are saved; rerun the same command to resume.', file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Cannot process source data ({type(error).__name__}); check JSON structure and file access.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
