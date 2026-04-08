# 项目发布到 GitHub（Windows / PowerShell）

这份文档用于把当前项目首次发布到 GitHub，并建立后续常规提交流程。

---

## 0. 前置准备

- 已安装 Git（命令行可用：`git --version`）
- 有 GitHub 账号并可登录
- 当前项目路径：`d:\python\PyPreject\aimoiveDownload`

可选（推荐）：

- 安装 GitHub CLI：`gh`（用于命令行创建仓库）

---

## 1. 初始化本地 Git 仓库

在项目根目录打开 PowerShell，执行：

```powershell
cd d:\python\PyPreject\aimoiveDownload
git init
```

---

## 2. 准备 `.gitignore`（防止无关文件进仓库）

创建（或补充）项目根目录 `.gitignore`，建议至少包含：

```gitignore
# Python
__pycache__/
*.pyc
.venv/
venv/

# Runtime/temp
temp/
*.log

# IDE / OS
.idea/
.vscode/
.DS_Store
Thumbs.db

# Local env
.env
```

---

## 3. 首次提交（Initial commit）

```powershell
git add .
git commit -m "Initial commit: douyin parser and downloader web app"
```

如果提交时报身份错误，先配置（把内容改成你自己的）：

```powershell
git config user.name "你的GitHub用户名"
git config user.email "你的GitHub邮箱"
```

然后再次执行 `git commit`。

---

## 4. 在 GitHub 创建远程仓库（两种方式）

### 方式 A：网页创建（最直观）

1. 打开 [GitHub New Repository](https://github.com/new)
2. Repository name 填你想要的名字（例如：`aimoiveDownload`）
3. 选择 Public 或 Private
4. **不要**勾选 `Add a README` / `.gitignore`（避免和本地初始提交冲突）
5. 点击 Create repository

创建后会看到远程地址，例如：

- HTTPS：`https://github.com/<你的用户名>/<仓库名>.git`
- SSH：`git@github.com:<你的用户名>/<仓库名>.git`

### 方式 B：命令行创建（需要 `gh`）

```powershell
gh auth login
gh repo create aimoiveDownload --private --source . --remote origin --push
```

> 这条命令会创建远程仓库、绑定 `origin`，并把当前分支直接 push。

---

## 5. 绑定远程并首次 push（网页方式创建仓库时用）

如果你是用网页创建仓库，执行：

```powershell
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

如果你更喜欢 SSH，把 remote URL 换成 SSH 地址即可。

---

## 6. 之后的日常提交流程

每次改完代码后：

```powershell
git add .
git commit -m "描述这次改动"
git push
```

---

## 7. 常见问题排查

- `remote origin already exists`
  - 先看当前远程：`git remote -v`
  - 覆盖远程地址：`git remote set-url origin <新地址>`
- `failed to push some refs`
  - 先拉取再推送：`git pull --rebase origin main`，解决冲突后 `git push`
- HTTPS push 反复要密码
  - 推荐使用 GitHub Token 或切换 SSH

---

## 8. 建议的首个里程碑

首次 push 后，在 GitHub 仓库里补齐：

- 项目描述（About）
- Topics（如 `fastapi` `douyin` `video-downloader`）
- `README` 增加运行截图和 API 示例

