# Video Downloader - 极速视频下载工具

基于 yt-dlp 的 Web 视频下载器，Vue 3 + FastAPI，支持多平台解析、抖音无水印、AI 视频笔记与工作台（思维导图、字幕等）。

## 技术栈

- **前端**：Vue 3、Vite、Tailwind CSS
- **后端**：Python、FastAPI
- **数据**：SQLite（默认 `backend/data/app.db`，可从旧版 `temp/workspace.db` 自动迁移）
- **核心**：yt-dlp

## 项目结构

```
aimoiveDownload/
├── backend/                 # FastAPI 应用
│   ├── main.py              # 应用入口（路由装配）
│   ├── database.py          # SQLite 统一入口与初始化
│   ├── api_video.py         # 解析 / 下载 / 封面代理等
│   ├── api_summarize.py     # AI 笔记与字幕相关 API（兼容 summarize 路径）
│   ├── api_workspace.py     # UI 标签、思维导图持久化等
│   ├── auth_routes.py       # OAuth 与 /api/me
│   ├── billing_routes.py    # 微信 / 支付宝订单骨架
│   ├── downloader.py        # yt-dlp 封装
│   ├── env_bootstrap.py     # 启动时加载根目录与 backend/.env
│   ├── .env.example         # 环境变量说明
│   └── data/                # 运行时生成 app.db（勿提交敏感数据）
├── frontend/                # Vue 工程（开发）+ dist（构建产物）
│   ├── src/
│   │   ├── api/             # 按域拆分的 API 客户端
│   │   └── components/
│   ├── package.json
│   └── vite.config.js
├── requirements.txt
└── README.md
```

## 环境要求

- **Python 3.10 或更高**（本仓库按 3.10+ 开发与测试；3.9 及以下未做兼容承诺）
- Node.js 18+
- pip、npm

仓库根目录的 `.python-version` 为 **3.10**（便于 pyenv / asdf 自动切换）。若你已安装 3.11 / 3.12，可自行把该文件改成对应主版本号。

### 从旧版 Python 迁到 3.10+（简要）

1. 从 [python.org](https://www.python.org/downloads/) 或使用 `winget install Python.Python.3.12` 等安装 **3.10+**，确认终端里 `python --version` 已是新版本。
2. 在项目根目录**新建虚拟环境**（不要用旧 3.7 的 venv 目录）：
  `python -m venv .venv` → 激活后执行 `pip install -r requirements.txt`。
3. 用该环境启动 `uvicorn`（与下方「快速开始」一致）。

## 快速开始

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量（可选）

参考 [backend/.env.example](backend/.env.example)，在项目根或 `backend` 下创建 `.env` 并导出变量，或在启动前手动 `set` / `export`。

启动时 `backend/main` 会自动加载 **项目根 `.env`** 与 `**backend/.env**`（不覆盖已在 shell 里导出的变量）。**本地开发**在未声明 `ENVIRONMENT=production` 时，未登录也可使用 AI 总结（按 IP 日限额，详见 [docs/PRODUCT_STATUS.md](docs/PRODUCT_STATUS.md) §2.4）。**上线请务必**设置 `ENVIRONMENT=production` 或 `DEV_ALLOW_ANONYMOUS_AI=0`。

### 3. 启动后端

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8003
```

### 4. 启动前端开发（含 Vite 代理到后端）

**若出现 `ERR_CONNECTION_REFUSED` 或 5173 无法访问，说明本机没有跑 Vite，需要先执行下方命令。**

**推荐：项目根目录一键启动（后端 8003 + 前端 5173）**

```bash
# 在项目根目录 aimoiveDownload/ 下执行（会安装 concurrently 并同时起 uvicorn 与 vite）
npm install
npm run dev
```

浏览器打开：**[http://localhost:5173/frontend/](http://localhost:5173/frontend/)**（注意路径含 `/frontend/`，与 `vite.config.js` 里 `base` 一致）。

Windows 也可双击根目录 `**dev.cmd`**（等价于上述命令）。
启动前会自动释放旧的 `5173 / 8003 / 8001` 监听，避免页面继续连到历史残留进程。

**仅启动前端（需另开终端先执行第 3 步启动后端，否则 /api 会失败）**

```bash
cd frontend
npm install
npm run dev
```

同上访问 **[http://localhost:5173/frontend/](http://localhost:5173/frontend/)**，API 通过 Vite 代理到 `http://127.0.0.1:8003`。

### 5. 生产 / 一体化访问（仅后端 + 构建产物）

在 `frontend` 目录执行 `npm run build`，然后仅用 uvicorn 启动后端，访问：

`http://localhost:8003/frontend/index.html`

### 6. 开发约定（修复后自动重启）

为避免“修好了但本地没生效”的情况，约定如下：

- 每次修复前端/后端 Bug 后，默认执行一次项目重启验证。
- 优先使用项目根目录一键启动：`npm run dev`（同时拉起后端 8003 + 前端 5173）。
- 启动前会自动清理旧的 5173/8003/8001 监听，避免页面连到历史残留进程。
- 提交修复结果时，应明确告知当前可访问地址：`http://localhost:5173/frontend/`。

## 主要 API

- `POST /api/extract`：解析视频信息与格式列表
- `POST /api/douyin/parse`：抖音专用解析
- `GET /api/download`：触发下载
- `GET /api/download/file`：下载已生成的本地文件
- `POST /api/summarize`：创建 AI 笔记任务（兼容旧路径）
- 更多路由见 `backend/api_*.py` 与 `auth_routes.py`、`billing_routes.py`

## 近期更新（沉淀）

### 1) Windows 下 ASR 音频下载 `[Errno 22] Invalid argument` 彻底加固

问题现象：AI 总结在需要 ASR 时，下载音频阶段报 `ASR 音频下载失败: Unable to download video: [Errno 22] Invalid argument`。

已采取的修复（核心思路：**避开 Windows 路径/命令行限制 + 尽量绕过 yt-dlp 分片临时文件**）：

- **B 站优先走 `fnval=0` 的渐进式 MP4 直链**（urllib 下载），避免 DASH 分片/合并链路触发 EINVAL。
- **B 站多段 `durl`**：逐段下载后用 **ffmpeg concat** 合并，仍不依赖 yt-dlp。
- **DASH 音频 URL 过长**（签名 query 极长）：不再 `ffmpeg -i <超长URL>`（会触发 Win32 `[Errno 22]`），改为 **先 urllib 落盘为本地 `.m4s`，再让 ffmpeg 读取本地文件封装为 `.m4a`**。
- **统一短路径临时目录**：ASR/直链下载输出都写入同一短路径根目录，减少 Windows 下文件名/临时目录问题。
- **ASR 下载的 yt-dlp 回退链路**：固定 `TMP/TEMP` 指向短路径目录、显式 `paths.temp` 子目录、降低分片并发等，降低概率性失败。

相关代码：

- `backend/summarizer.py`：B 站直链/ffmpeg 逻辑与 ASR 下载链路
- `backend/downloader.py`：Windows 路径短化工具

### 2) 思维导图从“编辑器”收敛为“轻编辑查看器”

目标：减少工具栏按钮与认知负担，保留最常用的轻编辑能力。

保留：

- 视图：适应画布、缩放、全屏
- 轻编辑：添加子节点、删除节点、双击重命名（弱化为低干扰）
- 导出：SVG、PNG（4K+）
- 右键菜单：添加子节点/重命名/删除

移除/停用：

- 布局切换、多套布局、自动排版
- 一级分支折叠体系（以及相关合并/裁剪逻辑）
- 添加兄弟节点入口、编辑器化快捷键（F2/Del）与时间轴跳转交互

相关代码：

- `frontend/src/components/MindmapFlow.vue`
- 已清理：`frontend/src/composables/useMindmapFold.js`

### 3) 问答失败提示可自救（Failed to fetch / 任务失效）

现象：前端问答出现 `Failed to fetch` 时，用户难以判断是后端未启动、后端刚重启、还是任务失效。

改进：对问答错误做更清晰的“可行动”提示：

- `Failed to fetch`：提示检查后端 8003 是否可达、是否刚重启，并引导重新总结再问答。
- `任务不存在`：提示后端重启会清空内存任务，需要重新总结。

相关代码：

- `frontend/src/App.vue`：`humanizeQaError`

### 4) 思维导图渲染与交互修复（黑影/右键/同级节点）

问题现象：
- 导出 PNG/SVG 或页面展示时，导图边线/节点区域出现黑色伪影（黑块、黑三角）。
- 部分场景下右键菜单不稳定。
- 需要“添加同级节点”能力。

已完成：
- 修复导图黑影：边线渲染改为更稳妥的纯描边（显式 `fill:none`），并清理易触发黑块伪影的样式组合。
- 加强右键菜单触发：节点右键与画布右键都可稳定弹出菜单（画布右键默认作用于 root）。
- 新增“添加同级节点”：
  - 工具栏增加“添加同级节点”按钮
  - 右键菜单增加“添加同级节点”（根节点场景自动禁用）

相关代码：
- `frontend/src/components/MindmapFlow.vue`

### 5) 摘要编辑体验升级（单 Markdown 文本框）

目标：把“概述 / 内容大纲 / 核心知识点”从多文本框编辑改为统一 Markdown 编辑。

已完成：
- 编辑态：摘要页使用**单个 Markdown 文本框**编辑（统一输入）。
- 展示态：非编辑时直接按 Markdown 风格渲染（标题/列表语义保留）。
- 自动保存仍保留：输入后解析回结构化字段并走现有保存接口。

相关代码：
- `frontend/src/App.vue`（Markdown 文本与渲染/解析逻辑）
- `frontend/src/api/workspace.js`（沿用现有 summary-edit 存储接口）

### 6) 摘要页信息分层优化

已完成：
- 在“摘要”标签页中移除底部内嵌思维导图区块，避免信息重复与页面过长。
- 思维导图仅在“思维导图”标签页显示，交互更聚焦。

相关代码：
- `frontend/src/App.vue`

### 7) 摘要工作台可读性优化（Markdown/标签/字幕稿/时间轴）

问题现象：摘要工作台多个区域字体偏小，Markdown 层级不够明显，长文本阅读成本高。

已完成：
- **Markdown 渲染分层增强**：为摘要渲染容器增加 `summary-markdown-prose`，明确区分 `h1 / h2 / p / li / strong`（一级标题、二级标题、正文、加粗重点）。
- **摘要区全局字号优化**：提升顶部标题、副标题、进度状态文案、操作按钮（编辑/复制/恢复）与功能标签（摘要/时间轴/字幕稿/思维导图/问答）的字号与内边距。
- **字幕稿可读性优化**：来源信息、操作按钮、字幕正文（含回退 `pre` 文本）统一升档，并增加行高。
- **时间轴可读性优化**：时间戳与正文字号增大，行距与每行留白优化，降低阅读疲劳。

相关代码：
- `frontend/src/App.vue`
- `frontend/src/style.css`

## 注意事项

- 本工具仅用于个人学习和研究目的，请遵守法律法规与平台服务条款。
- 生产环境请修改 `AUTH_SECRET_KEY` 并限制 CORS 来源；并设置 `ENVIRONMENT=production`（或 `DEV_ALLOW_ANONYMOUS_AI=0`），避免匿名滥用 AI 总结接口。

## 许可证

MIT License
