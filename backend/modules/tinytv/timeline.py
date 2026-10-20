# 固定频道的时间计算：根据开播时间和每集时长，返回所有观众此刻应观看的节目与偏移秒数。
"""Fixed channel timeline using the project data directory."""
import json
import math
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data/tinytv")


def read_json(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8-sig"))


# 纯计算过程，不读取当前时钟或修改输入；调用方传入 now，方便查询任意时刻的播放位置。
def timeline(schedule, sources, now):
    start = datetime.fromisoformat(schedule["startTime"])
    if start.utcoffset() is None:
        raise ValueError("startTime must include a timezone")
    scheduled = schedule["programs"]
    if not scheduled:
        raise ValueError("Empty schedule")
    # 用作品、季、集定位资源，并在计算时间线前检查重复或缺失的资源。
    index = {}
    for source in sources:
        key = (source["title"], source["season"], source["episode"])
        if key in index:
            raise ValueError(f"Duplicate source: {key}")
        index[key] = source
    # 用资源探测时长生成有效节目表，既校准播放边界，也保留输入节目表原状。
    programs = []
    for program in scheduled:
        key = (program["title"], program["season"], program["episode"])
        if key not in index:
            raise ValueError("Missing scheduled source")
        # 优先用资源探测的时长；只有资源未提供 duration 字段时才回退到旧节目表时长。
        # 已提供但无效的资源时长必须报错，不能用旧值掩盖配置问题。
        duration = index[key].get("duration", program.get("duration"))
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("Missing or invalid source duration")
        programs.append({**program, "duration": duration})
    # 总时长决定循环周期；开播前不尝试定位视频，只向前端返回等待状态。
    total = sum(p["duration"] for p in programs)
    epoch = start.timestamp()
    if now < epoch:
        return {"status": "waiting", "serverTime": now, "startTime": epoch}
    # 节目表循环播放：先跳到当前轮次，再沿该轮节目时长定位当前节目。
    cycle = math.floor((now - epoch) / total)
    cursor = epoch + cycle * total
    for position, program in enumerate(programs):
        end = cursor + program["duration"]
        # 边界采用左闭右开区间，恰好到结束时间时切入下一节目。
        if now < end:
            key = (program["title"], program["season"], program["episode"])
            return {
                **program,
                "channel": schedule["channel"],
                "status": "playing",
                "path": index[key]["path"],
                "offset": now - cursor,
                "remaining": end - now,
                "programStart": cursor,
                "programEnd": end,
                "serverTime": now,
                "next": programs[(position + 1) % len(programs)],
                "programs": programs,
            }
        cursor = end
    raise ValueError("Unable to locate program")

