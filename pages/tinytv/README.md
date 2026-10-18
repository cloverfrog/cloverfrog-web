# TinyTV

访问 `/pages/tinytv/`，观看按固定时间线循环播放的频道。依赖[网站公共认证](../../login/README.md)和[TinyTV 后端](https://github.com/cloverfrog/cloverfrog.github.io-backend/blob/main/modules/tinytv/README.md)。

## 使用

登录后显示当前节目和下一节目，展开节目单可查看当前节目和之后最多 10 个节目，按频道顺序跨循环显示，不重复展开整份节目单。点击画面中央的“进入频道”开始播放，进度跟随后端频道时间，不从头播放，不提供暂停、拖动进度或选集操作。频道尚未开播时显示开播时间。播放成功后中央按钮消失，播放受阻或加载失败时可点击“重新进入”。

正常播放时画面仅显示右下角全屏按钮，没有底部托盘、渐变遮罩或常驻播放状态文字。全屏按钮静置 2.5 秒后隐藏，移动指针、触屏或键盘操作时显示；等待、缓冲、报错和键盘聚焦操作按钮时保持显示。重要提示以左下角局部提示显示，恢复正常播放后隐藏。手机页面以贴边视频和紧凑页头呈现。

点击画面右下角的全屏按钮进入全屏播放，并在浏览器支持时尝试锁定横屏，退出全屏时解除锁定。横屏锁定失败不影响全屏，不支持标准全屏 API 的浏览器显示提示；未提供 Apple 专用全屏适配。

播放使用 AVPlayer 的非 MSE 路径，优先使用 WebCodecs 和硬件加速，解码器不支持时由库回退至 WASM。随模块准备的解码资源覆盖 H.264、H.265 和 AAC；软解性能取决于设备。浏览器暂停音频上下文时，点击“重新进入”恢复声音。

## 开发与依赖

`player.js` 负责频道时间校准和全屏交互，`playback.js` 封装 AVPlayer 的加载、定位、播放事件和资源释放，`style.css` 维护本模块样式。页面调用同源 `/api/tinytv/*` 查询节目与播放，媒体请求携带同源登录 Cookie，前端不保存 AList 地址或源文件路径。进入频道和切集时先定位再播放；播放中的同步查询间隔和进度偏差阈值分别为 15 秒、30 秒。

## 播放器资源

使用 [libmedia AVPlayer](https://github.com/zhaohappy/libmedia) 1.3.1，源码提交 `152f629d3021fd8013efa464fcb7b55f9fbe7753`，许可证为 LGPL-3.0-or-later。未修改的官方预编译文件随模块提交在 `vendor/libmedia/`：`avplayer/` 包含 npm 发行版的播放器及动态 JS 分块，`decode/`、`resample/`、`stretchpitch/` 包含官方演示站提供的 H.264、H.265、AAC 和音频处理 WASM。许可证和源码入口见该目录的 `COPYING.LGPLv3`、`SOURCE.txt`。

播放器资源随网站代码一同部署。运行时从本模块目录按需加载，不请求第三方 CDN；服务器需正确提供 JavaScript 和 `application/wasm` MIME 类型。

使用非共享内存模式，不依赖全站 COOP/COEP、SharedArrayBuffer 或 Service Worker；没有引入构建系统。

## 验证

节目编排、媒体源配置、接口和视频代理说明见后端模块 README；本地启动见[网站 README](../../README.md)。修改前端脚本后可在本目录检查语法：

```bash
node --check player.js
node --check playback.js
```

联调时验证原始异常时间戳片源的运动画面、声音和音画同步，以及当前进度播放、节目切换、全屏操作和登录过期处理。还需在手机上验证解码性能。真实播放验证需要配置可访问的媒体源。
