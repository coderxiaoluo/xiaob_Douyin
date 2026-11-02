# 小波 · 抖音采集工作台

本地运行的抖音数据采集工具，带一套完整的 Web 界面。抓取、预览、勾选、导出全在浏览器里完成，不用记命令行参数。

- 搜索：按关键词抓作品 / 用户 / 直播间
- 用户：主页作品、资料、粉丝、关注
- 作品：详情、评论区（含多级回复）、多链接批量
- 直播：只读监听弹幕、礼物、进场、点赞，查看 PK 榜与贡献榜
- 导出：Excel + 封面图 / 视频 / 图片，落盘到 `datas/`

> 所有写操作（发评论、私信、发布）默认不执行，只生成计划与草稿，需人工确认。

---

## 环境要求

| 项 | 要求 |
| --- | --- |
| Python | 3.10 及以上（3.14 也支持） |
| 系统 | Windows / macOS / Linux |
| 网络 | 需要能访问 `douyin.com`，必要时配代理 |
| 浏览器 | 新版 Chrome / Edge |

## 快速开始

### 方式一：Windows 一键启动（推荐）

双击 `start_web.bat`。脚本会自动：

1. 检查 Python 是否可用
2. `.env` 不存在时从 `.env.example` 复制一份
3. 释放被占用的端口
4. 打开浏览器并启动服务

PowerShell 用户可用 `start_web.ps1`，逻辑相同。

### 方式二：手动启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 准备配置
copy .env.example .env        # macOS / Linux 用 cp

# 3. 启动
python -m webapp.server
```

浏览器打开 <http://127.0.0.1:19527/>

改端口：设置环境变量 `DY_WEB_PORT`，例如

```powershell
$env:DY_WEB_PORT = "8080"; python -m webapp.server
```

> 依赖安装注意：`blackboxprotobuf` 声明依赖 `protobuf==3.10`，会把 protobuf 降级，导致 `import runtime_version` 报错。`requirements.txt` 里已固定 `protobuf>=5.27`，装完确认一下版本没被降下去即可。

---

## 配置登录凭证

没有 Cookie 只能看到公开的少量数据，且大概率被风控。两种配置方式任选：

### A. 扫码登录（最省事）

进入「会话配置」页 → 点「生成二维码」→ 用抖音 App 扫码确认。成功后 Cookie 自动写入 `.env`，状态卡片的 `Cookie / sessionid / ttwid` 会变为已就绪。

### B. 从浏览器复制

1. Chrome 打开 `douyin.com` 并登录
2. `F12` → Network → 随便点一个接口 → 复制 Request URL 和 Request Headers
3. 粘贴到「会话配置」的「抓包原文」框 → 点「解析抓包」→「保存并重载会话」

只贴 Cookie 也可以，但要记得补齐浏览器指纹（UA、screen、cpu、memory 等），与复制 Cookie 的那台浏览器保持一致，能明显降低风控概率。

### .env 字段

| 变量 | 说明 |
| --- | --- |
| `DY_COOKIES` | 主接口 Cookie |
| `DY_LIVE_COOKIES` | 直播弹幕 Cookie |
| `DY_PROXY` | 代理，如 `http://127.0.0.1:7890`，留空直连 |
| `DY_TICKET` / `DY_TS_SIGN` / `DY_CLIENT_CERT` / `DY_PRIVATE_KEY` | 扫码后自动写入，私信签名用 |
| `DY_DTRAIT_BLOB` / `DY_DTRAIT_PROFILE` | 写接口设备特征，留空用包内默认档案 |

> `.env` 已在 `.gitignore` 中，**不要提交到仓库**。

---

## 界面怎么用

左侧栏按分组排列：搜索 / 直播 / 用户 / 作品 / 我的，另有「本地档案」和折叠的「Agent / 会话」。

### 采集流程

1. 选左侧模块，例如「搜作品」
2. 填条件：关键词、数量、排序；展开的次级条件可筛发布时间、时长、类型
3. 点「扫描 / 拉取」，等待进度条走完
4. 下方出现卡片预览，勾选需要的条目（可全选、也可在结果内搜标题/作者）
5. 点「保存所选」；导出方式在「导出选项」里选：
   - `Excel + 媒体`（默认）
   - `仅 Excel / JSON`
   - `仅媒体`
6. 完成后点右上角下载链接，或到「本地档案」里下载历史文件

评论区模块额外支持结果内筛选：仅意向、仅认证、按属地、性别、关键词过滤。

### 直播监听

左侧「直播间」→ 粘贴直播间链接或房间号 →「开始监听」。中间是实时消息流，可按弹幕/礼物/进场/点赞/PK 过滤；右侧是 PK 榜和贡献榜；「导出 Excel」保存本次记录。

### Agent 配置

「Agent 配置」页只做策略保存，不会真的自动发内容。流程是：

1. 填品类、日产量、承接方式、今日目标
2. 在「能力开关」里打开需要的能力（默认全关）
3. 「预览计划」→ 生成只读步骤，进入「确认队列」
4. 逐条批准 → 跑只读准备 → 生成草稿 → 确认后才真实发评论

私信、发布视频目前未接入。开私信必须同时开「人工确认」。

---

## 目录结构

```
.
├── webapp/                 # Web 工作台
│   ├── server.py           # FastAPI 入口（python -m webapp.server）
│   ├── templates/          # 页面模板
│   ├── static/             # app.css / app.js
│   ├── agent_*.py          # Agent 策略、计划、队列、执行
│   └── live_feed.py        # 直播监听会话
├── dy_apis/                # 抖音接口封装
├── dy_live/                # 直播 WebSocket 与 protobuf
├── builder/                # 请求签名、Header 构造
├── utils/                  # Cookie、代理、指纹、签名、下载
├── tests/                  # 单元测试
├── datas/                  # 运行时数据（不入库）
│   ├── media_datas/        # 视频与图片
│   ├── excel_datas/        # 导出的 xlsx / json
│   ├── agent_config.json
│   └── agent_queue.json
├── main.py                 # 命令行模式入口
├── start_web.bat / .ps1    # 一键启动
└── .env                    # 本地凭证（不入库）
```

## 命令行模式

不想开 Web 界面，也可以直接改 `main.py` 末尾的 `__main__` 块跑：

```bash
python main.py
```

默认跑一次关键词搜索示例（只读，不下载媒体以外的写操作）。按注释切换：

- 作品链接批量采集
- 用户全部作品采集
- 私信发送（默认注释掉，避免误发）

## 数据保存位置

| 内容 | 路径 |
| --- | --- |
| 视频 / 图片 / 封面 | `datas/media_datas/<作者>/` |
| Excel / JSON | `datas/excel_datas/` |
| Agent 策略与队列 | `datas/agent_config.json`、`agent_queue.json` |

## 常见问题

**启动失败，提示端口被占用**
`start_web.bat` 会自动结束占用进程；手动启动时换个端口：`DY_WEB_PORT=8080`。

**模块导入报 `runtime_version`**
protobuf 被降级了。执行 `pip install "protobuf>=5.27"` 后再启动。

**采集一直空结果 / 频繁失败**
按顺序检查：Cookie 是否过期 → 代理是否可用 → 指纹是否与 Cookie 来源浏览器一致 → 是否请求太频繁（调低数量、放慢节奏）。

**扫码后状态仍是未就绪**
点「保存并重载会话」让服务重新加载 `.env`；仍不行就重启服务。

**下载按钮没反应**
确认导出文件确实生成在 `datas/excel_datas/`，并在「本地档案」页刷新一次。

## 免责声明

本项目仅用于个人学习与研究。采集到的数据、内容版权归原作者及平台所有，请遵守抖音用户协议与当地法律法规，不要用于商业倒卖、批量骚扰或任何侵害他人权益的行为。使用产生的风险由使用者自行承担。
