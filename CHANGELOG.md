# Changelog

本项目更新日志。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

> CI 发布时会自动提取与 tag 匹配的段落（`## [vX.Y.Z]`）作为 GitHub Release 正文；
> 若该版本段落不存在，则自动从提交历史生成。新增功能记得在 `## [Unreleased]` 下补记。

## [v1.3.2] - 2026

### 修复

- add_character 测试在 `tmp_path/src` 下未先建目录，导致 CI 报 FileNotFoundError

## [v1.3.1] - 2026

### 新增

- **一键添加新角色**：右键 → 切换人物 → 添加新角色…，选择素材文件夹（按动作子目录
  或文件名关键词自动分类），自动复制视频/语音并生成 `config.json`

## [v1.3.0] - 2026

### 新增

- **一键语音克隆微调**：`tools/train_clone.bat` 双击即用——准备音频+文本标注即可
  自动预处理并训练 GPT-SoVITS S2（含安洁莉娜数据管线脚本）
- **RTX 5060（Blackwell）训练兼容方案**：单进程训练、假 DDP（Windows torch 无
  NCCL）、禁用 GradScaler / TF32 / cuDNN / fp16 / weight_norm，修复 backward 段错误

### 工程

- 安装包 CI 自动化：choco 安装 Inno Setup 后直接调用 ISCC（不再依赖失效的 iscc-action）

## [v1.2.1] - 2026

### 新增

- **考试倒计时常驻徽章**：桌宠旁显示距最近考试还有几天，每小时刷新，可开关
- **AI 今日安排汇总（`today_summary`）**：一句"今天有什么安排"即汇总今日课程、待办与最近考试
- **AI 打通课表/待办**：`query_schedule` / `query_tasks` / `add_task` 工具，
  阿米娅能直接回答"下节课是什么""今天有什么作业"，并能自然语言添加作业/考试截止
- **讲义知识库（RAG）**：讲义 `.txt` / `.md` 放入 `%APPDATA%\AmiyaPet\knowledge\`
  即可基于课件答疑（词频检索，零依赖）

### 修复

- 语音克隆 `clone_dir` 改为绝对路径，修复 exe 运行时找不到部署目录

### 工程

- 发行说明自动生成：优先提取 CHANGELOG 对应版本段落，缺失时从提交历史生成
- **安装包分发**：Inno Setup 生成 `DesktopPet-Setup.exe`（用户级安装、自动建桌面快捷方式）；
  打包改为 onedir（修复 onefile 下 Qt5Core.dll 加载崩溃 0xc0000409）

## [v1.1.1] - 2026

### 新增

- **信息面板**：课程表 / 待办与考试 / OCR 结果集中展示，可拖动、缩放、滚动，
  待办行内完成/删除
- **OCR 截图翻译/总结**：`Alt+S` 框选屏幕区域 → 识别文字 → 翻译或 AI 总结
  （Windows 离线 OCR 或 AI 视觉）
- **待办与考试**：自然语言添加 DDL（"周五交高数作业"）与考试倒计时，到期前语音提醒
- **课程表**：导入强智教务课表（武大等），上课前提醒、查今天/下一节/本周

### 修复

- 右键菜单卡顿：语音克隆状态改为后台探测 + 缓存，消除最长 600ms 的 UI 冻结
- 抠图算法重写：清除角色动画中手臂/裙摆/发丝间的背景缝，黑块不再闪烁
- 构建脚本编码问题；打包隐私加固（`ai_config.json` 不进 exe/dist）

### 工程

- pytest 测试套件 + GitHub Actions CI（安全扫描 / 测试 / 构建 exe / 自动发布）
- pre-commit 密钥扫描钩子；MIT License；分支保护

## [v1.0.3] - 2026

### 修复

- 语音克隆服务改为手动拉起，降低常驻内存占用
- 主题适配系统浅色/深色模式
