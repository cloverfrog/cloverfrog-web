# 固定频道的时间计算：根据开播时间和每集时长，返回所有观众此刻应观看的节目与偏移秒数。
"""Fixed channel timeline using the project data directory."""
import json
import math
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data/tinytv")


def read_json(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8-sig"))


def valid_duration(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def source_parts(source, legacy_duration=None):
    """Normalize a source into ordered files without mutating the input data."""
    if "parts" in source:
        if "path" in source or "duration" in source:
            raise ValueError("Multipart source cannot also define path or duration")
        raw_parts = source["parts"]
        if not isinstance(raw_parts, list) or not raw_parts:
            raise ValueError("Source parts must be a non-empty array")
    else:
        raw_parts = [{"path": source.get("path"), "duration": source.get("duration", legacy_duration)}]
    parts = []
    for part in raw_parts:
        if not isinstance(part, dict) or not isinstance(part.get("path"), str) or not part["path"]:
            raise ValueError("Missing or invalid source path")
        if not valid_duration(part.get("duration")):
            raise ValueError("Missing or invalid source duration")
        parts.append({"path": part["path"], "duration": part["duration"]})
    return parts


def season_names(media):
    """Index optional display names by the same title and season used by the schedule."""
    names = {}
    for item in media:
        for season in item.get("seasons", []):
            key = (item["title"], season["season"])
            if key in names:
                raise ValueError(f"Duplicate media season: {key}")
            name = season["name"]
            if not isinstance(name, str) or not name:
                raise ValueError(f"Missing or invalid season name: {key}")
            names[key] = name
    return names


def program_details(program, names):
    """Return a client-facing program without modifying the generated schedule."""
    result = dict(program)
    name = names.get((program["title"], program["season"]))
    if name:
        result["seasonName"] = name
    return result


# 纯计算过程，不读取当前时钟或修改输入；调用方传入 now，方便查询任意时刻的播放位置。
def timeline(schedule, sources, now, media=None):
    start = datetime.fromisoformat(schedule["startTime"])
    if start.utcoffset() is None:
        raise ValueError("startTime must include a timezone")
    scheduled = schedule["programs"]
    if not scheduled:
        raise ValueError("Empty schedule")
    names = season_names(media or [])
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
        # 单文件资源暂时兼容旧节目表时长；多文件资源必须为每个 part 提供实际时长。
        parts = source_parts(index[key], program.get("duration"))
        programs.append({**program, "duration": sum(part["duration"] for part in parts)})
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
            parts = source_parts(index[key], program["duration"])
            program_offset = now - cursor
            part_cursor = 0.0
            for part_index, part in enumerate(parts):
                part_end = part_cursor + part["duration"]
                if program_offset < part_end:
                    break
                part_cursor = part_end
            else:
                raise ValueError("Unable to locate source part")
            upcoming = [
                program_details(programs[(position + index) % len(programs)], names)
                for index in range(min(11, len(programs)))
            ]
            current = program_details(program, names)
            return {
                **current,
                "channel": schedule["channel"],
                "status": "playing",
                "path": part["path"],
                "offset": program_offset - part_cursor,
                "remaining": part_end - program_offset,
                "programRemaining": end - now,
                "programStart": cursor,
                "programEnd": end,
                "partIndex": part_index + 1,
                "partCount": len(parts),
                "serverTime": now,
                "next": program_details(programs[(position + 1) % len(programs)], names),
                "upcoming": upcoming,
            }
        cursor = end
    raise ValueError("Unable to locate program")

