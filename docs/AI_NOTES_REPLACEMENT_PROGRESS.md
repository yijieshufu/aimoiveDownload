# AI笔记替换需求与开发进度

最后更新：2026-04-13  
范围：将原“AI 总结”工作台替换为“AI笔记”工作台（兼容保留 `/api/summarize` 路径）

## 1. 目标与范围

## 目标
- 参考抖音信息呈现方式，将“摘要型输出”升级为“笔记型输出”。
- 保持现有“解析 -> 下载 -> AI 生成 -> 编辑/导出/问答”闭环可用。
- 在不破坏现有调用的前提下，完成语义迁移（summary -> notes）。

## 范围
- 后端：结果结构、Prompt、工作台编辑接口兼容层。
- 前端：文案与标签、编辑流、主状态命名收口。
- 文档与测试：新增 notes 兼容测试与状态说明。

## 非目标（本阶段不做）
- 立即废弃 `/api/summarize` 路径（仍保留兼容）。
- 支付真实渠道打通（与 AI笔记替换无直接耦合）。

## 2. 需求基线（确认版）

- 产品定位从“视频总结”切到“AI笔记”。
- 右侧工作台以“可读、可复制、可执行”的笔记为核心。
- 保留 SSE 流式生成体验与失败降级轮询。
- 保留思维导图、字幕、问答、Markdown 下载。
- 保持接口兼容策略：**路径不变，语义升级**。

## 3. 关键兼容策略

- API 路径：继续使用 `/api/summarize`。
- 结果字段：新旧字段并存，前端优先读新字段，回退旧字段。
  - 新：`note_sections`、`timeline_notes`、`key_takeaways`
  - 旧：`summary_sections`、`highlights`
- 编辑接口：
  - 新增：`/api/summarize/{task_id}/notes-edit`
  - 保留：`/api/summarize/{task_id}/summary-edit`
  - 双向映射：`note_sections <-> sections`

## 4. 当前开发进度

## 已完成
- 后端 `summarizer` 结果结构升级：
  - 已输出 `note_sections`、`timeline_notes`、`key_takeaways`。
  - 继续输出 `summary_sections`、`highlights` 以兼容旧前端逻辑。
- 后端工作台接口兼容层：
  - 已新增 `notes-edit` 三个接口（GET/PUT/DELETE）。
  - `summary-edit` 仍可继续使用。
- 后端 Prompt 升级：
  - 普通与流式 Prompt 已强调“AI笔记风格”：
    - 短句、可执行、层级清晰、可复制卡片化表达。
- 前端 API 层迁移：
  - 新增 `apiGetNotesEdit/apiSaveNotesEdit/apiDeleteNotesEdit`。
  - 旧 `apiGetSummaryEdit/...` 保留为兼容别名。
- 前端 UI 文案迁移：
  - 关键文案切换为 `AI笔记`、`时间笔记`、`编辑笔记`。
- 前端状态命名收口（进行中收尾）：
  - 核心主状态已引入 notes 命名（`notesTaskId/notesResult/...`）。
  - 仍保留局部 summary 别名以降低一次性改动风险。
- 测试与校验：
  - 新增 `tests/test_notes_compat.py`（notes/summary 映射兼容）。
  - `tests/test_summarizer_postprocess.py` 持续通过。
  - 前端 `npm run build` 持续通过。

## 进行中
- 前端 `App.vue` 全量变量从 `summary*` 最终收口到 `notes*`（正在通过“先别名后删除”方式推进）。

## 待完成
- 删除 `App.vue` 内 summary 兼容别名，完成纯 notes 命名。
- 文档全量替换（README 与 docs 中“总结/摘要”历史表述统一补充“AI笔记兼容期说明”）。
- 视前端稳定性决定是否逐步下线 `summary-edit` 前端调用入口（后端仍可保留一段时间）。

## 5. 验收标准（本轮）

- 用户从界面感知到的是“AI笔记”而不是“AI总结”。
- 流式生成、轮询降级、字幕、导图、问答均可正常使用。
- 兼容期间历史任务不因字段变更无法读取。
- 前后端构建/测试通过，不引入回归故障。

## 6. 变更记录（本轮）

- 后端：
  - `backend/summarizer.py`
  - `backend/api_workspace.py`
  - `backend/workspace_store.py`
  - `backend/api_summarize.py`（补充接口说明）
- 前端：
  - `frontend/src/App.vue`
  - `frontend/src/components/VideoUrlBar.vue`
  - `frontend/src/api/workspace.js`
- 测试：
  - `tests/test_notes_compat.py`

## 7. 后续建议

- 短期：保持接口兼容，优先完成前端变量名最终收口。
- 中期：将 `note_sections` 作为唯一主结构，对外文档明确“旧字段将进入弃用期”。
- 长期：在确认无旧客户端依赖后，再评估是否引入 `/api/notes` 新路径（可选）。
