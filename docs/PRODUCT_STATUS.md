# 产品与技术现状说明

> 便于后续开发对齐认知：「解析 + 下载」主能力已落地，持续迭代集中在体验、环境与边界场景。

## 1. 结论摘要

**多平台视频的「解析元数据」与「按格式下载到本地」主链路已实现**，可在此基础上做体验优化与站点个案排查，而非从零搭建下载内核。

## 2. 已实现能力（解析与下载）

### 2.1 后端


| 项目      | 说明                                                                                                                                |
| ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 核心依赖    | 通过 `**yt-dlp`** 封装解析与下载，代码集中在 `[backend/downloader.py](../backend/downloader.py)`。                                                |
| 解析接口    | `POST /api/extract`：入参 JSON `{ "url": "..." }`，返回标题、时长、作者、封面、可用 `formats` 等（见 `[backend/api_video.py](../backend/api_video.py)`）。 |
| 下载接口    | `GET /api/download?url=...&format_id=...` 生成临时文件；`GET /api/download/file?file_path=...` 供浏览器拉取文件。                                 |
| 抖音      | 短链优先走轻量解析（`[backend/douyin_parser.py](../backend/douyin_parser.py)`），失败时回退 `yt-dlp`；另有 `POST /api/douyin/parse`。                  |
| 封面代理    | `GET /api/thumbnail`：缓解部分站点防盗链导致封面无法展示。                                                                                           |
| Cookies | `POST /api/cookies/upload`、`GET /api/cookies/status`：支持 Netscape 格式 cookies，供需登录站点使用。                                             |
| 错误提示    | `format_user_ytdlp_error()` 将常见 yt-dlp 异常转写为更易读的中文（同 `downloader.py`）。                                                            |
| 4K / 超清 | 非 Pro 用户后端拒绝超清档位下载（与前端 Pro 提示一致）。                                                                                                 |


### 2.2 前端


| 项目     | 说明                                                                                                                                                                               |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API 封装 | `[frontend/src/api/video.js](../frontend/src/api/video.js)`：`apiExtract`、`apiDownload`、`apiDownloadFileUrl`；请求带 `credentials: 'include'` 以配合登录态额度。                               |
| 交互     | `[VideoUrlBar.vue](../frontend/src/components/VideoUrlBar.vue)` 输入链接、主解析、串行批量、快捷「试试」示例；`[VideoResultPanel.vue](../frontend/src/components/VideoResultPanel.vue)` 展示预览与格式列表并触发下载。 |


### 2.3 额度与限流（与下载共用请求上下文）

- 按日统计、匿名 / 登录免费 / Pro 差异：`[backend/usage_limits.py](../backend/usage_limits.py)`。
- 按分钟 IP 突发限制：同模块 `check_burst`。
- 数据表：`usage_daily`（见 `[backend/database.py](../backend/database.py)` 初始化脚本）。
- 登录与订阅信息：`GET /api/me` 含 `usage` 字段（`[backend/auth_routes.py](../backend/auth_routes.py)`）。
- **AI 总结额度**：线上未登录调用 `POST /api/summarize` 在无「开发匿名」策略时为 401；本地开发默认允许匿名总结（按 IP 日限额，见 `[backend/usage_limits.py](../backend/usage_limits.py)` 与 `[backend/.env.example](../backend/.env.example)`）。生产环境须设置 `ENVIRONMENT=production` 或 `DEV_ALLOW_ANONYMOUS_AI=0`，避免误开匿名额度。

## 2.4 已修复：开发期「AI 总结仍要登录 / 弹升级窗」

**现象**：本地点击「AI 总结」仍返回 401「请先登录后再使用 AI 视频总结」，前端弹出升级 Pro + 登录引导。

**原因（历史）**：

1. `assert_can_summarize` 早于总结流水线里对 `.env` 的注入执行，写在文件里的 `DEV_ALLOW_ANONYMOUS_AI` 往往尚未进入 `os.environ`。
2. 原先仅从 `os.getcwd()/.env` 读配置，易漏掉只放在 `backend/.env` 或未建 `.env` 的情况。
3. 未显式配置开发开关时，匿名总结一律按「禁止」处理。

**当前修复**：

- 启动时尽早加载环境：[`backend/env_bootstrap.py`](../backend/env_bootstrap.py) 由 [`backend/main.py`](../backend/main.py) 在其它子模块导入前调用，依次合并 **项目根 `.env`** 与 **`backend/.env`**（不覆盖已在 shell 中 `export` 的变量）。
- 开发期默认策略：[`backend/usage_limits.py`](../backend/usage_limits.py) 中 `DEV_ALLOW_ANONYMOUS_AI` 为 `0/false/no/off` 时强制关闭；为 `1/true/yes/on` 时强制开启；**未配置时**，若 `ENVIRONMENT` / `ENV` / `APP_ENV` 未设为 `production` 或 `prod`，则默认允许匿名总结（仍受 `DEV_ANON_SUMMARIZE_DAILY` 等 IP 日限额与 `check_burst` 约束）。

## 3. 「各种视频」的边界（对运营/测试的诚实描述）

- **覆盖面**取决于 **yt-dlp 对各站点的支持程度**及链接是否仍有效，会随上游更新变化。
- **无法保证**的场景包括但不限于：需强登录且未提供有效 cookies、地区限制、**DRM/加密**、会员专享且鉴权失败等。
- **合规**：产品仅面向有权获取的内容；下载行为须遵守各平台服务条款与用户当地法规。

## 4. 仍属「细节未完全处理好」的方向（后续开发 backlog 参考）

以下不表示「功能未开发」，而是**稳定性、体验与运维**上的持续项：

1. **运行环境**
  - 服务器或本机需安装 **ffmpeg / ffprobe** 并可在 PATH 中被 `yt-dlp` 调用；否则合并音视频、探测音轨等可能失败。
  - 建议固定或定期升级 `**yt-dlp` 版本**，并记录与线上环境一致的依赖说明。
2. **错误与可观测性**
  - 继续把高频失败原因映射为用户可操作的提示（登录、cookies、网络、风控等）。
  - 可按需在关键路径增加结构化日志（注意勿记录完整 URL 或敏感 cookie）。
3. **登录类站点**
  - Cookies 上传流程、格式校验、过期后的引导文案可继续优化。
  - 抖音等国内站的风控变化快，需预留「主方案失败 → 回退」的运维说明。
4. **前端体验**
  - 移动端浏览器下载行为、大文件进度提示、批量串行时的进度与失败汇总等可继续打磨。
  - UI 已偏向浅色商业化落地页，仍可按品牌规范迭代。
5. **测试**
  - 自动化：见 `[tests/test_api_extract_mock.py](../tests/test_api_extract_mock.py)`（mock 外网）；可扩展下载路径的 mock。
  - 手工清单：`[tests/ACCEPTANCE.txt](../tests/ACCEPTANCE.txt)`。

## 5. 与「下载核心」并行的其它能力（避免混淆范围）

以下**独立迭代**，与「解析/下载是否完成」无矛盾：

- **AI 视频总结**、字幕、思维导图、工作区持久化等：见 `[backend/api_summarize.py](../backend/api_summarize.py)`、`[backend/summarizer.py](../backend/summarizer.py)` 等。
- **登录 / OAuth、计费订单骨架**：见 `[backend/auth_routes.py](../backend/auth_routes.py)`、`[backend/billing_routes.py](../backend/billing_routes.py)`。

## 6. 文档维护约定

- 若主链路接口签名、额度策略、**环境变量 / 启动加载顺序**或依赖项有重大变更，请同步更新本页 **§2（含 §2.4）、§4** 及 `[tests/ACCEPTANCE.txt](../tests/ACCEPTANCE.txt)`。
- **已修复缺陷与开发踩坑**的条目化记录见 [`docs/BUGFIX_AND_DEV_NOTES.md`](./BUGFIX_AND_DEV_NOTES.md)；修复可复现 bug 时请在该页追加一条并必要时链回本节。
- 新增站点特化逻辑时，在 `[backend/downloader.py](../backend/downloader.py)` 或独立 parser 模块旁补充简短注释，便于后人区分「通用 yt-dlp」与「个案补丁」。

---

*最后更新：以仓库当前实现为准；具体日期可由提交记录追溯。*