# docs 文档导航

本目录用于沉淀项目文档，按“当前状态 / 需求基线 / 故障记录 / 发布指南”分层维护。

## 推荐阅读顺序（新同学）

1. [COMPLETED_FEATURES.md](./COMPLETED_FEATURES.md)  
   看当前已经可用的功能闭环（偏产品视角）。
2. [PRODUCT_STATUS.md](./PRODUCT_STATUS.md)  
   看技术现状、边界、环境策略和运维注意事项（偏技术实现视角）。
3. [BUGFIX_AND_DEV_NOTES.md](./BUGFIX_AND_DEV_NOTES.md)  
   看历史故障、根因与修复落点，减少重复踩坑。
4. [AI_NOTES_REPLACEMENT_PROGRESS.md](./AI_NOTES_REPLACEMENT_PROGRESS.md)  
   看“AI 总结 -> AI笔记”替换需求基线与开发进度。

## 文档清单

- [COMPLETED_FEATURES.md](./COMPLETED_FEATURES.md)  
  当前版本“已完成能力”清单（面向功能盘点与交付说明）。
- [PRODUCT_STATUS.md](./PRODUCT_STATUS.md)  
  产品与技术现状、限制边界、环境变量策略说明。
- [BUGFIX_AND_DEV_NOTES.md](./BUGFIX_AND_DEV_NOTES.md)  
  已修复问题与开发备忘（按现象/根因/代码落点沉淀）。
- [ai-video-summary-requirements.md](./ai-video-summary-requirements.md)  
  AI 总结工作台需求基线文档（历史需求确认依据）。
- [PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md)  
  早期阶段总结（保留用于历史回顾，不作为唯一现状依据）。
- [AI_NOTES_REPLACEMENT_PROGRESS.md](./AI_NOTES_REPLACEMENT_PROGRESS.md)  
  AI笔记替换专项文档（需求、兼容策略、进度与待办）。
- [GITHUB_PUBLISH_GUIDE.md](./GITHUB_PUBLISH_GUIDE.md)  
  GitHub 发布与日常提交流程指南。

## 维护约定

- 变更用户可见能力时：优先更新 `COMPLETED_FEATURES.md`。
- 变更技术策略/环境变量/边界行为时：同步更新 `PRODUCT_STATUS.md`。
- 修复可复现 bug 时：追加到 `BUGFIX_AND_DEV_NOTES.md`，必要时回链到现状文档。
- 若文档内容出现重复，保留一份“主文档”，其余文档加跳转说明，避免多处冲突。
