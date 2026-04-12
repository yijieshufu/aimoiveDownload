# 已修复问题与开发备忘

> 将线上/本地曾出现的问题与对应修复**沉淀为可检索条目**，避免后人重复踩坑。  
> 产品级能力说明仍以 [PRODUCT_STATUS.md](./PRODUCT_STATUS.md) 为主；本页侧重**故障现象、根因与代码落点**。

## 使用方式

- 迭代时若修复了**可复现的缺陷**或消除了**易误解的行为**，请在本文件追加一条（保持时间倒序或按模块分组均可）。
- 若涉及环境变量、启动顺序或对外接口语义，请同步 [PRODUCT_STATUS.md](./PRODUCT_STATUS.md) 相应小节与 [tests/ACCEPTANCE.txt](../tests/ACCEPTANCE.txt)（如验收步骤依赖环境）。

---

## 1. 环境与配置

### 1.1 开发期「AI 总结」误报 401 / 误弹升级窗

| 项目 | 说明 |
|------|------|
| **现象** | 本地未登录点击 AI 总结返回 401，或前端一直引导登录/升级。 |
| **根因** | `.env` 未在业务代码读取前进入 `os.environ`；且仅读 `cwd` 下 `.env` 易漏掉只放在 `backend/.env` 的配置；未显式配置时匿名策略与预期不一致。 |
| **修复要点** | 在 `backend/main.py` **最先**调用 `load_dotenv_files()`；依次合并**仓库根**与 **`backend/.env`**，且不覆盖 shell 已导出变量；匿名总结策略见 `usage_limits._dev_allow_anonymous_summarize()`。 |
| **相关文件** | [backend/env_bootstrap.py](../backend/env_bootstrap.py)、[backend/main.py](../backend/main.py)、[backend/usage_limits.py](../backend/usage_limits.py) |
| **详细叙述** | [PRODUCT_STATUS.md §2.4](./PRODUCT_STATUS.md#24-已修复开发期ai-总结仍要登录--弹升级窗) |

### 1.2 pytest 污染本地数据库 / 额度行为与开发机不一致

| 项目 | 说明 |
|------|------|
| **现象** | 跑测试后本地 `app.db` 被改写，或测试里额度统计与「本地不限次解析」不一致。 |
| **根因** | `backend.main` 导入时会 `init_db()`；若未提前指定 `DATABASE_PATH`，会落到默认 `backend/data/app.db`。本地开发默认 `DEV_BYPASS_EXTRACT_DOWNLOAD` 未显式关闭时不计解析/下载日额度，与测试期望不同。 |
| **修复要点** | 在**任何** `import backend.*` 之前设置 `os.environ["DATABASE_PATH"]` 指向临时目录；测试里显式 `DEV_BYPASS_EXTRACT_DOWNLOAD=0` 以便断言额度。 |
| **相关文件** | [tests/conftest.py](../tests/conftest.py)、[backend/database.py](../backend/database.py)、[backend/usage_limits.py](../backend/usage_limits.py) |

### 1.3 手工验收清单与本地开发策略

| 项目 | 说明 |
|------|------|
| **说明** | [tests/ACCEPTANCE.txt](../tests/ACCEPTANCE.txt) 中「未登录 AI」等步骤按**生产或接近生产**的配置编写。本地若未将 `ENVIRONMENT` 设为 `production` 且未关闭 `DEV_ALLOW_ANONYMOUS_AI`，匿名 AI 可能仍可用（见 usage_limits），验收时需按目标环境切换变量。 |

---

## 2. 抖音解析与下载

### 2.1 公开接口空数据 / 风控导致解析失败

| 项目 | 说明 |
|------|------|
| **现象** | 抖音链接解析偶发失败或返回空。 |
| **根因** | 公开 API 在风控下可能空 JSON；单靠一条链路不可靠。 |
| **修复要点** | 轻量方案失败时在 `extract_video_info` 中**回退 yt-dlp**；`douyin_parser` 在接口空时**回退分享页**提取 `playwm` 等（仍无需登录态时的路径）。 |
| **相关文件** | [backend/downloader.py](../backend/downloader.py)（`extract_video_info`）、[backend/douyin_parser.py](../backend/douyin_parser.py) |

### 2.2 无水印直链下载失败

| 项目 | 说明 |
|------|------|
| **现象** | 选用抖音无水印档位时下载失败。 |
| **根因** | CDN 或链接时效、风控导致直链不可用。 |
| **修复要点** | `format_id == "douyin_nowm"` 时直链下载失败则**捕获后继续走 yt-dlp** 变体。 |
| **相关文件** | [backend/downloader.py](../backend/downloader.py)（`download_video`） |

### 2.3 标题/文案乱码或 URL 转义未还原

| 项目 | 说明 |
|------|------|
| **现象** | 标题显示为 `\uXXXX` 或错误转义片段。 |
| **根因** | 接口或 HTML 内嵌 JSON 字符串与 UTF-8 混用。 |
| **修复要点** | `_decode_json_escaped_text` 用 `json.loads('"{value}"')` 兼容；URL 片段用 `_decode_js_escaped_url` 替换常见转义序列。 |
| **相关文件** | [backend/douyin_parser.py](../backend/douyin_parser.py) |

### 2.4 文件大小展示不稳定

| 项目 | 说明 |
|------|------|
| **现象** | 部分响应无 `Content-Length`。 |
| **根因** | 服务端 HEAD/CDN 行为不一致。 |
| **修复要点** | 优先 HEAD；无长度时用 `Range: bytes=0-0` 等回退（见 parser 内注释）。 |
| **相关文件** | [backend/douyin_parser.py](../backend/douyin_parser.py) |

---

## 3. AI 总结 / ASR

### 3.1 faster-whisper 配置 CUDA 但本机缺少动态库

| 项目 | 说明 |
|------|------|
| **现象** | 总结任务在加载模型阶段失败，日志含 cublas/cuda/cudnn 相关错误。 |
| **根因** | `WHISPER_DEVICE=cuda` 等与当前环境不匹配。 |
| **修复要点** | 加载失败且错误信息命中 CUDA 相关关键字时，**自动回退** `cpu` + `int8` 再试。 |
| **相关文件** | [backend/summarizer.py](../backend/summarizer.py)（`_transcribe_by_faster_whisper`） |

---

## 4. 数据与迁移

### 4.1 升级路径后工作台数据「消失」

| 项目 | 说明 |
|------|------|
| **现象** | 新代码使用 `backend/data/app.db`，旧数据仍在 `temp/workspace.db`。 |
| **根因** | 默认库路径变更，未迁移则新库为空。 |
| **修复要点** | 若新库不存在或为空文件且存在非空 `temp/workspace.db`，**整库复制一次**到目标路径。 |
| **相关文件** | [backend/database.py](../backend/database.py)（`_maybe_migrate_legacy`） |

---

## 5. 前端与联调

### 5.1 开发态 API 代理与生产 base 路径

| 项目 | 说明 |
|------|------|
| **现象** | 开发正常、打包后静态资源路径错误，或 `/api` 未打到后端。 |
| **根因** | 后端将构建产物挂在 `/frontend`，与 Vite 的 `base`、代理目标需一致。 |
| **修复要点** | `vite.config.js` 中 `base: '/frontend/'`，`server.proxy['/api']` 指向后端端口（默认 8001）。 |
| **相关文件** | [frontend/vite.config.js](../frontend/vite.config.js)、[backend/main.py](../backend/main.py) |

### 5.2 登录态与额度计数不生效

| 项目 | 说明 |
|------|------|
| **现象** | 已登录仍被当作匿名，或 cookie 未带上。 |
| **根因** | `fetch` 默认不跨域携带 cookie（同域代理场景下也需与后端 CORS、`credentials` 配置一致）。 |
| **修复要点** | 对需会话的接口使用 `credentials: 'include'`（见各 `frontend/src/api/*.js`）。 |
| **相关文件** | [frontend/src/api/video.js](../frontend/src/api/video.js) 等 |

---

## 6. 构建提示（非功能性缺陷）

| 项目 | 说明 |
|------|------|
| **现象** | `vite build` 报 `INEFFECTIVE_DYNAMIC_IMPORT`（html-to-image）。 |
| **说明** | 某模块同时被静态与动态 import，打包告警；**不影响**当前构建成功。若需消告警，可统一为单一引入方式。 |
| **相关文件** | `frontend` 构建日志、`App.vue` / `MindmapFlow.vue` |

---

*最后更新：与仓库实现同步维护；重大行为变更请同时更新 [PRODUCT_STATUS.md](./PRODUCT_STATUS.md)。*
