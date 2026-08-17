# 🐾 Amiya Desktop Pet — 更新日志

## 🚀 v1.0.1 (2026-08-10)

> **仓库**: [Wyuio-0/AmiyaDesktopPet](https://github.com/Wyuio-0/AmiyaDesktopPet)

### ✨ 改进

**🎙️ 语音克隆服务改为手动控制**
- 右键菜单新增「启动语音克隆服务（AI 声线）」/「停止语音克隆服务（释放显存）」，移除首次 TTS 自动加载模型的逻辑
- 菜单按服务状态动态显示：未启动 → 启动；加载中（约 30 秒）→ 禁用态；运行中 → 停止
- 不手动拉起时，桌宠日常运行不再加载 2-4 GB 语音模型，**常驻内存占用大幅降低**

### ⚙️ 使用变化

- 需要克隆声线：右键 →「启动语音克隆服务（AI 声线）」，约 30 秒后生效；加载期间朗读自动降级为 edge-tts
- 空闲 10 分钟无 TTS 请求仍自动释放显存，也可右键「停止语音克隆服务（释放显存）」手动释放
- 残留或加载了错误角色的旧服务进程，可右键「停止」清理

### 📄 文档

- README 同步更新语音合成说明、右键菜单交互与 FAQ

---

## 🎉 v1.0.0 (2026-08-07)

> **版本**: v1.0.0  
> **日期**: 2026-08-07  
> **仓库**: [Wyuio-0/AmiyaDesktopPet](https://github.com/Wyuio-0/AmiyaDesktopPet)

---

## 🎉 概述

Amiya Desktop Pet 是一个 Windows 桌面宠物程序，把《明日方舟》的阿米娅带到你的桌面上。她会在屏幕底部播放动画，响应拖拽、点击和聊天，接入大模型与你对话，甚至帮你翻译文字、操控电脑。

---

## ✨ 新功能

### 🎭 多角色系统
- 内置三位角色：**阿米娅**、**圣聆初雪**、**予愿安洁莉娜**（新增）
- 每位角色拥有独立动画素材（idle / click / drag / move / sit / sleep / greet / skill）和语音包
- 右键菜单一键切换角色，热加载无需重启
- 支持通过 `config.json` 自定义动作、缩放比例、人设和台词

### 🌐 快速翻译（新增）
- `Alt+T` 全局热键翻译剪贴板内容
- AI + Google 翻译双后端，在线优先 AI，离线自动降级
- 翻译结果以专用浮窗展示，自动消失

### 🤖 AI 对话
- 接入兼容 `/v1/chat/completions` 的大模型（DeepSeek / OpenAI / Kimi / 通义千问 / Qwen 等）
- 对话保留最近 8 轮上下文
- 支持角色级 `ai_config.json` 或环境变量配置 API Key
- 离线模式自动使用内置台词

### 🔧 电脑操控
- 对话中让宠物帮你：打开程序、搜网页、调音量、媒体控制、锁屏、截图、设提醒
- **安全白名单机制**：仅开放固定操作，无任意命令执行
- URL 访问限制为公网 http(s)，拒绝内网/本地地址

### 🎙️ 语音合成
- 支持 **GPT-SoVITS 语音克隆**（本地 GPU 推理）
- 支持 **edge-tts**（微软免费在线 TTS）
- 自动 TTS 开关控制，避免打扰

---

## 🔒 安全修复（重要）

此版本经过安全审计，修复了以下问题：

| 问题 | 修复 |
|------|------|
| **端口误杀** — TTS 端口检测用子串匹配，可能命中外部地址误杀无关进程 | 改为精确列匹配 + 端口严格相等判断 |
| **临时文件泄露** — 合成音频使用固定文件名留在 `%TEMP%`，包含用户对话内容 | 改用 `mkstemp` 随机命名，`O_EXCL` 防符号链接占位，退出时自动删除 |
| **TTS 服务未认证** — 虽只绑 `127.0.0.1`，但网页可通过 `text/plain` POST 绕过 CORS 占用 GPU | 增加 `X-Amiya-Token` 共享密钥 + `Content-Type` 校验，token 自动生成无需手动配置 |
| **URL 提示注入** — 模型可被诱导访问内网地址（路由器管理页、本机服务），浏览器带用户 Cookie | `open_url` 限制仅公网 http(s)，拒绝回环/内网段/link-local/file/UNC |
| **依赖供应链** — 未锁定版本可能被上游投毒 | `requirements.txt` 锁定精确版本，补上缺失的 `Pillow`（截图依赖） |
| **API Key 泄露** — 配置文件中的真实密钥可能被提交 | 添加 `.gitignore` 规则 + 提供 `ai_config.example.json` 模板 + 清除已提交的 Key |

---

## 🐛 Bug 修复

- **中文输入法超时**：修复中文输入法下聊天输入框因 IME 组合过程超时被自动关闭的问题
- **API Key JSON 格式**：修复 `ai_config.json` 中 `api_key` 字段的 JSON 格式问题
- **配置文件模板化**：将 `ai_config.json` 改为 `ai_config.example.json`，避免密钥被误提交

---

## 📦 安装使用

### 普通用户
到 [Releases](https://github.com/Wyuio-0/AmiyaDesktopPet/releases) 下载 `DesktopPet.exe`，双击运行。

需要语音克隆功能请下载完整安装包（分卷压缩），解压后运行 `setup.bat`。

### 开发者

```bash
git clone https://github.com/Wyuio-0/AmiyaDesktopPet.git
cd AmiyaDesktopPet
pip install -r requirements.txt
python main.py              # 默认角色
python main.py amiya        # 指定角色
```

---

## 📋 变更统计

```
66 files changed, 476 insertions(+), 78 deletions(-)
```

- 新增文件：角色资源（动画 WebM + 语音 WAV）、翻译模块、配置模板
- 修改文件：TTS 模块（安全加固）、窗口系统（IME 修复）、动作模块（URL 限制）、README（完整文档）

---

## 🙏 贡献

欢迎提交 Issue 和 PR！如果你有新角色素材想添加，请参考 `characters/` 目录结构。

---

> *"博士，您还有许多事情需要处理。不过现在，先休息一下吧。"* — 阿米娅
