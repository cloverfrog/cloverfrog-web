#!/usr/bin/env python3
"""Generate a TinyTV schedule from independently cycling series."""

import argparse
import json
import math
import os
import random
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def valid_positive_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def source_duration(item, key):
    """Return one logical episode's duration for either supported source shape."""
    if "parts" in item:
        if "path" in item or "duration" in item:
            raise ValueError(f"多文件资源不能同时定义 path 或 duration：{key}")
        parts = item["parts"]
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"parts 不能为空：{key}")
        paths = [part.get("path") for part in parts if isinstance(part, dict)]
        if len(paths) != len(parts) or not all(isinstance(path, str) and path for path in paths) or len(set(paths)) != len(paths):
            raise ValueError(f"part path 无效或重复：{key}")
        durations = [part.get("duration") for part in parts if isinstance(part, dict)]
        if len(durations) != len(parts) or not all(valid_positive_number(value) for value in durations):
            raise ValueError(f"缺少有效 part duration：{key}")
        return sum(durations)
    if not isinstance(item.get("path"), str) or not item["path"]:
        raise ValueError(f"缺少有效 path：{key}")
    if not valid_positive_number(item.get("duration")):
        raise ValueError(f"缺少有效 duration：{key}")
    return item["duration"]


def group_sources(sources):
    if not isinstance(sources, list):
        raise ValueError("sources.json 必须是数组")
    grouped = defaultdict(list)
    seen = set()
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"]:
            raise ValueError("片源缺少有效 title")
        try:
            title = item["title"]
            season, episode = int(item["season"]), int(item["episode"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("片源缺少有效 season 或 episode") from None
        key = (title, season, episode)
        if key in seen:
            raise ValueError(f"重复资源：{key}")
        seen.add(key)
        grouped[title].append({**item, "_duration": source_duration(item, key)})
    if not grouped:
        raise ValueError("sources.json 中没有视频")
    for episodes in grouped.values():
        episodes.sort(key=lambda item: (int(item["season"]), int(item["episode"])))
    return grouped


def validate_priorities(priorities, titles):
    if priorities is None:
        return {title: 1 for title in titles}
    if not isinstance(priorities, dict):
        raise ValueError("优先级配置必须是以作品名为键的对象")
    unknown = sorted(set(priorities) - set(titles))
    if unknown:
        raise ValueError(f"优先级配置包含未知作品：{', '.join(unknown)}")
    result = {}
    for title in titles:
        value = priorities.get(title, 1)
        if not valid_positive_number(value):
            raise ValueError(f"作品优先级必须是大于 0 的有限数字：{title}")
        result[title] = value
    return result


def validate_previous_schedule(schedule):
    if not isinstance(schedule, dict):
        raise ValueError("旧节目表必须是对象")
    try:
        start = datetime.fromisoformat(schedule["startTime"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("旧节目表缺少有效 startTime") from None
    if start.utcoffset() is None:
        raise ValueError("旧节目表 startTime 必须带时区")
    programs = schedule.get("programs")
    if not isinstance(programs, list) or not programs:
        raise ValueError("旧节目表 programs 必须是非空数组")
    normalized = []
    for position, program in enumerate(programs, start=1):
        try:
            title = program["title"]
            season = int(program["season"])
            episode = int(program["episode"])
            duration = program["duration"]
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"旧节目表第 {position} 项无效") from None
        if not isinstance(title, str) or not title or not valid_positive_number(duration):
            raise ValueError(f"旧节目表第 {position} 项无效")
        normalized.append({"title": title, "season": season, "episode": episode, "duration": duration})
    return start, normalized


def continuation_starts(previous_schedule, sources, new_start):
    """Calculate per-title starting episodes without looping an expired schedule."""
    old_start, programs = validate_previous_schedule(previous_schedule)
    grouped = group_sources(sources)
    played = []
    if new_start >= old_start:
        elapsed = (new_start - old_start).total_seconds()
        cursor = 0.0
        for program in programs:
            played.append(program)  # The program in progress counts as played.
            cursor += program["duration"]
            if elapsed < cursor:
                break
    last_played = {}
    for program in played:
        last_played[program["title"]] = (program["season"], program["episode"])
    first_planned = {}
    for program in programs:
        first_planned.setdefault(program["title"], (program["season"], program["episode"]))
    starts = {}
    for title, episodes in grouped.items():
        keys = [(int(item["season"]), int(item["episode"])) for item in episodes]
        if title in last_played:
            starts[title] = next((key for key in keys if key > last_played[title]), keys[0])
        elif title in first_planned:
            starts[title] = next((key for key in keys if key >= first_planned[title]), keys[0])
    return starts


def generate(sources, *, min_run=2, max_run=3, balance_alpha=0.6, priorities=None, starts=None, seed=None):
    if min_run < 1 or max_run < min_run:
        raise ValueError("必须满足 1 <= min_run <= max_run")
    if not math.isfinite(balance_alpha) or not 0 <= balance_alpha <= 1:
        raise ValueError("balance_alpha 必须介于 0 和 1 之间")
    grouped = group_sources(sources)
    priority_by_title = validate_priorities(priorities, grouped)
    starts = starts or {}
    unknown_starts = sorted(set(starts) - set(grouped))
    if unknown_starts:
        raise ValueError(f"起始位置包含未知作品：{', '.join(unknown_starts)}")
    rng = random.Random(seed)
    queues = {}
    for title, episodes in grouped.items():
        if title in starts:
            wanted = tuple(starts[title])
            try:
                offset = next(index for index, item in enumerate(episodes) if (int(item["season"]), int(item["episode"])) == wanted)
            except StopIteration:
                raise ValueError(f"作品起始集不存在：{title} S{wanted[0]}E{wanted[1]}") from None
        else:
            offset = rng.randrange(len(episodes))
        queues[title] = episodes[offset:] + episodes[:offset]
    positions = {title: 0 for title in queues}
    previous, programs, total_seconds = None, [], 0.0
    while any(positions[title] < len(queues[title]) for title in queues):
        active = sorted(queues)
        candidates = [title for title in active if title != previous] if len(active) > 1 else active
        weights = [len(queues[title]) ** balance_alpha * priority_by_title[title] for title in candidates]
        title = rng.choices(candidates, weights=weights, k=1)[0]
        for _ in range(rng.randint(min_run, max_run)):
            if all(positions[name] >= len(queues[name]) for name in queues):
                break
            item = queues[title][positions[title] % len(queues[title])]
            programs.append({"title": title, "season": int(item["season"]), "episode": int(item["episode"]), "duration": item["_duration"]})
            total_seconds += item["_duration"]
            positions[title] += 1
        previous = title
    return programs, total_seconds


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def load_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取{label} {path}：{error}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("backend/data/tinytv/sources.json"))
    parser.add_argument("--output", type=Path, default=Path("backend/data/tinytv/schedule.json"))
    parser.add_argument("--priorities", type=Path, help="可选的作品优先级 JSON 文件")
    parser.add_argument("--mode", choices=("random", "continue"), default="random", help="random 完全随机；continue 延续旧节目表，默认 random")
    parser.add_argument("--previous-schedule", type=Path, help="延续模式读取的旧节目表；默认与 --output 相同")
    parser.add_argument("--channel", default="tiny")
    parser.add_argument("--min-run", type=int, default=2, help="每次最少连播几集，默认 2")
    parser.add_argument("--max-run", type=int, default=3, help="每次最多连播几集，默认 3")
    parser.add_argument("--balance-alpha", type=float, default=0.6, help="集数权重指数（0=各作品等权，1=按集数），默认 0.6")
    parser.add_argument("--start", help="带时区的 ISO 时间，如 2026-10-17T00:00:00+08:00")
    parser.add_argument("--seed", type=int, help="可选随机种子，使编排可复现")
    args = parser.parse_args(argv)
    try:
        if args.min_run < 1 or args.max_run < args.min_run:
            raise ValueError("必须满足 1 <= --min-run <= --max-run")
        if not math.isfinite(args.balance_alpha) or not 0 <= args.balance_alpha <= 1:
            raise ValueError("--balance-alpha 必须介于 0 和 1 之间")
        start = datetime.fromisoformat(args.start) if args.start else datetime.now(timezone(timedelta(hours=8)))
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("--start 必须带时区，如 +08:00")
        sources = load_json(args.sources, "片源")
        priorities = load_json(args.priorities, "优先级配置") if args.priorities else None
        starts = None
        if args.mode == "continue":
            previous = load_json(args.previous_schedule or args.output, "旧节目表")
            starts = continuation_starts(previous, sources, start)
        programs, seconds = generate(sources, min_run=args.min_run, max_run=args.max_run, balance_alpha=args.balance_alpha, priorities=priorities, starts=starts, seed=args.seed)
        schedule = {"channel": args.channel, "startTime": start.isoformat(timespec="seconds"), "programs": programs}
        write_json_atomic(args.output, schedule)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(f"生成 {args.output}：{len(programs)} 集、{len(set(p['title'] for p in programs))} 部作品、约 {seconds / 3600:.1f} 小时")
    print("所有作品都已至少完整播放一轮；较短作品可能循环多次。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
