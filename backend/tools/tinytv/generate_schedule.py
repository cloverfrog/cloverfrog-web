# 节目编排工具：各作品从随机一集起按集序循环，每次连播若干集后换作品，直到所有作品至少完成一轮。
#!/usr/bin/env python3
"""Generate a random TinyTV schedule with independently cycling series.

Each title starts at a random episode and retains its cyclic episode order.
A selection plays 2–3 episodes by default, then switches titles if possible.
Selections use fixed weights based on each title's total episode count raised
to balance_alpha (default 0.6), with no cycle-dependent decay.
Stop once every title has completed a cycle.
"""

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


# 返回节目列表与总秒数；使用资源中的真实时长，编排结果可由 seed 重现。
def generate(sources, *, min_run=2, max_run=3, balance_alpha=0.6, seed=None):
    if min_run < 1 or max_run < min_run:
        raise ValueError("必须满足 1 <= min_run <= max_run")
    if not math.isfinite(balance_alpha) or not 0 <= balance_alpha <= 1:
        raise ValueError("balance_alpha 必须介于 0 和 1 之间")

    grouped = defaultdict(list)
    seen = set()
    for item in sources:
        title = item["title"]
        season, episode = int(item["season"]), int(item["episode"])
        key = (title, season, episode)
        if key in seen:
            raise ValueError(f"重复资源：{key}")
        seen.add(key)
        duration = item.get("duration")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError(f"缺少有效 duration：{key}")
        grouped[title].append(item)

    if not grouped:
        raise ValueError("sources.json 中没有视频")

    # 独立随机数生成器使同一 seed 可复现；每部作品只随机起点，集序保持不变。
    rng = random.Random(seed)
    queues = {}
    for title, episodes in grouped.items():
        episodes.sort(key=lambda x: (int(x["season"]), int(x["episode"])))
        offset = rng.randrange(len(episodes))
        queues[title] = episodes[offset:] + episodes[:offset]

    # 较短作品可能在其他作品播完前循环多次，位置可超过集数，取模后继续按原集序播放。
    positions = {title: 0 for title in queues}
    previous = None
    programs = []
    total_seconds = 0.0

    while any(positions[t] < len(queues[t]) for t in queues):
        active = sorted(queues)
        candidates = [t for t in active if t != previous] if len(active) > 1 else active

        # 选片权重只由作品总集数决定：指数小于 1 时减弱长作品优势，不随剩余集数衰减。
        weights = [len(queues[t]) ** balance_alpha for t in candidates]
        title = rng.choices(candidates, weights=weights, k=1)[0]
        count = rng.randint(min_run, max_run)
        for _ in range(count):
            # 最后一部作品完成首轮后立即停止，不为凑满本次连播数量再追加节目。
            if all(positions[t] >= len(queues[t]) for t in queues):
                break
            item = queues[title][positions[title] % len(queues[title])]
            programs.append({
                "title": title,
                "season": int(item["season"]),
                "episode": int(item["episode"]),
                "duration": item["duration"],
            })
            total_seconds += item["duration"]
            positions[title] += 1
        previous = title

    return programs, total_seconds


# 命令行负责读取资源和写节目表；带时区的 startTime 是后端计算所有观众播放位置的共同起点。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("data/tinytv/sources.json"))
    parser.add_argument("--output", type=Path, default=Path("data/tinytv/schedule.json"))
    parser.add_argument("--channel", default="tiny")
    parser.add_argument("--min-run", type=int, default=2, help="每次最少连播几集，默认 2")
    parser.add_argument("--max-run", type=int, default=3, help="每次最多连播几集，默认 3")
    parser.add_argument("--balance-alpha", type=float, default=0.6,
                        help="集数权重指数（0=各作品等权，1=按集数），默认 0.6")
    parser.add_argument("--start", help="带时区的 ISO 时间，如 2026-10-17T00:00:00+08:00")
    parser.add_argument("--seed", type=int, help="可选随机种子，使编排可复现")
    args = parser.parse_args()
    if args.min_run < 1 or args.max_run < args.min_run:
        parser.error("必须满足 1 <= --min-run <= --max-run")
    if not math.isfinite(args.balance_alpha) or not 0 <= args.balance_alpha <= 1:
        parser.error("--balance-alpha 必须介于 0 和 1 之间")
    start = datetime.fromisoformat(args.start) if args.start else datetime.now(timezone(timedelta(hours=8)))
    if start.tzinfo is None or start.utcoffset() is None:
        parser.error("--start 必须带时区，如 +08:00")
    with args.sources.open(encoding="utf-8") as f:
        sources = json.load(f)
    programs, seconds = generate(
        sources,
        min_run=args.min_run,
        max_run=args.max_run,
        balance_alpha=args.balance_alpha,
        seed=args.seed,
    )
    schedule = {
        "channel": args.channel,
        "startTime": start.isoformat(timespec="seconds"),
        "programs": programs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"生成 {args.output}：{len(programs)} 集、{len(set(p['title'] for p in programs))} 部作品、约 {seconds / 3600:.1f} 小时")
    print("所有作品都已至少完整播放一轮；较短作品可能循环多次。")


if __name__ == "__main__":
    main()
