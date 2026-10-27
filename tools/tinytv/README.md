# TinyTV 本地维护工具

## build_sources.py — 从 AList 生成片源清单

脚本从 `backend/.env` 读取 `ALIST_URL` 和 `ALIST_ROOT`，通过 AList `/api/fs/list` 递归枚举媒体文件，再按各季的 `pattern` 匹配分集。目录接口需要认证时，可配置 `ALIST_TOKEN`，或同时配置 `ALIST_USERNAME`、`ALIST_PASSWORD`；账号密码仅用于登录并获取本次运行的临时 token。

```bash
python tools/tinytv/build_sources.py --config sources_config.json --output backend/data/tinytv/sources.json
```

普通剧集输出 `title`、`season`、`episode` 和相对于 `ALIST_ROOT` 的 `path`，不探测 `duration`。一个逻辑剧集需要依次播放多个文件时，在对应 season 中用 `episodeParts` 显式列出各 part 的匹配规则：

```json
{
  "season": 5,
  "episodes": 20,
  "pattern": "Show/S{season:02d}E{episode:02d}.mp4",
  "episodeParts": {
    "12": [
      "Show/S{season:02d}E{episode:02d}a.mp4",
      "Show/S{season:02d}E{episode:02d}b.mp4"
    ]
  }
}
```

每条 part 规则必须恰好匹配一个文件，且同一集不能重复匹配同一文件；输出使用有序的 `parts: [{"path": ...}, ...]`。没有列入 `episodeParts` 的剧集继续要求普通 `pattern` 恰好匹配一个文件。生成后再运行 `probe_durations.py`；它会分别探测每个文件，跳过已有有效时长，并从既有输出恢复路径未变化的结果。

`--dry-run` 会完成 AList 枚举和匹配检查，但不写输出文件。AList 对 `ALIST_ROOT` 需要允许目录浏览。

## probe_durations.py — 批量采集时长

先安装项目 Python 依赖和 FFmpeg，确保 `ffprobe` 可执行。在项目根目录、激活虚拟环境后运行：

```bash
# 先试采集 3 条，再运行全部
python tools/tinytv/probe_durations.py --limit 3
python tools/tinytv/probe_durations.py
```

读取 `backend/.env` 的 `ALIST_URL`、`ALIST_ROOT` 和 `ALIST_TOKEN`，通过 `/d/` 直链采集。配置 token 时，每个待探测文件先调用 `/api/fs/get` 获取签名，再将带 `sign` 参数的地址交给 ffprobe；签名为空时使用普通直链，未配置 token 时保留直接拼接地址。API 失败记录为该文件采集失败，不降级为无签名地址，错误报告不包含 token 或上游响应。启用 Sign all 前必须配置有效 token。命令行参数优先于环境变量，环境变量优先于 `backend/.env`。

| 文件 | 用途 |
| --- | --- |
| `backend/data/tinytv/sources.json` | 输入，保持原样 |
| `backend/data/tinytv/sources.probed.json` | 输出，为单文件记录或每个 part 补充数值型 `duration`，单位为秒 |
| `backend/data/tinytv/sources.probed.errors.json` | 本次运行的失败记录 |

每处理一个视频文件保存一次结果。重复运行相同命令会跳过已有有效时长，并从输出文件恢复同一分集、同一路径的采集结果；多文件剧集只重新探测缺失或路径发生变化的 part。失败项会重试，中断后也可直接重跑。

检查输出的 `failed`、`remaining` 和结果文件，确认所需分集时长完整后，再自行替换 `sources.json`。工具不会自动替换原文件或修改节目单。

可用 `--input`、`--output` 指定文件，`--base-url`、`--root` 覆盖 AList 配置，`--ffprobe` 指定程序位置；单次探测超时默认 60 秒，可用 `--timeout` 调整。普通探测超时后，工具会禁用 HTTP 跳转读取并顺序重试一次，因此单个异常文件最多会等待两次超时时间。完整参数见 `--help`。

数据字段与后端行为见 [TinyTV 模块说明](../../backend/modules/tinytv/README.md)。

## generate_schedule.py — 节目编排脚本

用于 TinyTV 的节目单生成工具。读取 `sources.json` 中的逻辑剧集及其时长，随机打散不同动画的播放顺序，生成固定的 `schedule.json` 节目时间线。多文件剧集的时长为所有 part 之和，在抽取、计数和节目单中仍只算一集。

**编排规则：**
- **作品起点**：完全随机模式下，每部作品从随机一集开始；延续模式下，已有作品从旧节目表的播放进度继续。之后均按季数、集数顺序播放，播到末尾自动接回开头。
- **连续播放**：每次选中一部作品，默认连续播放 **2～3 集**，再随机切换作品。
- **禁止连续选中**：只要有其他作品，两轮之间不会连续选中同一部；片库只有一部作品时例外。
- **适度均衡**：固定抽取权重为 `总集数 ** balance_alpha * priority`。`balance_alpha` 默认 `0.6`，介于各作品等概率（`0`）和完全按集数加权（`1`）之间；作品 `priority` 默认 `1`。权重不随剩余集数或循环轮数变化。
- **允许重复循环**：短篇作品播完一轮仍继续参与随机抽选，可能在长篇作品完成一轮前播放多轮。
- **结束条件**：所有作品都至少完整播放一轮后结束；最后一轮连播可能不足设定的最小集数。

**使用方式：**

完全随机编排：

```bash
python tools/tinytv/generate_schedule.py --mode random --min-run 2 --max-run 3 --seed 123
```

延续现有节目表：

```bash
python tools/tinytv/generate_schedule.py --mode continue \
  --previous-schedule backend/data/tinytv/schedule.json \
  --start 2026-10-22T20:00:00+08:00 --seed 123
```

`--mode continue` 根据旧节目表的 `startTime` 和逐集 `duration` 计算新开始时间处的进度。切换时正在播放的剧集视为已经播放，各作品从下一有效集继续；旧节目表已经结束时停在最后位置，不循环旧表。旧表尚未开始时视为没有进度。新增作品随机选择起始集，删除作品不再参与；原作品增删片源后，按新的季、集顺序寻找最后播放位置的后继。

未指定 `--previous-schedule` 时，延续模式读取 `--output` 指向的现有节目表。脚本会先完整读取并验证旧表，再以临时文件原子替换输出，因此可以安全地读取并覆盖同一路径。旧表无效时不会修改原文件。

作品优先级集中写在单独的 JSON 对象中，通过 `--priorities` 指定，不写入逐集片源数据：

```json
{
  "作品 A": 2,
  "作品 B": 0.5
}
```

没有列出的作品使用默认优先级 `1`。优先级必须是大于 `0` 的有限数字，配置中出现片源不存在的作品名会报错。`--seed` 同时控制作品抽取和需要随机起点的作品；输入及其他参数相同时，结果可复现。

生成的 `schedule.json` 包含频道名称、起始时间及有序节目列表，供 TinyTV 后端查询当前播放节目。

## 上传服务器

在已经配置了 `~/.ssh/config` 的情况下，使用 `scp` 上传数据文件到服务器：

```bash
scp backend/data/tinytv/media.json backend/data/tinytv/sources.json backend/data/tinytv/schedule.json aliyun:/srv/web/backend/data/tinytv
```
