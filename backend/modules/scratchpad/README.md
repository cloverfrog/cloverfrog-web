# Scratchpad 后端

为草稿和文件速传提供 `/api/scratchpad/*`。依赖[公共认证](../../auth/README.md)，使用当前普通用户的 token 调用 PocketBase，由集合权限规则隔离数据。前端使用说明见[网站模块文档](https://github.com/cloverfrog/cloverfrog.github.io/blob/main/pages/scratchpad/README.md)。

## 接口

`collection` 仅允许 `scratchpads`、`scratchpad_files`，`id` 为 15 位小写字母或数字。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/scratchpad/collections/{collection}/records` | 列表，仅转发 page、perPage、sort 查询参数 |
| `POST /api/scratchpad/collections/{collection}/records` | 创建草稿或文件记录 |
| `GET /api/scratchpad/collections/{collection}/records/{id}` | 读取记录 |
| `PATCH /api/scratchpad/collections/scratchpads/records/{id}` | 修改草稿 |
| `DELETE /api/scratchpad/collections/{collection}/records/{id}` | 删除记录及其关联文件 |
| `GET /api/scratchpad/files/{id}` | 验证记录访问权限后流式下载文件 |

JSON 草稿写入包含 title、content；创建时还需 owner，可提供 id。文件上传使用 multipart/form-data，字段为 owner、originalName、size、file。文件记录不支持 PATCH。

所有接口需要认证，写接口校验 Origin。JSON 请求体上限 2 MiB，multipart 总请求体上限 51 MiB，实际单文件 50 MiB 限制由 PocketBase 字段配置执行。上传流式转发，存储请求超时 300 秒。下载由后端申请短期文件 token，不返回给前端。

存储接口的 400、401、403、404、413、429 状态保留，其他存储服务错误转换为 503，不暴露上游错误详情。模块没有额外环境变量，使用公共 PocketBase 配置。

## PocketBase 集合

### 草稿 `scratchpads`

创建 Base Collection：

| 字段 | 配置 |
| --- | --- |
| owner | Relation → users，必填，单值 |
| title | Text，最大 500 |
| content | Text，最大 2000000 |
| created / updated | Autodate，分别在创建 / 创建及更新时写入 |

若已有 version 字段，取消 Required、Min 设为 0，无需删除字段或已有数据。

| API Rule | 表达式 |
| --- | --- |
| List / View / Delete | `@request.auth.id != "" && owner = @request.auth.id` |
| Create | `@request.auth.id != "" && @request.body.owner = @request.auth.id` |
| Update | `@request.auth.id != "" && owner = @request.auth.id && @request.body.owner:changed = false` |

### 文件 `scratchpad_files`

创建 Base Collection：

| 字段 | 配置 |
| --- | --- |
| owner | Relation → users，必填，单值 |
| file | File，必填，Max Files = 1，Max Size = 52428800 bytes，**Protected 开启**，类型不限 |
| originalName | Text，必填，最大 1024 |
| size | Number，必填，整数，Min 1，Max 52428800 |
| created / updated | Autodate，分别在创建 / 创建及更新时写入 |

List / View / Delete、Create 规则与草稿集合相同，Update 保持 locked。必须同时开启 Protected 并设置 owner 的 View 规则。

文件默认存储在 PocketBase `pb_data/storage`，随记录删除；备份需包含数据库和 storage。容量取决于服务器磁盘和带宽。不提供公开分享。

字段长度按 PocketBase 配置执行，请求体大小按字节限制，正文接近字段上限时仍可能先达到 JSON 请求体上限。

## 清理与验证

3 天过期清理由前端在使用时发起普通读写请求，后端没有定时清理任务。完整保留策略见前端模块文档。

`tests/test_scratchpad.py` 覆盖共享认证、草稿读写、路由范围、来源校验、上传下载、请求大小限制、权限拒绝和服务故障。运行命令见[后端 README](../../README.md)。真实联调需按上述配置准备集合，验证保存、刷新、上传、下载与删除。

PocketBase 配置参考：[API Rules](https://pocketbase.io/docs/api-rules-and-filters/)、[文件处理](https://pocketbase.io/docs/files-handling/)。
