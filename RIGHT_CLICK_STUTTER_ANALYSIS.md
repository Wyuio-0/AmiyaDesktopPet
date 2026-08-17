# 桌宠右键卡顿：问题分析与修复方案

> 状态：**方案 A + B 已落地**（`pet/tts.py`、`pet/window.py`），C 部分落地（探测已后台化），D/E/F 留待后续
> 范围：`pet/window.py` 右键菜单路径、`pet/tts.py`、`pet/character.py`

## 1. 现象

桌宠上右键弹出菜单时出现**明显卡顿**（动画冻结、菜单延迟弹出、掉帧）。卡顿发生在**菜单显示之前**（构建菜单阶段），表现为"点下去 → 顿一下 → 菜单才出来"。

## 2. 右键调用链走查（修复前的路径）

```
右键 → customContextMenuRequested → PetWindow._menu()            [window.py:84, 997]
  ├─ 构建 QMenu + setStyleSheet(theme.MENU_QSS)                   [window.py:998-999]
  ├─ _add_character_menu(m)                                       [window.py:1016, 1060]
  │    └─ _available_characters()                                 [window.py:1063, 465]
  │         └─ glob("characters/*/config.json")
  │              └─ Character(dir) → 解析 config.json + 每个 Action
  │                   glob 动作文件夹/*.webm                        [character.py:21-34, 42-55]
  ├─ _add_clone_menu(m)                                            [window.py:1024, 1087]
  │    └─ tts.clone_state()                                        [window.py:1096, tts.py:124]
  │         └─ tts.clone_ready()                                   [tts.py:131 → 91]
  │              └─ urllib 同步 HTTP GET http://127.0.0.1:9881/ping
  │                   timeout=0.6s —— ★ 在 UI 线程阻塞 ★
  └─ m.exec_(mapToGlobal(pos))                                     [window.py:1028] 模态事件循环
```

## 3. 根因分析（按影响排序）

> 本节行号为**修复前**代码快照；修复后相关函数见「7. 相关代码位置索引」。

### P0 主因：UI 线程同步 HTTP 探测语音克隆服务 —— `tts.clone_state()`

**位置**：`tts.py:124-135`（`clone_state`）→ `tts.py:91-97`（`clone_ready`），被 `window.py:1096` 在每次右键菜单构建时同步调用。

`clone_ready()` 是**阻塞式** `urllib.request.urlopen(..., timeout=0.6)`，跑在 GUI 线程。右键一次就打一次。三种服务状态下的实际耗时：

| 服务状态 | /ping 行为 | 每次右键阻塞耗时 |
|---|---|---|
| 已停止（端口无人监听） | 连接被拒，立刻抛异常 | ~1-5 ms（几乎无感） |
| **正在加载（starting）** | **端口已监听但 /ping 要等模型加载完才应答（约 30s）** | **卡满 0.6s 超时** ⚠️ |
| 运行中（ready） | 立即回 "ok" | ~1-10 ms（有网络往返开销） |
| 僵尸进程占端口但不应答 | 连接成功、永不响应 | **卡满 0.6s 超时** ⚠️ |

- `window.py:125`：阿米娅默认 `use_clone: true`，因此**每次右键都会走这条路径**。
- 卡顿最明显的窗口期：用户点了「启动语音克隆服务」后的约 30s 加载期内，**每次右键必然卡 600ms**（`tts.py:128` 注释也写明 "the first /ping answers only after ~30s"）。
- 若端口被一个不响应 /ping 的旧进程占用，则**每次右键都卡 600ms**——这可以解释"平时也一直卡"的现象。
- 更糟的是该阻塞发生在 `m.exec_()` **之前**：此时 Qt 事件循环根本没在跑，动画定时器 `_tick` 停摆 → 桌宠整体冻结，然后菜单才弹出。

### P1：每次右键全量扫描并解析所有角色 —— `_available_characters()`

**位置**：`window.py:465-473`，每次菜单构建调用。

```python
pattern = os.path.join(self.characters_dir, "*", "config.json")
for cfg_path in sorted(glob.glob(pattern)):
    chars.append(Character(os.path.dirname(cfg_path)))  # 读 json + 每个 Action 再 glob
```

- `Character()` 构造（`character.py:42-55`）会**读取全部 config.json 并为每个动作文件夹各做一次 `glob("*.webm")`**：3 个角色 × ~9 个动作 ≈ 27 次目录扫描 + 3 次 JSON 解析，全部在 UI 线程。
- SSD 本地盘约 5-30ms；机械盘 / 杀毒软件实时扫描 / 网络盘可放大到 100ms+。
- 属于"每次都白做"：角色列表几乎不变，理应缓存。

### P2：菜单实例化与模态循环开销

- **每次重建 QMenu + 重设 QSS**（`window.py:998-999`）：`theme.MENU_QSS`（`theme.py:105-132`）是 25 行样式表，每次右键都新建菜单并整表重解析。首帧渲染成本叠加在 P0/P1 之后。
- **模态 `m.exec_()` 期间动画定时器照跑**（`window.py:92-93` `_timer` → `_tick`）：菜单打开时嵌套事件循环仍会驱动动画 tick 与分层窗口重绘（`WA_TranslucentBackground` + 无边框 + 置顶的 `Qt.Tool` 窗口），与弹出菜单的组合器交互在部分 Windows/显卡组合上会互相抢帧 → 表现为菜单悬停/打开期间整体掉帧。（该点未经实测，属候选因素。）

### P3（同类问题，顺带记录）：60s 空闲克隆检测也在 UI 线程 ping

**位置**：`window.py:167-170` → `tts.maybe_stop_idle_clone(600)`（`tts.py:176-194`）。

- 每 60 秒一个 `QTimer` 在 UI 线程调用，内部条件触发时执行 `clone_ready(timeout=0.3)`（`tts.py:189`）——同样是同步 HTTP。
- 一旦克隆服务被用过（`_clone_last_used > 0`），之后**每分钟一次**最多 300ms 的 UI 线程阻塞，可能造成周期性小卡。

## 4. 复现与验证方法（不改代码即可确认）

1. **隔离主因**：把当前角色 `config.json` 的 `voice.tts.use_clone` 临时改为 `false`，重启桌宠再右键。
   - 若卡顿消失 → 主因就是 P0 的 `clone_state()` 网络探测。
   - 若仍卡 → 重点查 P1 的目录扫描。
2. **复现 600ms 冻结**：右键菜单点「启动语音克隆服务」后 30s 内连续右键，用秒表/录屏观察菜单弹出延迟 ≈ 0.6s。
3. **精确取证**：对 `_menu()` 加临时 `time.perf_counter()` 计时（或在 PyCharm/VSCode 里用 cProfile 挂载），分别统计 `_available_characters()`、`clone_state()`、`exec_()` 三段耗时。
4. Windows 下可用 **Windows Performance Recorder (WPR)** 抓取右键瞬间的 CPU/事件栈，确认阻塞线程是 Qt GUI 线程在做网络等待。

## 5. 修复方案（按优先级分阶段落地）

> ✅ 已落地 / ⬜ 未实施，见每节说明。落地记录见文末「8. 落地记录」。

### 方案 A（✅ 已落地）：克隆状态缓存 + 后台定时刷新

- **做法**：
  1. `tts.py` 新增 `_clone_state_cache`：`clone_state()` 改为**只读缓存**（非阻塞）；新增 `refresh_clone_state()`（真正探测并写缓存，可在任意线程调用）与 `set_clone_state()`（start/stop 后直接写状态）。
  2. `pet/window.py` 新增 `CloneStateProbe`（一次性 `QThread`）每 3s 在**后台线程**刷新缓存；`_start_clone` / `_stop_clone` 后主动触发一次立即探测。
- **涉及文件**：`pet/tts.py`、`pet/window.py`
- **效果**：右键路径 0 网络调用；600ms 冻结消除（实测克隆菜单构建 0.05ms）。
- **风险**：状态标签可能滞后 ≤3s；「启动/停止」点击后已主动触发立即刷新，可接受。

### 方案 B（✅ 已落地）：动态内容懒加载（`aboutToShow`）

- **做法**：
  1. 「切换人物」子菜单改为占位项 + `QMenu.aboutToShow` 时才填充（`_populate_character_menu`），普通右键不再扫描。
  2. `_available_characters()` 增加 mtime 缓存：目录不变时二次调用只花一次 `stat()`，不再全量 glob + 解析所有角色。
- **涉及文件**：`pet/window.py`
- **效果**：右键构建菜单的同步工作只剩静态项；角色扫描移出右键热路径。
- **风险**：角色配置在运行期被编辑时列表可能滞后（以目录 mtime 为失效依据）；对菜单场景可接受。

### 方案 C（部分已落地）：把网络探测彻底移出 UI 线程

- **做法**：`clone_ready` 改用后台 `QThread`/`QRunnable`（复用 `tts.py` 里现成的 `TtsWorker` 模式），完成时经信号写回状态缓存。`_clone_idle_timer`（P3）同样改为只读缓存。
- **涉及文件**：`pet/tts.py`、`pet/window.py`
- **效果**：无论服务处于何种状态，UI 线程零网络阻塞；P3 一并解决。
- **落地状态**：**右键路径已后台化**（`CloneStateProbe`，见方案 A）。**P3 未迁移**：`window.py` 的 `_clone_idle_timer` 每 60s 仍在 UI 线程调用 `maybe_stop_idle_clone`（内部 `clone_ready(timeout=0.3)`，且仅在克隆服务被使用过后才触发，单次最多 300ms）——留待后续。
- **风险**：状态刷新存在异步竞态（用户点「停止」瞬间状态可能仍是 running），需用"操作先行 + 状态最终一致"的策略。

### 方案 D（⬜ 未实施）：复用 QMenu 实例，消除每次重建与 QSS 重解析

- **做法**：`_menu()` 里缓存 `self._menu`（首次构建），动态项（AI 状态、克隆状态、音量、静音勾选）在 `aboutToShow` 时按缓存值更新；QSS 只设置一次。
- **涉及文件**：`pet/window.py`
- **效果**：摊薄菜单构建与样式表解析成本；也是方案 A/B 的自然承接。

### 方案 E（⬜ 未实施）：菜单打开期间暂停/降载动画

- **做法**：`m.exec_()` 前 `self._timer.stop()`，`aboutToHide`/`destroyed` 后按当前动作恢复（参考 `_switch_character` 里已有的停/启定时器写法，`window.py:485-516`）。
- **涉及文件**：`pet/window.py`
- **效果**：消除模态期间动画 tick 与菜单抢帧（P2 后半段）。
- **风险**：菜单开着时桌宠不动，属预期行为；需保证所有退出路径（选中项、Esc、点空白）都能恢复定时器。

### 方案 F（⬜ 未实施，已被方案 B 部分覆盖）：角色列表缓存 + 轻量元数据

- **做法**：`_available_characters()` 的结果按 `characters_dir` 的 mtime 缓存；菜单只需要 `display_name`，可改为不构造完整 `Character`（跳过每个动作的 glob），或给 `Character` 加一个 `light=True` 模式。
- **涉及文件**：`pet/window.py`、`pet/character.py`
- **效果**：把 P1 的 20+ 次目录扫描降为 0。
- **落地状态**：**mtime 缓存部分已随方案 B 落地**；`light=True` 轻量解析未实施（当前缓存 + 懒加载已足够）。

## 6. 落地状态与验收

1. **A + B 已完成**：右键路径零同步网络、角色扫描按 mtime 缓存且懒加载 → 复现步骤 1/2 不再出现卡顿（冒烟测试：克隆菜单构建 0.05ms，探测在后台线程完成）。
2. **C 部分完成**：探测已后台化；`_clone_idle_timer`（P3）的 60s ping 留待后续迁移。
3. **D/E 未实施**：如仍有菜单打开期间的掉帧，再按需落地。
4. **验收**：`use_clone=true` 且服务处于 starting 状态时，连续右键 10 次，菜单弹出延迟均 < 50ms；菜单打开期间桌宠动画流畅或按预期暂停；`WPR` 抓包无 GUI 线程网络等待栈。

## 7. 相关代码位置索引

| 位置 | 说明 |
|---|---|
| `pet/window.py` `_menu()` | 右键菜单构建与 `exec_()` |
| `pet/window.py` `_add_character_menu()` / `_populate_character_menu()` | 角色子菜单懒加载（方案 B） |
| `pet/window.py` `_available_characters()` | 角色扫描（mtime 缓存） |
| `pet/window.py` `_add_clone_menu()` | 读缓存状态（方案 A） |
| `pet/window.py` `CloneStateProbe` / `_schedule_clone_probe()` | 后台状态探测线程（方案 A/C） |
| `pet/window.py` `_start_clone()` / `_stop_clone()` | 操作后主动刷新状态 |
| `pet/window.py` `_clone_idle_timer` | 每 60s 同步 ping（P3，未迁移） |
| `pet/tts.py` `clone_ready()` | 阻塞 HTTP（0.6s 超时，仅后台/用户操作调用） |
| `pet/tts.py` `clone_state()` / `refresh_clone_state()` / `set_clone_state()` | 缓存读写（方案 A） |
| `pet/tts.py` `maybe_stop_idle_clone()` | 内部 0.3s ping（P3，未迁移） |
| `pet/character.py` `Action`/`Character` | 构造中的目录扫描（已随缓存懒加载） |
| `pet/theme.py` `MENU_QSS` | 每次右键整表重设（方案 D，未实施） |

## 8. 落地记录

- 将 `tts.clone_state()` 改为缓存读取；新增 `refresh_clone_state()` / `set_clone_state()`（`pet/tts.py`）。
- 新增 `CloneStateProbe` 后台线程 + 3s 定时探测；`_start_clone` / `_stop_clone` 后主动触发探测（`pet/window.py`）。
- 「切换人物」子菜单改为 `aboutToShow` 懒填充；`_available_characters()` 按目录 mtime 缓存（`pet/window.py`）。
- 退出路径等待在途探测线程（`pet/window.py` `_quit()`）。
- 验证：`py_compile` 通过；offscreen 冒烟测试通过（缓存命中、懒填充、克隆菜单 0.05ms、探测线程生命周期、退出清理）。
