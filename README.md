[README.md](https://github.com/user-attachments/files/27547782/README.md)
wo xi# ai_chat_web

类 ChatGPT 的 Web 界面：**FastAPI 后端** + **React（Vite）前端**，数据与登录会话复用项目 `ai实战/auth_db.py`（MySQL）。

---

## 环境要求

- Python 3.10+
- Node.js 18+（建议 LTS）
- 已可用的 MySQL，并配置与 `auth_db` 一致的环境变量（如 `MYSQL_HOST`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DATABASE` 等）
- AI 对话需配置 `DEEPSEEK_API_KEY`

---

## 启动方式

### 1. 后端（FastAPI）
lsof -ti:8765 | xargs kill -9
```bash
cd /Users/yang/原电脑代码/py_project01/ai_chat_web/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8765
```

保持该终端运行。Windows 下激活虚拟环境请使用：`.venv\Scripts\activate`。

### 2. 前端（Vite 开发服务器）

新开一个终端：

```bash
cd /Users/yang/原电脑代码/py_project01/ai_chat_web/frontend
npm install
npm run dev
```

要给朋友用完整网页（前端 + 接口代理）：
ngrok http 5173

cloudflared tunnel --url http://localhost:5173
浏览器打开终端里提示的地址（一般为 `http://localhost:5173`）。

开发时 Vite 会把 `/api` **代理**到本机 `8765`，因此需**先启动后端**再启动前端。

### 3. 生产构建（可选）

```bash
cd /Users/yang/原电脑代码/py_project01/ai_chat_web/frontend
npm run build
```

产物在 `frontend/dist/`，可由 Nginx 等托管；并把 `/api` 反向代理到 FastAPI。若前后端不同域，需在 `backend/main.py` 的 CORS 中增加你的前端域名。

---

## 架构原理（简要）

1. 浏览器只运行前端页面；登录后把会话 token 存在 `localStorage`，请求头带 `Authorization: Bearer <token>`。
2. 后端 `deps.py` 用 `auth_db.validate_session` 校验 token，得到 `user_id`，再执行业务。
3. AI 回复通过 `POST /api/ai/stream` 以 **SSE（`text/event-stream`）** 流式返回；前端 `src/api.ts` 解析 `data:` 行。
4. 好友与私聊、多会话聊天状态均走 `auth_db` 的 MySQL 表，与旧版 Streamlit 共用同一套数据。

---

## 目录里各文件的作用与原理

以下为**本仓库内**手写或配置相关文件；`node_modules/`、`.venv/`、`dist/`、`package-lock.json` 等为安装或构建生成，不列细节。

### 后端 `backend/`

| 文件 | 作用 | 原理简述 |
|------|------|----------|
| `main.py` | 应用入口 | 创建 FastAPI 应用；配置 CORS；挂载路由前缀 `/api/auth`、`/api/ai`、`/api/friends`；`import auth_db` 时会执行 `ai实战/auth_db.py` 中的建表等初始化。 |
| `deps.py` | 鉴权依赖 | 从 `Authorization: Bearer` 取 token，调用 `auth_db.validate_session` 得到 `user_id`；失败返回 401。需登录的路由通过 `Depends(get_current_user_id)` 注入当前用户。 |
| `requirements.txt` | Python 依赖 | 供 `pip install -r requirements.txt` 安装 FastAPI、Uvicorn、OpenAI SDK、PyMySQL 等。 |
| `routers/__init__.py` | 包标识 | 使 `routers` 成为 Python 包。 |
| `routers/auth.py` | 认证相关 API | 登录（校验密码、`create_session` 返回 token）、注册、登出（`revoke_session`）、`GET /me` 返回当前用户 id 与用户名。 |
| `routers/ai.py` | AI 与多会话 | `GET/PUT` 读写 `load_chat_state` / `save_chat_state`；新建会话、删除会话；`POST /stream` 写入用户消息、调用 DeepSeek 流式接口、**SSE 推送**、结束后保存状态。 |
| `routers/friends.py` | 好友与私聊 | 转发到 `auth_db`：好友列表、入站申请、发申请、接受/拒绝、拉取与发送私聊消息。 |

**路径说明**：`auth_db` 位于 `py_project01/ai实战/`，`main.py` 通过 `sys.path` 加入该目录后 `import auth_db`。

### 前端 `frontend/`

| 文件 | 作用 | 原理简述 |
|------|------|----------|
| `package.json` | npm 配置 | 定义脚本 `dev` / `build` / `preview` 以及 React、Vite、TypeScript、Tailwind 等依赖。 |
| `vite.config.ts` | Vite 配置 | 开发服务器端口；**将 `/api` 代理到 `http://127.0.0.1:8765`**，前端用相对路径即可访问后端。 |
| `index.html` | HTML 入口 | 提供 `#root` 挂载点，加载 `src/main.tsx`。 |
| `tailwind.config.js` | Tailwind 主题 | 扩展颜色（如 `chat-bg`、`chat-sidebar`）等，用于深色聊天布局。 |
| `postcss.config.js` | PostCSS | 接入 Tailwind 与 Autoprefixer。 |
| `tsconfig.json` | TypeScript（应用） | 编译选项、包含 `src/`。 |
| `tsconfig.node.json` | TypeScript（Node） | 用于 `vite.config.ts` 等 Node 侧配置。 |
| `src/main.tsx` | 前端入口 | `ReactDOM.createRoot` 渲染根组件 `App`，引入全局样式。 |
| `src/index.css` | 全局样式 | `@tailwind` 指令与基础布局（全屏高度、滚动条等）。 |
| `src/vite-env.d.ts` | 类型声明 | 引用 `vite/client`，便于 TS 识别 Vite 环境。 |
| `src/api.ts` | HTTP 封装 | 读写 `localStorage` 中的 token；`apiJson` 统一带鉴权；`streamAiChat` 读取 SSE 流并解析 `data:` JSON 与 `[DONE]`。 |
| `src/App.tsx` | 主界面 | 登录/注册页；主界面侧栏（会话、好友、新建对话）、主区（AI 或好友私聊）、底部输入；AI 流式展示与好友轮询刷新等。 |

---

## 数据流小结

1. 登录 → 后端返回 token → 前端存储，后续请求携带 Bearer。
2. AI 会话列表与内容 → `GET /api/ai/state`；发送 → `POST /api/ai/stream` → 流式结束后再 `GET /api/ai/state` 同步。
3. 好友与私聊 → `/api/friends/*`，底层均为 `auth_db` 的 SQL。

---

## 与旧版 Streamlit 的关系

原 `ai实战/0.3_partner_1.py`（Streamlit）可保留作对照；新界面使用本目录下的 `backend` + `frontend`，不再依赖 Streamlit 运行时。



users
用户主表，存账号基础信息（如用户名、密码哈希、创建时间等）。其他大部分用户相关表都通过 user_id 关联它。

user_profiles
用户扩展资料表，主要放个人资料（目前你项目里重点是头像 avatar_data），和 users 一对一。

user_phones
用户手机号绑定表，记录某个用户绑定的手机号（用于短信注册/验证关联）。

sms_verify_codes
短信验证码流水表，保存手机号、验证码、发送时间、过期时间、是否已使用等，用于校验注册验证码和做冷却控制。

friend_requests
好友申请表，记录“谁向谁发起申请”、状态（待处理/已同意/已拒绝）、时间等。

friendships
好友关系表，表示双方已经成为好友。私聊、好友列表通常基于这张表查询。

friend_aliases
好友备注表，存“我给某个好友起的备注名”。
典型是 (user_id, friend_id, alias)，所以 A 给 B 的备注和 B 给 A 的备注可以不同。

friend_messages
好友私聊消息表，存私聊内容、发送方、接收方、时间。右侧好友聊天窗口的数据来源就是它。

user_chat_state
AI 对话状态表，保存用户的会话状态（如聊天历史 JSON、当前会话 id 等），用于你刷新后恢复聊天记录。

browser_sessions
登录会话表（token/session 持久化），用于“登录态校验、退出登录失效”等。Authorization: Bearer ... 背后通常会查这张表。


## 有关于.venv 虚拟环境的配置
.venv 是 Python 虚拟环境（virtual environment） 的目录，通常由 python -m venv .venv 创建。
## 为什么要用？
隔离依赖：这个项目里装的 fastapi、uvicorn、pymysql 等只装在 .venv 里，不会污染系统 Python，也不会和别的项目冲突。
版本固定：配合 requirements.txt，换机器可以 pip install -r requirements.txt 在虚拟环境里复现同一套版本。
可删可重建：.venv 删了再建一次即可，不影响业务代码。
## 里面大概有什么？
bin/（Windows 是 Scripts/）：python、pip、uvicorn 等可执行文件
lib/：下载的第三方包源码
pyvenv.cfg：指向创建该环境时用的基础 Python 等配置
## 需要提交到 Git 吗？
一般不要提交。体积大、且每人机器路径可能不同。仓库里只保留 requirements.txt（或 pyproject.toml），别人自己 python -m venv .venv 再装依赖。
## 和你项目的关系
在 ai_chat_web/backend/ 下的 .venv 表示：后端依赖装在这个虚拟环境里。
用 IDE 或终端跑后端时，应 选中这个 .venv 里的 Python 解释器，这样 import fastapi 等才能被正确解析，红线也会少很多。

一句话：.venv = 这个项目专用的 Python + 已安装包，用来隔离和复现环境。
