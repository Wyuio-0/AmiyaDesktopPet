# 🐾 桌面宠物 (Desktop Pet)

一个基于 PyQt5 的桌面宠物程序——把《明日方舟》的阿米娅（或其他角色）放到你的桌面上。她会在屏幕底部播放动画，响应拖拽、点击、聊天，还能帮你翻译文字、操作电脑。

<!-- 上传到 GitHub 后可以添加截图：![preview](app_preview.png) -->

## ✨ 功能

- **动画播放** — WebM 透明抠图，支持 idle / click / drag / greet / move / sit / sleep 多动作
- **AI 对话** — 接入大模型（DeepSeek / OpenAI / 通义千问等），阿米娅按人设陪你聊天
- **语音合成** — 支持语音克隆（GPT-SoVITS）和 edge-tts，让宠物"开口说话"；克隆服务手动拉起，平时不占显存
- **快速翻译** — `Alt+T` 翻译剪贴板文字，AI + Google 双后端自动降级
- **课程表** — 导入强智教务课表（武大等），上课前语音提醒、查今天/下一节课/本周课表
- **待办与考试** — 自然语言添加作业 DDL 和考试倒计时（"周五交高数作业"），到期前提醒
- **OCR 截图** — `Alt+S` 框选屏幕区域 → 识别文字 → 翻译/总结（离线 WinRT OCR 或 AI 视觉）
- **电脑操控** — 对话中让宠物帮你打开程序、搜网页、调音量、截屏、设提醒
- **专注工具** — 内置番茄钟、倒计时、定时提醒
- **多角色** — 一键切换人物，自带阿米娅、圣聆初雪和予愿安洁莉娜
- **全局热键** — `Alt+A` 唤起聊天，`Alt+T` 翻译剪贴板
- **自适应内存** — 根据系统空闲 RAM 动态调整帧缓存，低配电脑也不卡
- **离线可用** — 未配置 API key 时自动使用内置台词

## 🚀 快速开始

### 方式一：直接下载运行（推荐，无需 Python）

适合普通用户，**不需要安装 Python**。

1. 到 [Releases](../../releases) 下载最新版 `DesktopPet.exe`
2. 双击运行即可

> 如果你需要**本地语音克隆**（GPT-SoVITS，需 NVIDIA 显卡），请下载完整安装包（`DesktopPet_v*.7z.001` 等分卷），全部下载完后右键 `.001` → 解压，然后运行 `setup.bat`。

### 方式二：从源码运行（开发者）

#### 环境要求

- Windows 10 / 11（全局热键依赖 Win32 API）
- Python 3.10+
- 建议有 CUDA 显卡（语音克隆功能需要，非必需）

依赖在 `requirements.txt` 中**锁定了精确版本**，保证可复现安装，也避免上游某个版本被投毒后被静默拉进来。升级请手动改版本号。其中 `psutil` 缺失时自适应内存管理会退化成保守档（假定可用内存 4 GB），`Pillow` 缺失时截图功能会静默失效 —— 两者都别漏装。

#### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/Wyuio-0/AmiyaDesktopPet.git
cd AmiyaDesktopPet

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python main.py              # 加载第一个可用角色
python main.py amiya        # 指定角色
```

首次运行，阿米娅会出现在屏幕底部中央。没有配置 AI 时她会用内置台词回应你。

#### 生成 exe（可选）

```bash
# 双击 build.bat，或执行：
powershell -ExecutionPolicy Bypass -File build.ps1
```

构建完成后 `dist/` 下会生成 `DesktopPet.exe`，桌面快捷方式自动刷新。

## 🎮 交互

| 操作 | 行为 |
|------|------|
| 左键拖拽 | 移动宠物（触发 move 动画） |
| 单击 | 触发 click 动画 + 语音 |
| 双击 | 弹出聊天输入框 |
| 右键 | 菜单：聊天 / 翻译 / 切换角色 / 课程表 / 待办与考试 / OCR 截图 / 专注工具 / 语音克隆服务 / 音量 / 退出 |
| `Alt+A` | 全局热键唤起聊天（可在 config.json 中修改） |
| `Alt+T` | 翻译剪贴板内容 |
| `Alt+S` | OCR 截图翻译（框选区域） |

窗口无边框、始终置顶、背景透明——点击宠物身体以外的区域会穿透到桌面。

## 🤖 AI 对话

### 配置 API Key

编辑 `characters/<角色>/ai_config.json`，填入 API key：

```json
{
  "api_key": "",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "temperature": 0.8,
  "allow_actions": true
}
```

或者通过环境变量（优先级更高）：

```bash
set PET_AI_KEY=your_api_key
set PET_AI_BASE=https://api.deepseek.com      # 可选
set PET_AI_MODEL=deepseek-chat                # 可选
```

支持所有兼容 `/v1/chat/completions` 的服务：DeepSeek、OpenAI、Kimi、通义千问、Qwen 等。

### 离线模式

未配置 API key 时，阿米娅使用内置台词回复。所有离线台词在 `ai.py` 的 `FALLBACK` 列表中，也可在角色 `config.json` 中通过 `"fallback"` 字段自定义。

### 自定义人设

在角色 `config.json` 中添加 `"persona"` 字段即可覆盖默认人设：

```json
{
  "persona": "你是《明日方舟》中的能天使，企鹅物流成员。你活泼开朗，喜欢用枪解决问题……"
}
```

对话保留最近 8 轮上下文，历史存储在 `%APPDATA%\AmiyaPet\` 下。右键菜单点「忘记对话」可清除。

## 🌐 快速翻译

| 触发方式 | 操作 |
|----------|------|
| 全局热键 | 任意应用 `Ctrl+C` 复制 → `Alt+T` |
| 聊天框 | 输入 `翻译:hello world` |
| 右键菜单 | 「翻译剪贴板（Alt+T）」 |

翻译结果以专用浮窗展示（原文灰色 + 译文白色），自动消失或点击关闭。后端优先使用已配置的 AI 模型，离线时降级到 Google 翻译。

## 🔧 电脑操控

在线模式下，阿米娅可以帮你完成一组**白名单内、安全可逆**的操作：

| 对话示例 | 实际动作 |
|----------|----------|
| "帮我打开记事本" | 启动 notepad |
| "打开 bilibili.com" | 浏览器打开网址 |
| "搜索明日方舟" | 必应搜索 |
| "声音大一点 / 静音" | 调节系统音量 |
| "暂停 / 下一首" | 媒体控制 |
| "帮我锁屏" | `LockWorkStation` |
| "截个图" | 全屏截图 → `图片` 文件夹 |
| "现在几点" | 报当前时间 |
| "10 分钟后提醒我开会" | 定时提醒 |

**安全边界**：仅开放上述固定操作，无任意命令执行、无文件删除、无关机。程序名走字典白名单，无法启动任意可执行文件。

打开网址限制为**公网 http(s) 页面**：回环地址、内网段（`127.0.0.1`、`192.168.x`、`10.x`、`169.254.x`）、以及 `file:` / UNC 路径一律拒绝。原因是模型的工具调用会受它读到的文本影响（聊天输入、剪贴板内容），而浏览器带着你的 Cookie —— 不加限制的话，一次提示注入就能让它去访问路由器管理页或本机其他服务的已认证接口。正常上网不受影响。

想完全关闭电脑操控，将 `ai_config.json` 中的 `allow_actions` 设为 `false`。

## 📅 课程表（学生功能）

把教务系统的课表导入桌宠，她会在上课前语音提醒你，也能随时查课。

### 如何拿到课表数据（强智教务，武大等）

1. 登录教务系统 → 打开「个人课表查询」，点**查询**让课表显示出来
2. 按 `F12` 打开开发者工具 → **Network（网络）** 标签 → 过滤框输入 `xskbcx`
3. 点 `xskbcx_cxXsksxxlist` 请求 → **Response（响应）** → 右键 → **Copy response**
4. 把复制的内容保存为 `.json` 文件（例如 `kebiao.json`）

### 导入

两种方式任选：

- **命令行**（推荐，一步到位）：
  ```bash
  python tools/import_schedule.py kebiao.json --term-start 2026-08-31
  ```
  `--term-start` 是**第 1 周周一**的日期，不传则默认今天所在周的周一。
- **右键菜单**：桌宠上右键 →「课程表 → 导入课表…」，选择 JSON 文件，按提示填开学日期。

数据保存在 `%APPDATA%\AmiyaPet\schedule.json`（原始 JSON 留档为 `schedule_raw.json`），重装程序不丢失。

### 使用

| 操作 | 行为 |
|------|------|
| 右键 → 课程表 → 今天课程 | 信息面板显示今天的课 |
| 右键 → 课程表 → 下一节课 | 信息面板显示最近一节课及剩余时间 |
| 右键 → 课程表 → 本周课表 | 信息面板显示整周课表（标注单双周、本周不上） |
| 自动 | 上课前 10 分钟语音+气泡提醒（可在 `schedule.json` 的 `remind_minutes` 改） |

> 课表、待办、OCR 等**信息量较大的内容统一显示在「信息面板」窗口**（可拖动、可缩放、可滚动）：
> 左侧导航切换 课程表 / 待办与考试 / OCR 结果，`Esc` 或右上角 ✕ 关闭。

### 自定义

`schedule.json` 支持按需修改：

```json
{
  "term": "2026-2027-第1学期",
  "term_start": "2026-08-31",
  "remind_minutes": 10,
  "sections": { "1": "08:00", "2": "08:50", "3": "09:50", "4": "10:40", "5": "11:30",
                "6": "14:00", "7": "14:50", "8": "15:40", "9": "16:30",
                "10": "18:30", "11": "19:20", "12": "20:10", "13": "21:00" }
}
```

- `term_start` — 第 1 周周一日期，周次计算基准（务必核对）
- `sections` — 各节次的开始时刻，**默认是常见作息，请按本校教务处作息修改**
- `remind_minutes` — 上课前提前提醒分钟数

## 📋 待办与考试（学生功能）

记录作业截止日期和考试时间，到期前让阿米娅提醒你。

### 使用

右键菜单 →「待办与考试」：

| 操作 | 行为 |
|------|------|
| 添加作业 DDL… | 填事项、课程、截止时间；**截止时间支持自然语言**：`明天`、`周五 23:59`、`9月20日`、`2026-12-25 14:00`、`下周一` |
| 添加考试… | 同上，默认提前 1 周提醒 |
| 即将到期 | 浮窗显示按剩余时间排序的任务清单 |
| 考试倒计时 | 显示最近考试还有多少天 |
| 管理待办… | 列表管理：双击标记完成、按钮删除 |
| 自动 | 到期前提醒（作业默认提前 1 天、考试提前 1 周，添加时可改） |

数据保存在 `%APPDATA%\AmiyaPet\tasks.json`，不随打包分发、不进仓库。

## 🔍 OCR 截图翻译/总结（学生功能）

框选屏幕任意区域 → 识别文字 → 翻译或总结，浮窗展示。适合英文 PPT、文献段落、网课截图、板书。

### 使用

| 操作 | 行为 |
|------|------|
| `Alt+S` 或右键 → OCR 截图 → 截图翻译 | 全屏截图 → 拖拽框选区域 → 识别并翻译（AI 优先，Google 兜底） |
| 右键 → OCR 截图 → 截图总结 | 同上，但用 AI 提炼要点（≤200 字） |

框选时：拖拽画矩形，松手开始识别；`Esc` 或右键取消。

### OCR 后端（按优先级自动降级）

1. **Windows 自带 OCR（离线、免费、中文好）**——需安装可选依赖：
   ```bash
   pip install winsdk
   ```
2. **AI 视觉模型（在线）**——无需 winsdk，但需在 `ai_config.json` 配置**支持视觉**的模型，
   例如 `"model": "moonshot-v1-8k-vision-preview"`（配好 `api_key` 即可）。

两个后端都不可用时，会提示如何启用。注意：截图里的内容会发给 AI 后端（如有配置），隐私敏感内容请用离线 winsdk 或慎用 AI 总结。

## 🎭 角色系统

### 目录结构

```
characters/
├── amiya/                  # 阿米娅
│   ├── config.json         # 角色定义（动作/缩放/语音/人设）
│   ├── ai_config.json      # AI 配置（api_key/base_url/model）
│   ├── idle/               # 待机动画 (.webm)
│   ├── click/              # 点击动画
│   ├── drag/               # 拖拽动画
│   ├── greet/              # 打招呼动画
│   ├── move/               # 移动动画
│   ├── sit/                # 坐下动画
│   ├── sleep/              # 睡觉动画
│   └── voice/              # 语音文件 (.wav)
├── shenglinchuxue/         # 圣聆初雪
│   └── ...
└── yuyuananjielina/        # 予愿安洁莉娜
    └── ...
```

### config.json 字段说明

```json
{
  "name": "amiya",
  "display_name": "阿米娅",
  "scale": 1.0,
  "hotkey": "alt+a",
  "actions": {
    "idle": {
      "folder": "idle",
      "interval": 40,
      "loop": true,
      "next": null
    },
    "click": {
      "clip": "click.webm",
      "interval": 40,
      "loop": false,
      "next": "idle"
    }
  },
  "interactions": {
    "on_click": "click",
    "on_drag": "move",
    "on_double_click": null
  },
  "voice": {
    "enabled": true,
    "volume": 0.7,
    "tts": {
      "enabled": true,
      "use_clone": true,
      "clone_dir": "voiceclone",
      "clone_character": "amiya",
      "voice": "zh-CN-XiaoyiNeural",
      "rate": "+0%"
    }
  },
  "rest": {
    "idle_to_sit": [300, 600],
    "sit_to_sleep": [3600, 7200]
  },
  "greetings": {
    "enabled": true,
    "morning": { "start": "06:00", "end": "10:00", "lines": ["早安，博士。"] },
    "noon":    { "start": "12:00", "end": "14:00", "lines": ["中午了，博士记得吃饭。"] },
    "late_night": { "start": "23:00", "end": "03:00", "lines": ["已经很晚了，博士早点休息。"] }
  }
}
```

| 字段 | 说明 |
|------|------|
| `name` / `display_name` | 内部标识 / 显示名称 |
| `scale` | 缩放比例（1.0 = 原始大小） |
| `hotkey` | 聊天热键（仅 Windows，需至少一个修饰键+一个字母键） |
| `actions.<name>.folder` | 动作对应的文件夹（内含 .webm 帧序列） |
| `actions.<name>.clip` | 或指定单个动画文件 |
| `actions.<name>.interval` | 帧间隔（毫秒），越小动画越快 |
| `actions.<name>.loop` | 是否循环播放 |
| `actions.<name>.random` | 多 clip 时是否随机选取 |
| `actions.<name>.next` | 播放结束后自动切换到的动作名 |
| `actions.<name>.loop_count` | 额外重复次数（配合 `next` 使用） |
| `interactions` | 将交互事件映射到动作名 |
| `voice.enabled` | 是否启用语音 |
| `voice.tts.use_clone` | 是否使用语音克隆（需单独部署） |
| `voice.tts.clone_dir` | 语音克隆项目路径（绝对路径或相对于 exe/项目根） |
| `rest` | 空闲时逐级放松：idle → sit → sleep，单位为秒 |
| `greetings` | 定时问候（早/午/深夜），支持跨午夜时间窗口 |

## 🎤 语音合成

支持两种 TTS 后端，自动降级：

1. **语音克隆**（GPT-SoVITS）— 阿米娅自己的声音，需额外部署 [voiceclone](https://github.com/RVC-Boss/GPT-SoVITS) 服务
2. **edge-tts** — 微软免费在线神经语音，有网就能用
3. **预录语音** — 离线兜底，播放角色 `voice/` 目录下的 `.wav` 文件

语音克隆服务**手动启动**：右键菜单「启动语音克隆服务（AI 声线）」拉起，模型加载约 30 秒；加载完成后朗读回复才使用克隆声线，否则自动降级到 edge-tts。不主动拉起的会话不会加载模型，桌宠常驻时内存占用低。空闲 10 分钟自动释放 GPU 内存，也可右键「停止语音克隆服务（释放显存）」手动释放。

### 语音克隆服务的访问控制

克隆服务只绑定 `127.0.0.1`，外网进不来。但回环地址对**本机任意进程**都是开放的，包括浏览器里的 JavaScript —— 网页用 `Content-Type: text/plain` 发一个不触发 CORS 预检的 POST，就能白嫖你的 GPU 做合成。所以 `POST /tts` 有两道校验：

- 必须带 `X-Amiya-Token` 头，值是一个随机 token
- `Content-Type` 必须是 `application/json`（堵住上面那条 text/plain 绕过）

token 首次运行时自动生成，存在 `%APPDATA%\AmiyaPet\tts_token`，宠物和 `serve.py` 读同一个文件，所以谁先启动都行，无需手工配置。也可以用 `AMIYA_TTS_TOKEN` 环境变量覆盖（两边都要设）。

如果 token 文件读不到，服务会打印 `auth: DISABLED` 并放行 —— 宁可退化也不让宠物直接失声。此时 Content-Type 校验仍然生效。用 `--host 0.0.0.0` 且无 token 启动会额外告警。

合成出来的音频是你的对话内容，所以临时文件用 `mkstemp` 随机命名（同时借 `O_EXCL` 防止本机进程预先占位成符号链接改写向），并在退出时删除。

## 📁 项目结构

```
.
├── main.py                  # 入口
├── DesktopPet.spec          # PyInstaller 打包配置
├── build.bat / build.ps1    # 构建脚本
├── requirements.txt         # 运行依赖（精确锁定）
├── requirements-dev.txt     # 开发/测试依赖（pytest）
├── pytest.ini               # pytest 配置
├── app.ico                  # 应用图标
├── LICENSE                  # MIT License
├── .githooks/               # pre-commit 安全钩子（密钥/个人信息扫描）
├── .github/workflows/       # GitHub Actions CI（测试 + 构建 + 自动发布）
├── tests/                   # pytest 测试套件（schedule/tasks/ocr/frames/安全规则）
├── pet/                     # 核心模块
│   ├── window.py            # 主窗口（动画播放 / 交互 / 生命周期）
│   ├── frames.py            # WebM 解码 + 透明抠图（边界背景 + 闭合背景缝）
│   ├── character.py         # 角色模型（解析 config.json / 动作枚举）
│   ├── ai.py                # AI 对话（OpenAI 兼容 API + 流式 + 工具调用）
│   ├── ai_settings.py       # AI 配置对话框
│   ├── chat.py              # 聊天气泡 + 输入框
│   ├── voice.py             # 预录语音播放
│   ├── tts.py               # 语音合成（语音克隆 + edge-tts）
│   ├── translate.py         # 快速翻译（AI + Google 双后端 + 翻译浮窗）
│   ├── schedule.py          # 课程表（强智课表解析 / 上课提醒 / 查询）
│   ├── tasks.py             # 待办/考试（中文日期解析 / 到期检查 / 持久化）
│   ├── tasks_ui.py          # 待办/考试 对话框（自然语言截止时间 / 任务管理）
│   ├── info_panel.py        # 信息面板（课程表/待办/OCR 集中展示窗口）
│   ├── ocr.py               # OCR（WinRT 离线优先 / AI 视觉降级）
│   ├── region_select.py     # 区域框选浮层（截图 OCR 用）
│   ├── actions.py           # 电脑操控（白名单安全动作）
│   ├── hotkey.py            # 全局热键（Win32 RegisterHotKey）
│   ├── timers.py            # 倒计时浮窗 / 番茄钟 / 提醒对话框
│   ├── settings.py          # 用户偏好持久化（JSON）
│   ├── memory.py            # 自适应内存管理
│   └── theme.py             # UI 主题（罗德岛黑金配色）
├── tools/                   # 开发工具
│   └── import_schedule.py   # 命令行导入强智课表 JSON
└── characters/              # 角色资源
    ├── amiya/               #   阿米娅（默认）
    ├── shenglinchuxue/      #   圣聆初雪
    └── yuyuananjielina/     #   予愿安洁莉娜
```

## 🧪 测试与 CI

### 本地跑测试

```bash
pip install -r requirements-dev.txt
python -m pytest          # 全部测试
python -m pytest tests/test_tasks.py -k parse   # 只跑某个文件/关键字
```

测试覆盖：课表解析与查询、待办中文日期解析与持久化、抠图算法、OCR 后端降级、安全扫描规则。CI（GitHub Actions）在每次 push 自动运行：**安全扫描 → 测试 → 构建 exe → 校验 dist 无泄露**；打 `v*` 标签时自动发布 Release（附 exe）。

### 安全钩子

`.githooks/pre-commit` 在每次提交前扫描暂存区，发现 API key / 课表数据 / `ai_config.json` 等即阻止提交：

```bash
git config core.hooksPath .githooks   # 启用（克隆后执行一次）
python tools/check_secrets.py --all   # 手动全量扫描整个工作区
```

## 🔍 透明处理

WebM 源文件是黑色背景（无 alpha 通道）。程序先把「近黑 **且** 低色度」的像素判为背景候选（这样带色相的深色衣物、紫蓝色描边不会被误判），再做两次筛选：

1. **边界连通背景** — 给背景掩码垫一圈 1px 边框后做单次 flood-fill，凡是能连到画面边缘的背景全部抠成透明；
2. **闭合背景缝** — 角色动起来时，手臂与腰、裙摆与腿、发丝与头之间会围出一些「与边缘不连通」的纯黑缝隙，若不处理就会变成闪烁的黑块。这类被角色完全包围的背景块也会一并抠掉（带面积下限保护，眼睛、瞳孔等小深色特征绝不误删）。

角色内部保持完全不透明（深色轮廓、衣物不受影响），边缘仅做 1px 亮度的渐变羽化——抗锯齿边缘平滑、核心锐利。见 `pet/frames.py`。

## ⚙️ 用户数据

偏好设置和对话历史保存在：

```
Windows: %APPDATA%\AmiyaPet\settings.json      # 音量 / 静音 / 当前角色
                 \history_<角色名>.json         # 对话历史（上限 8 轮）
                 \tts_token                     # 语音克隆服务的共享密钥
Linux:   ~/.config/amiya_pet/
```

这些都在**安装目录之外**，重装或重新打包不会丢，也不会混进版本控制。

> **API Key 不要提交。** `ai_config.json` 已被 `.gitignore` 排除（`**/ai_config.json`），仓库里只有 `ai_config.example.json` 模板（`api_key` 为空）。注意删掉文件并不会删掉 git 历史里的 blob —— 如果 key 曾经进过某次 commit，唯一有效的补救是**去服务商控制台吊销它**，然后再用 `git filter-repo` 清理历史。优先用 `PET_AI_KEY` 环境变量，key 就永远不会落在仓库目录里。

## ❓ 常见问题

**Q: 双击宠物没有反应？**  
A: 等待第一个动画帧加载完毕（约 1 秒）后再试。若始终无效，检查 `characters/<角色>/config.json` 是否完整。

**Q: 聊天输入框弹不出来？**  
A: 确保全局热键注册成功（右键菜单中聊天项后面会显示快捷键提示）。如果热键被其他程序占用，换个组合：编辑 `config.json` 的 `hotkey` 字段，例如 `"ctrl+shift+a"`。

**Q: AI 回复"连接出错了"？**  
A: 检查 `ai_config.json` 中的 `api_key` 和 `base_url`，确认网络能访问该 API 地址。中国大陆用户用 DeepSeek 通常最稳定。

**Q: 翻译不工作？**  
A: 翻译优先使用 AI（需配置 API key），降级到 Google 翻译。如果在国内且未配置 key，Google 翻译可能因网络原因不可用——配置 API key 即可解决。

**Q: 语音克隆怎么部署？**  
A: 参考 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 部署服务到 `http://127.0.0.1:9881`。部署完成后，**右键菜单 →「启动语音克隆服务（AI 声线）」**手动拉起，约 30 秒后生效；不想用时点「停止语音克隆服务（释放显存）」。也可将 `"use_clone"` 设为 `false` 只用 edge-tts。

**Q: 为什么宠物说话不是克隆声线？**  
A: 克隆服务是**手动拉起**的，不会自动加载。右键菜单 →「启动语音克隆服务（AI 声线）」，约 30 秒加载完成后回复就会用克隆声线；在此之前自动降级为 edge-tts。

**Q: 怎么添加新角色？**  
A: 在 `characters/` 下新建文件夹，放入 `config.json` + 各动作的 `.webm` 文件 + 可选 `voice/*.wav`。右键菜单「切换人物」中会自动发现。

## 📄 许可证

MIT License
