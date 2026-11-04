# Collection

由 PocketBase 配置驱动的只读收藏展示模块。前端入口为 `/pages/collection/`（类型目录），展示页为 `/pages/collection/view.html?type=类型键`。沿用现有静态托管和 `/api/*` 代理，不需要额外 Caddy 路由。前端代码位于 `frontend/pages/collection/`，本说明是模块唯一的配置与接入文档。

依赖[公共认证](../../auth/README.md)与[前端公共登录](../../../../frontend/login/README.md)。不提供注册、独立登录、导入、编辑、筛选、分组、视图编辑或视频播放；不在浏览器持久保存业务数据。

## PocketBase 注册表

在 PocketBase 后台创建 Base Collection `collection_types`：

| 字段 | 配置 |
| --- | --- |
| `key` | Text，必填，最大 64，格式 `[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}`，唯一索引；同时作为类型代号和业务表名称，必须与目标 PocketBase Collection 名称一致 |
| `name` | Text，必填，建议最大 100；页面显示名称 |
| `allowed_users` | Relation → `users`，多值，选择允许查看此类型的账号 |
| `media_gateway` | URL，媒体网关基础地址；支持 HTTP/HTTPS，可带目录前缀，不能带账号密码、查询参数或锚点 |
| `display` | JSON，必填，保存下述展示协议 |

`key` 的唯一索引：

```sql
CREATE UNIQUE INDEX idx_collection_types_key ON collection_types (key)
```

List/View Rules：

```text
@request.auth.id != "" && allowed_users.id ?= @request.auth.id
```

Create/Update/Delete 保持 **locked**。配置由管理员在后台维护，不能授予普通用户修改配置的权限：配置能够决定后端请求的目标表与媒体网关。

未授权的类型不会出现在类型目录中。指定类型的请求先通过注册表的 List 与 View Rules，再请求对应业务表。没有本地白名单，不使用超级用户 token；类型配置也不跨请求缓存。

## 业务表与字段映射

每个类型独立创建业务 Base Collection，名称与注册记录的 `key` 完全一致，不另设目标表映射。例如 `key` 为 `example` 时，后端读取 `example` 表；更改业务表名时需要同步修改注册记录的 `key` 和页面链接中的 `type`。字段名与结构由数据本身决定。PocketBase 内部 `id` 保持默认 15 位小写字母或数字，用于接口定位；原始业务 ID 使用单独字段，在本表建立唯一索引，用于未来导入和去重，无需跨表统一。

各业务表独立维护 List/View Rules，规则必须要求登录，并按需要限制账号或记录。类型可见性不会自动授权业务表。阶段 1 的 Create/Update/Delete 保持 locked，测试记录在后台手动录入。业务表可自行使用 Relation → users 表达权限；无需创建框架专用账号权限字段。

展示协议示例（全部为虚构字段，按实际表结构替换）：

```json
{
  "title_field": "caption",
  "identifier_field": "source_code",
  "properties": [
    {"field": "score", "label": "评分", "format": "number"},
    {"field": "labels", "label": "标签", "format": "tags"},
    {"field": "complete", "label": "完成", "format": "boolean"}
  ],
  "resources": {
    "artwork": {"field": "image_path"}
  },
  "cover": "artwork"
}
```

- `title_field`、`identifier_field` 必填，指定卡片标题和业务编号字段；值为文本、数字或布尔值时显示，其他值显示 `—`。文本编号保留前导零。
- `properties` 的数组顺序就是属性展示顺序，最多 30 项。`label` 为显示标签；`format` 支持 `text`（默认）、`number`、`boolean`、`tags`（字符串数组）。缺失、不兼容或空值显示 `—`。
- `resources` 是最多 30 个资源槽位的映射，槽位名遵循与类型键相同的字符规则；每个槽位指定保存相对资源路径的业务字段。
- `cover` 指定封面槽位，可省略或为 null。无封面路径时显示占位；图片请求失败只影响该卡片。
- 字段名仅支持直接字段，格式 `[a-zA-Z_][a-zA-Z0-9_]{0,63}`；不支持嵌套访问、关系展开、表达式、模板、HTML 或脚本。资源字段不能同时用作标题、编号或展示属性，避免意外公开资源路径。
- 未知配置键、非法字段映射或未注册的封面槽位返回配置错误，不猜测业务字段。列表仍可显示该类型名称，其他类型不受影响。

例如上述业务表可包含 `caption`、`source_code`、`score`、`labels`、`complete`、`image_path`；另一个类型可完全使用其他名称。新增类型无需修改前后端或 Caddy，新增高级格式才需扩展框架协议。

## 媒体网关与资源读取

不同类型可配置不同网关。假设 `media_gateway` 为 `http://media.example.test/base/`，记录的资源字段为 `folder/image.png`，后端请求 `/base/folder/image.png`。实际网关、字段、路径和配置只存 PocketBase，不写入源码或公开仓库。

相对路径使用未 URL 编码的原始文本，可包含空格和中文；不要填写完整 URL、开头的 `/`、反斜杠、百分号、查询参数、锚点、控制字符、空路径段、`.` 或 `..`。后端逐路径编码并拒绝重定向，客户端不能提交网关或任意资源地址。

每次读取资源先验证公共登录、类型权限、记录 View Rule，再从配置的网关读取，不向浏览器返回真实源站地址或相对路径，不向网关附加 PocketBase token、用户 Cookie 或服务间认证。后端机器需能访问对应的 Tailscale/Caddy 链路。

当前仅读取 JPEG、PNG、WebP，校验 Content-Type 和文件头，最多 10 MiB，读取超时 20 秒、连接超时 5 秒。采用有大小上限的完整读取，避免向客户端返回半张图片；浏览器使用临时 Blob URL，翻页和离开时释放。`resources/{slot}` 接口不与封面字段绑定，但当前不支持视频、Range、转码或下载管理。

本站接口始终认证并禁止缓存；网关自身的网络可达性与访问控制由部署环境负责，不能以本站接口代替源站访问控制。退出后新网络请求被拒绝，已经显示或被用户保存的内容不能撤回。

## 只读 API

全部接口需要公共登录，以当前普通用户 token 请求 PocketBase；响应统一 `Cache-Control: private, no-store`。

| GET 路径 | 返回 |
| --- | --- |
| `/api/collection/types?page=1` | `{page,totalPages,totalItems,items:[{key,name}]}` |
| `/api/collection/types/{key}` | `{key,name,properties:[{label,format}]}`，仅包含页面需要的配置 |
| `/api/collection/types/{key}/items?page=1` | `{page,totalPages,totalItems,items:[{id,title,identifier,properties,cover}]}` |
| `/api/collection/types/{key}/items/{id}/resources/{slot}` | 经权限检查后的图片内容 |

`properties` 值数组与类型详情中的属性顺序一致；`cover` 为本站资源接口相对地址或 null。类型目录和条目每页固定 24 项，page 范围 1–100000；目录按 key 排序，条目按 PB 内部 id 稳定排序。客户端不能指定目标表、字段、filter、sort 或 expand，额外查询参数不会转发。

401 表示认证失效，前端清空内容并进入公共登录页；403/404 显示无权限或内容不存在；429 提示稍后重试；422 表示参数错误；存储、网关临时故障及配置错误返回 503。不回显上游错误详情。PocketBase List Rule 可以返回 200 空列表，不能据此区分“没有记录”和“没有可见记录”；View Rule 不满足通常返回 404。

## 配置与验收

没有模块专用环境变量，使用已有 PocketBase 与公共认证配置。配置随请求从数据库读取。后端启动和依赖见[后端说明](../../README.md)。

在仓库根目录运行模拟测试和现有回归测试（PowerShell）：

```powershell
$env:PYTHONPATH = "$PWD/backend;$PWD"
backend/.venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/test_collection_frontend.mjs tests/test_tinytv_player.mjs
```

真实联调由后台手动准备集合、规则、账号和少量测试记录：

1. 准备两个不同字段结构的业务表与注册配置，确认类型目录、卡片属性顺序、编号和图片显示正确；修改展示配置后刷新即可生效。
2. 使用授权、未授权两个普通账号分别测试类型和业务表权限，直接调用 PB API 确认规则同样生效。未登录直接访问类型、条目和本站图片接口均应被拒绝。
3. 测试无封面、空列表、非法配置、分页、图片失败、网关故障和 PocketBase 临时故障。
4. 退出登录后重新请求原图片及数据接口，应返回 401；已有标签页下一次受保护请求遇到 401 时清空并跳转登录。
5. 检查现有网站功能。测试样例不得使用真实私人条目、来源或资源地址。

权限语义参考 [PocketBase API Rules](https://pocketbase.io/docs/api-rules-and-filters/)。
