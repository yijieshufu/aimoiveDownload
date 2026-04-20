# GitHub 提交与稳定推送指南（当前项目）

这份文档用于沉淀当前仓库的**日常 commit / push 标准动作**，目标是：  
减少漏提、减少脏文件、网络波动时也能稳定推送。

---

## 1. 日常提交标准流程（推荐）

在项目根目录执行：

```bash
git status --short
git add <你确认要提交的文件>
git commit -m "feat/fix/docs: 本次改动目的"
```

建议：

- 优先按文件精确 `git add`，避免 `git add .` 把无关变更一起提交。
- 提交信息尽量写“为什么改”，不是只写“改了什么”。
- 提交前至少看一次：`git diff --staged`。

---

## 2. 推送到 GitHub（稳定方案）

本仓库已提供脚本：`scripts/git-push-proxy.sh`。  
默认走本机代理 `127.0.0.1:7897`（适合网络不稳场景）。

```bash
bash scripts/git-push-proxy.sh
```

自定义代理端口：

```bash
PROXY_HOST=127.0.0.1 PROXY_PORT=7899 bash scripts/git-push-proxy.sh
```

说明：该脚本仅对本次命令注入 `HTTP_PROXY/HTTPS_PROXY`，不会改全局 Git 配置。

---

## 3. 快速检查清单（每次提交前 30 秒）

- `git status --short`：确认仅包含预期文件
- `git diff --staged`：确认已暂存内容正确
- `git branch --show-current`：确认在正确分支
- `git log --oneline -n 3`：保持提交风格一致

---

## 4. 常见问题与处理

- `Failed to connect github.com:443`
  - 直接改用：`bash scripts/git-push-proxy.sh`
- `failed to push some refs`
  - 先同步远端：`git pull --rebase origin <当前分支>`，处理冲突后再推送
- 不小心带上本地日志或临时文件
  - 先 `git reset <文件>` 取消暂存，再补充 `.gitignore` 规则

---

## 5. 本仓库忽略规则（与提交流程相关）

当前已忽略关键本地噪音文件：

- `.codex-logs/`
- `node_modules/`
- `temp/`
- `__pycache__/`
- `.venv/` / `venv/`

如新增本地工具目录，记得同步更新根目录 `.gitignore`，避免污染提交历史。

