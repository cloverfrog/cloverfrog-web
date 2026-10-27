# TinyTV 后端

提供固定频道时间线和认证后的 AList 下载地址，接口前缀为 `/api/tinytv`，依赖[公共认证](../../auth/README.md)。前端使用说明见[网站模块文档](https://github.com/cloverfrog/cloverfrog.github.io/blob/main/pages/tinytv/README.md)。

## 模块配置

以下变量属于本模块，通过项目根目录 `.env` 加载：

| 配置 | 用途 |
| --- | --- |
| `ALIST_URL` | AList 服务地址，默认 `https://alist.cloverfrog.xyz` |
| `ALIST_ROOT` | AList 影视挂载目录，可为空；与 sources.json 的 path 拼接 |

频道接口将 `ALIST_URL + '/d' + ALIST_ROOT + '/' + path` 作为 playUrl 返回，路径按 URL 规则编码。浏览器直接请求 AList 并跟随其 302 重定向；后端不请求 AList，也不读取或转发视频。当前没有 AList 登录或访问 token 配置，源文件必须能通过配置的下载路径访问。

## 节目与媒体源

数据位于项目根目录 `data/tinytv/`，从项目根目录启动服务。每次查询重新读取数据，修改后下次请求生效。`media.json` 中每部作品的 `seasons` 通过 `title + season` 与节目匹配，其中 `name` 作为前端显示的季名；未匹配到时前端回退显示季号。

`schedule.json` 示例：

```json
{
  "channel": "tiny",
  "startTime": "2026-01-01T00:00:00+08:00",
  "programs": [
    {"title": "示例节目", "season": 1, "episode": 1}
  ]
}
```

`startTime` 必须包含时区。节目依数组顺序循环，实际时长从媒体源读取；时间线由服务器当前时间推算。

`sources.json` 示例：

```json
[
  {"title": "示例节目", "season": 1, "episode": 1, "path": "示例节目/S01E01.mp4", "duration": 600.25},
  {
    "title": "示例节目",
    "season": 1,
    "episode": 2,
    "parts": [
      {"path": "示例节目/S01E02a.mp4", "duration": 300.5},
      {"path": "示例节目/S01E02b.mp4", "duration": 320.75}
    ]
  }
]
```

通过 title、season、episode 匹配节目与媒体源，组合键不可重复，每个编排的节目都必须有对应媒体源。普通剧集使用 `path + duration`；一个逻辑剧集由多个文件组成时改用有序的 `parts`，不可同时保留顶层 `path` 或 `duration`。各部分按数组顺序无间隔播放，节目单中仍只计作一集。实际读取路径为 `ALIST_ROOT + '/' + path`。

`duration` 是对应视频文件的实际时长，单位为秒，必须为正数，允许小数。多文件剧集的逻辑时长是各 part 时长之和。后端优先读取源记录的时长；单文件记录缺失该字段时暂时兼容旧节目单中的时长，多文件记录则要求每个 part 都有有效时长。数据文件缺失、JSON 解析失败或配置无效时，频道接口返回 500 和通用响应 `{"detail":"Channel unavailable"}`，不向客户端暴露文件路径或异常详情。模块日志 `modules.tinytv.router` 以 ERROR 级别记录频道标识、原始异常及完整堆栈；由 systemd 托管时可通过 `journalctl -u cloverfrog-backend` 查看。公共认证上游临时不可用时仍返回 503。批量采集方法见[本地维护工具](../../../tools/tinytv/README.md)。

前端使用浏览器原生 `<video>` 播放，不附带额外解码器。片源应采用目标浏览器支持的封装和编码；为了兼容常见桌面与移动浏览器，建议统一为 MP4 封装、H.264 视频和 AAC 音频，并修复异常时间戳、关键帧和索引信息。

## 接口与直连播放

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/tinytv/channels/tiny/now` | 认证后返回当前节目、季名、当前文件内偏移和剩余时间、逻辑剧集剩余时间、分段序号、下一节目、当前起最多 11 条节目和 AList `/d/...` 地址 playUrl；开播前返回 waiting 与开播时间 |

播放状态中的 `offset`、`remaining` 对应当前视频文件，供播放器在 part 边界换源；`programStart`、`programEnd`、`programRemaining` 和 `duration` 对应完整逻辑剧集。`partIndex` 从 1 开始，`partCount` 是该集文件数，单文件剧集分别为 1 和 1。`upcoming` 从当前节目开始，按频道循环顺序最多返回 11 条，避免向前端发送完整节目表。

接口需要公共认证，响应禁止缓存。不再提供 `/api/tinytv/play/{key}` 接口。浏览器直接使用 playUrl 播放，AList 的下载重定向、Range 请求和视频传输均不经过本站后端。

已登录观看者可以看到 AList 地址；片源访问权限、重定向地址的有效期由 AList 和媒体源控制，退出网站登录不撤销已获得的地址。网站登录 Cookie 不发送给片源。

AList 及重定向后的媒体源需要允许网站跨域读取（CORS），支持 Range 与 206，并暴露 `Content-Length`、`Content-Range`、`Accept-Ranges` 响应头；HTTPS 页面使用 HTTPS 片源。播放器跨域请求不携带 Cookie，使用 no-referrer 策略。

后端不转码、不缓存视频、不承担视频传输流量。

## 验证

`tests/test_timeline.py` 验证开播、节目及分段边界、循环和节目时长；`tests/test_api.py` 验证登录限制、AList 下载地址和路径编码，并确认频道接口不访问 AList 或媒体源，同时覆盖频道数据异常的 500 响应、通用错误信息和服务端异常堆栈日志。统一运行命令见[后端 README](../../README.md)。

真实联调时配置可访问的 AList 挂载和媒体源，使用普通账号登录前端，验证从当前进度播放、节目切换、视频编码支持和退出。
