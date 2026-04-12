# Video Downloader - 极速视频下载工具

基于 yt-dlp 的 Web 视频下载器，Vue 3 + FastAPI，支持多平台解析、抖音无水印、AI 视频总结与工作台（思维导图、字幕等）。

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
│   ├── api_summarize.py     # AI 总结与字幕相关 API
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

启动时 `backend/main` 会自动加载 **项目根 `.env`** 与 **`backend/.env`**（不覆盖已在 shell 里导出的变量）。**本地开发**在未声明 `ENVIRONMENT=production` 时，未登录也可使用 AI 总结（按 IP 日限额，详见 [docs/PRODUCT_STATUS.md](docs/PRODUCT_STATUS.md) §2.4）。**上线请务必**设置 `ENVIRONMENT=production` 或 `DEV_ALLOW_ANONYMOUS_AI=0`。

### 3. 启动后端

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

### 4. 安装前端依赖并开发调试

```bash
cd frontend
npm install
npm run dev
```

浏览器访问开发服务器提示的地址（默认 `http://localhost:5173`），API 会通过 Vite 代理到 `http://127.0.0.1:8001`。

### 5. 生产 / 一体化访问（仅后端 + 构建产物）

在 `frontend` 目录执行 `npm run build`，然后仅用 uvicorn 启动后端，访问：

`http://localhost:8001/frontend/index.html`

## 主要 API

- `POST /api/extract`：解析视频信息与格式列表
- `POST /api/douyin/parse`：抖音专用解析
- `GET /api/download`：触发下载
- `GET /api/download/file`：下载已生成的本地文件
- `POST /api/summarize`：创建 AI 总结任务
- 更多路由见 `backend/api_*.py` 与 `auth_routes.py`、`billing_routes.py`

## 注意事项

- 本工具仅用于个人学习和研究目的，请遵守法律法规与平台服务条款。
- 生产环境请修改 `AUTH_SECRET_KEY` 并限制 CORS 来源；并设置 `ENVIRONMENT=production`（或 `DEV_ALLOW_ANONYMOUS_AI=0`），避免匿名滥用 AI 总结接口。

## 许可证

MIT License
