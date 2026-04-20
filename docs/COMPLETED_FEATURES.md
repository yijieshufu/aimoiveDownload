# aimoiveDownload 已完成功能清单

最后更新：2026-04-13  
适用版本：当前工作区代码（未区分分支发布版本）

## 1. 用户可见功能（前端）

- 视频链接输入与提取：
  - 支持粘贴普通 URL、文本中提取首个 URL、短链场景（含抖音短链识别）。
  - 可解析并展示标题、封面、作者、时长、播放量、可下载格式列表。
- 视频下载：
  - 支持按解析出的 `format_id` 发起下载。
  - 支持下载完成后的文件直链拉取（浏览器直接保存）。
  - 4K/超高清下载已接入 Pro 限制提示（非 Pro 会触发升级引导）。
- AI 笔记工作台（兼容 `/api/summarize` 路径）：
  - 支持创建笔记任务，并以 SSE 流式显示生成过程与进度。
  - 流式失败时自动降级轮询，并提供“重试流式 / 改用轮询”。
  - 输出结果包含：摘要、时间轴高亮、字幕稿、思维导图、问答区。
- 笔记编辑与导出：
  - 笔记区支持单 Markdown 文本框编辑（概述/大纲/要点统一编辑）。
  - 支持自动保存笔记编辑版本、恢复 AI 原文、复制全文/分区。
  - 支持下载 Markdown 结果文件。
- 字幕能力：
  - 支持字幕片段展示与滚动阅读。
  - 支持下载 `SRT / VTT / TXT` 字幕文件。
- 思维导图：
  - 支持查看、拖拽、重命名、添加子节点、添加同级节点、删除节点。
  - 支持右键菜单操作、适应画布、缩放、全屏。
  - 支持导出 `SVG` 与 4K+ `PNG`。
  - 支持导图自动保存与回读。
- 问答（QA）：
  - 支持基于当前笔记任务的多轮问答。
  - 支持对话历史展示与滚动。
  - 针对常见故障（如 `Failed to fetch`、任务失效）有可操作提示文案。
- 账号与升级弹窗：
  - 支持 GitHub / Google / 微信 OAuth 登录入口。
  - 支持读取当前用户与套餐状态，并展示使用额度提示。
  - 支持升级弹窗内创建订单与开发态 mock 支付闭环。

## 2. 后端 API 能力（已落地）

- 视频解析与下载（`api_video`）：
  - `POST /api/extract`
  - `POST /api/douyin/parse`
  - `GET /api/download`
  - `GET /api/download/file`
  - `GET /api/thumbnail`
  - `GET /api/cookies/status`
  - `POST /api/cookies/upload`
- AI 笔记生成（`api_summarize`，兼容路径保留）：
  - `POST /api/summarize`
  - `GET /api/summarize/{task_id}`
  - `GET /api/summarize/{task_id}/stream`
  - `POST /api/summarize/{task_id}/qa`
  - `POST /api/summarize/{task_id}/chat`
  - `POST /api/summarize/{task_id}/translate`
  - `GET /api/summarize/{task_id}/subtitles`
  - `GET /api/summarize/{task_id}/subtitles/download`
- 工作台持久化（`api_workspace`）：
  - `GET/PUT /api/ui/tabs`
  - `GET/PUT /api/summarize/{task_id}/mindmap`
  - `GET/PUT/DELETE /api/summarize/{task_id}/notes-edit`
  - `GET/PUT/DELETE /api/summarize/{task_id}/summary-edit`
- 认证（`auth_routes`）：
  - `GET /api/auth/login/{provider}`
  - `GET /api/auth/callback/{provider}`
  - `POST /api/auth/logout`
  - `GET /api/me`

## 3. 数据与工程能力

- SQLite 已作为统一存储入口（初始化在应用启动时执行）。
- 前后端开发一键启动已可用（根目录 `npm run dev` 或 `dev.cmd`）。
- 前端已配置 Vite 开发代理与 `/frontend/` 基础路径。
- 后端已挂载静态资源目录，可直接托管前端构建产物。

## 4. 已有测试覆盖

- `tests/test_summarizer_postprocess.py` 已覆盖：
  - 一级导图节点与章节时间/标题对齐逻辑。
  - 总结后处理增强逻辑（主旨/要点/证据子节点注入）。

## 5. 明确为“未完成/占位”的部分

- 支付“真实下单与回调验签”仍是骨架：
  - 微信支付下单接口仍为 TODO，占位返回 `code_url/pay_url`。
  - 支付宝下单接口仍为 TODO。
  - 微信/支付宝异步通知路由目前为占位返回。
- 这部分当前可用于本地流程联调（通过 mock 标记已支付），不等同于生产可用支付链路。

## 6. 当前项目定位（按现状）

本项目目前已形成“可用的端到端闭环”：

1) 解析视频 -> 2) 选择格式下载 -> 3) AI 生成笔记 -> 4) 在工作台编辑笔记/查看字幕/编辑导图/问答 -> 5) 数据持久化保存。  
其中支付的“真实渠道接入”是主要未完项，其余核心体验已可开发和演示。
