# TinyTV 本地维护工具

## build_sources.py — 从 AList 生成片源清单

脚本从 `backend/.env` 读取 `ALIST_URL` 和 `ALIST_ROOT`，通过 AList `/api/fs/list` 递归枚举媒体文件，再按各季的 `pattern` 匹配分集。目录接口需要认证时，可配置 `ALIST_TOKEN`，或同时配置 `ALIST_USERNAME`、`ALIST_PASSWORD`；账号密码仅用于登录并获取本次运行的临时 token。

```bash
python tools/tinytv/build_sources.py --config sources_config.json --output backend/data/tinytv/sources.json
```

输出只包含 `title`、`season`、`episode` 和相对于 `ALIST_ROOT` 的 `path`，不探测 `duration`。生成后再运行 `probe_durations.py`；它会跳过已有有效时长，并从既有输出恢复路径未变化的记录。

`--dry-run` 会完成 AList 枚举和匹配检查，但不写输出文件。AList 对 `ALIST_ROOT` 需要允许目录浏览。

## probe_durations.py — 批量采集时长

先安装项目 Python 依赖和 FFmpeg，确保 `ffprobe` 可执行。在项目根目录、激活虚拟环境后运行：

```bash
# 先试采集 3 条，再运行全部
python tools/tinytv/probe_durations.py --limit 3
python tools/tinytv/probe_durations.py
```

读取 `backend/.env` 的 `ALIST_URL`、`ALIST_ROOT`，通过 `/d/` 直链采集。命令行参数优先于环境变量，环境变量优先于 `backend/.env`。

| 文件 | 用途 |
| --- | --- |
| `backend/data/tinytv/sources.json` | 输入，保持原样 |
| `backend/data/tinytv/sources.probed.json` | 输出，补充数值型 `duration`，单位为秒 |
| `backend/data/tinytv/sources.probed.errors.json` | 本次运行的失败记录 |

每处理一条保存一次结果。重复运行相同命令会跳过已有有效时长，并从输出文件恢复同一分集、同一路径的采集结果；失败项会重试。中断后也可直接重跑。

检查输出的 `failed`、`remaining` 和结果文件，确认所需分集时长完整后，再自行替换 `sources.json`。工具不会自动替换原文件或修改节目单。

可用 `--input`、`--output` 指定文件，`--base-url`、`--root` 覆盖 AList 配置，`--ffprobe` 指定程序位置；单文件总超时默认 60 秒，可用 `--timeout` 调整。完整参数见 `--help`。

数据字段与后端行为见 [TinyTV 模块说明](../../modules/tinytv/README.md)。

## generate_schedule.py — 随机节目编排脚本

用于 TinyTV 的节目单生成工具。读取 `sources.json` 中的视频资源及其时长，随机打散不同动画的播放顺序，生成固定的 `schedule.json` 节目时间线。

**编排规则：**
- **随机起点**：每部作品从随机一集开始，之后按季数、集数顺序播放；播到末尾自动接回开头。
- **连续播放**：每次选中一部作品，默认连续播放 **2～3 集**，再随机切换作品。
- **禁止连续选中**：只要有其他作品，两轮之间不会连续选中同一部；片库只有一部作品时例外。
- **适度均衡**：根据各作品**总集数**设置固定抽取权重：`权重 = 总集数 ** balance_alpha`。默认 `balance_alpha=0.6`，介于各作品等概率（`0`）和完全按集数加权（`1`）之间。权重不随剩余集数或循环轮数变化。
- **允许重复循环**：短篇作品播完一轮仍继续参与随机抽选，可能在长篇作品完成一轮前播放多轮。
- **结束条件**：所有作品都至少完整播放一轮后结束；最后一轮连播可能不足设定的最小集数。

**使用方式：**

```bash
python generate_schedule.py --min-run 2 --max-run 3
```

生成的 `schedule.json` 包含频道名称、起始时间及有序节目列表，供 TinyTV 后端查询当前播放节目。

## 上传服务器

在已经配置了 `~/.ssh/config` 的情况下，使用 `scp` 上传数据文件到服务器：

```bash
scp backend/data/tinytv/media.json backend/data/tinytv/sources.json backend/data/tinytv/schedule.json aliyun:/srv/web/backend/data/tinytv
```