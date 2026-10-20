#!/usr/bin/env python3
"""按手写的季/集范围及 glob 模板从 AList 生成 TinyTV sources.json。"""
import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.rmvb', '.flv', '.m4v'}


def join_path(*parts):
    """拼接 AList 绝对路径，同时保持根目录为 /。"""
    values = [str(part).strip('/') for part in parts if str(part).strip('/')]
    return '/' + '/'.join(values) if values else '/'


def list_directory(client, base_url, path):
    """读取一个 AList 目录；只返回构建清单需要的公开元数据。"""
    try:
        response = client.post(
            base_url.rstrip('/') + '/api/fs/list',
            json={'path': path, 'page': 1, 'per_page': 0, 'refresh': True},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError(f'AList request failed for {path} ({type(error).__name__})') from None
    if payload.get('code') != 200 or not isinstance(payload.get('data'), dict):
        raise ValueError(f'AList could not list {path} (code {payload.get("code", "unknown")})')
    content = payload['data'].get('content') or []
    if not isinstance(content, list):
        raise ValueError(f'AList returned invalid directory data for {path}')
    return content


def authenticate(client, base_url, env):
    """配置现有 token，或用账号密码登录 AList 获取临时 token。"""
    token = os.getenv('ALIST_TOKEN') or env.get('ALIST_TOKEN')
    if token:
        client.headers['Authorization'] = token
        return
    username = os.getenv('ALIST_USERNAME') or env.get('ALIST_USERNAME')
    password = os.getenv('ALIST_PASSWORD') or env.get('ALIST_PASSWORD')
    if not username and not password:
        return
    if not username or not password:
        raise ValueError('ALIST_USERNAME and ALIST_PASSWORD must be configured together')
    try:
        response = client.post(
            base_url.rstrip('/') + '/api/auth/login',
            json={'username': username, 'password': password},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError(f'AList login failed ({type(error).__name__})') from None
    token = payload.get('data', {}).get('token') if isinstance(payload.get('data'), dict) else None
    if payload.get('code') != 200 or not token:
        raise ValueError(f'AList login failed (code {payload.get("code", "unknown")})')
    client.headers['Authorization'] = token


def collect_files(client, base_url, root):
    """递归枚举挂载目录，返回相对于 ALIST_ROOT 的 POSIX 路径。"""
    files = []
    pending = [join_path(root)]
    while pending:
        directory = pending.pop()
        for entry in list_directory(client, base_url, directory):
            name = entry.get('name')
            if not isinstance(name, str) or not name or '/' in name:
                continue
            full_path = join_path(directory, name)
            if entry.get('is_dir'):
                pending.append(full_path)
            elif PurePosixPath(name).suffix.lower() in VIDEO_EXTENSIONS:
                root_path = join_path(root)
                relative = full_path[len(root_path):].lstrip('/') if root_path != '/' else full_path.lstrip('/')
                files.append(relative)
    return files


def build_records(config, files):
    records, errors = [], []
    if not isinstance(config, list):
        raise ValueError('Sources config must be a JSON array')
    for show in config:
        title = show['title']
        for season in show['seasons']:
            number = int(season['season'])
            count = int(season['episodes'])
            template = season['pattern']
            for episode in range(1, count + 1):
                pattern = template.format(season=number, episode=episode).lstrip('/')
                matches = sorted(path for path in files if fnmatch.fnmatchcase(path, pattern))
                if len(matches) != 1:
                    message = f'{title} S{number}E{episode}: 匹配到 {len(matches)} 个文件 [{pattern}]'
                    print('警告：' + message, file=sys.stderr)
                    errors.append(message)
                    continue
                records.append({
                    'title': title,
                    'season': number,
                    'episode': episode,
                    'path': '/' + matches[0],
                })
    return records, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('backend/data/tinytv/sources_config.json'))
    parser.add_argument('--output', type=Path, default=Path('backend/data/tinytv/sources_new.json'))
    parser.add_argument('--dry-run', action='store_true', help='只匹配文件，不写 JSON')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        env = dotenv_values('backend/.env')
        base_url = os.getenv('ALIST_URL') or env.get('ALIST_URL') or 'https://alist.cloverfrog.xyz'
        root = os.getenv('ALIST_ROOT', env.get('ALIST_ROOT') or '')
        parsed = urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            parser.error('ALIST_URL 必须是 HTTP 或 HTTPS 地址')
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            authenticate(client, base_url, env)
            files = collect_files(client, base_url, root)
        records, errors = build_records(config, files)
        if not args.dry_run:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
            )
            print(f'已写入 {args.output}：{len(records)} 集；问题 {len(errors)} 个')
        else:
            print(f'预检完成：匹配 {len(records)} 集；问题 {len(errors)} 个')
        return 0 if not errors else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'无法生成片源清单：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
