# VoiceIME — Ubuntu 中文 / 中英混合语音输入

> 当前推荐版本：Sherpa 双语 Paraformer 流式识别（真人样本当前最优）。
> Zipformer hotword 路径保留为实验，但不会自动替换生产识别器。
> FireRedASR2 二次识别默认关闭，DeepSeek 后处理可选，最终通过 Fcitx5 原生提交。
> 原 Vosk/nerd-dictation 路径保留为兼容/回归测试，不再作为默认日用后端。

## 推荐安装（日用路径）

适用：Ubuntu 24.04 + GNOME + Fcitx5。当前 PTT 热键监听仍以 X11 为主。

已经完成首次依赖和模型安装时，日常更新直接运行：

```bash
./deploy.sh
```

脚本默认启用一句话结束后的 AI 纠错；运行中回答 `n` 可关闭。启用时可继续选择：

- `punctuation`：只调整标点和中英文空格，默认推荐。
- `aggressive`：允许修正错字和英文词，可能改变原意。
- DeepSeek 模型以及引擎等待纠错结果的超时时间。

CI 或其他非交互环境可以用 `VOICEIME_LLM_ENABLED`、
`VOICEIME_LLM_MODE`、`VOICEIME_LLM_TIMEOUT`、
`DEEPSEEK_MODEL` 提供相同配置。密钥只从项目根目录的 `.env` 读取。

```bash
# 1. 先构建并安装 Fcitx5 原生桥
sudo apt-get install -y g++ libfcitx5core-dev libfcitx5utils-dev libfcitx5config-dev
bash native/build.sh
bash native/install.sh
fcitx5 -r

# 2. 安装中英双语实时识别后端（生产默认 Paraformer）
bash scripts/09-setup-sherpa.sh

# 3. 可选：安装松键后的二次识别模型（默认关闭，先用真人录音 A/B）
bash scripts/11-setup-quality.sh

# 4. DeepSeek 后处理（默认开启；安全模式只允许标点/空格）
#    在 .env 里设 VOICEIME_LLM_ENABLED=0 可关闭
#    在项目根目录创建权限为 600 的 .env：
#    DEEPSEEK_API_KEY='...'
#    DEEPSEEK_BASE_URL='https://api.deepseek.com/anthropic'
#    DEEPSEEK_MODEL='deepseek-v4-flash'

# 5. 安装并启动用户级 systemd 服务
bash scripts/10-install-service.sh

# 6. 检查
./voiceime-status
journalctl --user -u voiceime-ptt -f
journalctl --user -u voiceime-corrector -f

> `voiceime-engine` 直接调用 DeepSeek 的 Anthropic 兼容接口，明确关闭
> thinking；不需要 OpenCode、cc-switch 或本地纠错服务。
> 换模型 / 换推理档：覆盖 `VOICEIME_CORRECTOR_ZEN_MODEL` /
> `VOICEIME_CORRECTOR_ZEN_REASONING`（low/medium/high/xhigh）。
```

### 使用

- **按住右 Alt**：开始说话，实时上屏。
- **松开右 Alt**：结束本句。FireRedASR2 默认关闭（本机真人样本中 FireRed 的中英混合结果更差，只应用 `VOICEIME_FINAL_ENABLED=1` 显式开启做 A/B）。LLM 后处理默认开启，`punctuation` 安全模式只接受标点/空格变化；任何中文、数字或英文实词变化都会被拒绝并保留 ASR 原文；想要更激进的纠错请设 `VOICEIME_LLM_MODE=aggressive`，想要完全关闭设 `VOICEIME_LLM_ENABLED=0`。
- 屏幕提示：录音时在当前活动显示器下方居中显示动态声波；AI 后处理显示“纠错中”，结束后短暂显示“纠错完成”“纠错失败”或“纠错超时”。提示窗不会获取键盘焦点。
- `Ctrl+Alt+V`：免手持开始/停止。
- `Ctrl+Alt+B`：结束当前听写。
- `./voiceime-reset`：异常时强制清理引擎和录音进程。

### 为什么不再默认使用 Vosk

真实使用中暴露出的三个问题——长时间使用卡死、中英混输差、中文准确率低——都和旧主链路有关。新链路做了这些调整：

1. **Vosk small-cn → Sherpa streaming Paraformer（中英双语）**，解决基础中文和 code-switch 能力不足。
2. **可选 FireRedASR2 第二遍纠错**：实时结果负责速度，松键后的离线 CTC 结果负责准确率。
3. **不再每个 partial 都启动一次 `busctl` 子进程**：优先使用一个持久化 Gio D-Bus 连接直达 Fcitx5。
4. **PTT supervisor 有超时恢复**：最终识别超过 4 秒未回到 idle 时直接重启引擎，而不是整套输入法永久卡住。
5. **每次听写独立 ASR stream / recorder**，一次异常不会污染下一次听写。

### 体验目标

当前目标是把日常中文与中英混合口述做到“可以替代大部分键盘输入”的 Alpha。是否达到“豆包输入法 80%”必须用同一批真人录音做 A/B 基准，不能只靠主观描述。后续以首字延迟、最终纠错延迟、中文 CER、中英 code-switch WER、连续 100 次 PTT 无卡死率作为验收指标。

### 中英混输领域词库

项目维护三套内置领域词库，并在启动前合并：

- `hotwords/programming.txt`：前端、后端、Git/GitHub、数据库、DevOps、AI、VoiceIME。
- `hotwords/work-tools.txt`：Stripe、Linear、Vercel、AWS 及常用子产品。
- `hotwords/dental.txt`：美国牙科供应商、品牌、产品和常用牙科术语。

Zipformer contextual-bias 路径经过 30 条真人录音 A/B 后没有达到上线门槛：
当前 Paraformer 的内容 CER / 中文 CER / 英文 token recall 分别为
12.23% / 8.22% / 58.54%；Zipformer+hotwords 最好一组（score=1.5）为
16.51% / 9.54% / 36.59%。因此生产流式识别继续固定使用 Paraformer。
Zipformer 仅保留为实验路径，不能为了词库牺牲现有中英文整体准确率。

个人词库放在：

```text
~/.config/voiceime/hotwords.txt
```

也可以直接用命令维护；修改后会重新生成合并词表并重启输入服务：

```bash
./voiceime-hotwords add "Henry Schein" "Darby Dental" "Stripe Checkout"
./voiceime-hotwords add "MyProject" "MyCompany"
./voiceime-hotwords list
./voiceime-hotwords remove "MyProject"
./voiceime-hotwords rebuild
```

实际传给 Sherpa 的合并文件是 `hotwords/compiled.txt`，它由脚本生成、不提交
到 Git。默认 hotword 分值通过 `VOICEIME_HOTWORDS_SCORE` 控制，识别后端通过
`VOICEIME_ASR_BACKEND=auto|paraformer|zipformer-hotwords` 控制。

### 用真人录音评测

`14-record-samples.sh` 产生的 manifest 可以直接交给当前识别链路。评测会同时报告内容、原始格式、英文词、数字和标点准确率，并把逐句结果写成 TSV：

```bash
python3 scripts/08-offline-suite.py \
  --manifest samples/voice-input-session-20260921-211507/manifest.tsv
```

默认使用日常路径（Sherpa streaming）。测试 FireRed 时临时加
`VOICEIME_FINAL_ENABLED=1`；不要仅因模型已经下载就默认启用。当前这批
30 条真人录音的 streaming 内容准确率为 90.66%，FireRed 为 82.71%。
这批数据参与了调优，只能作为开发集；最终准确率需要另录未参与调优的样本验收。

---

## Legacy POC documentation
> 项目代号：VoiceIME POC ｜ 版本 v0.1 ｜ 状态：执行中

## 核心目标

在 Ubuntu 上验证：**用户聚焦任意输入框 → 说中文 → 识别文字不经复制粘贴，直接进入当前输入框**。

## 环境

| 项目 | 值 |
|---|---|
| OS | Ubuntu 24.04.4 LTS |
| 桌面 | GNOME (ubuntu) |
| 显示协议 | X11 (`DISPLAY=:1`) |
| 日常输入 | Fcitx5 原生文字提交（Rime 可保持启用） |
| 旧版 POC 输入工具 | xdotool |
| ASR | Vosk（Python API） |
| 模型 | vosk-model-small-cn-0.22 |
| 采样率 | 16000 Hz（Vosk 中文模型要求） |

## 目录结构

```
laopan-voice-input-method/
├── nerd-dictation/          # 上游项目，含本地音频/信号/按键修复
├── models/
│   └── vosk-model-small-cn-0.22/
├── scripts/
│   ├── 01-setup.sh          # 环境准备（apt + pip + 模型下载）
│   ├── 02-asr-test.sh       # 验证录音+中文识别（结果输出到屏幕）
│   ├── 03-direct-input.sh   # 验证直接输入当前焦点窗口（核心）
│   ├── 04-latency-suite.sh  # 跑 PRD 测试用例并记录延迟
│   ├── 05-keyboard-shortcut.sh  # 配置 GNOME 快捷键 (P1)
│   ├── 06-app-compat.sh     # 应用兼容性测试
│   └── lib.sh               # 共享配置
└── logs/                    # 测试结果
```

## 快速开始

### 0. 真人语音测试（一键入口，推荐）

```bash
bash scripts/00-user-test.sh
```

依次运行：识别测试 → 直接输入测试 → 11 个延迟用例，全程只需说话+按回车。

### 1. 环境准备（一次性）

```bash
bash scripts/01-setup.sh
```

会执行：
- `sudo apt install xdotool unzip curl pulseaudio-utils`
- `pip3 install --user vosk`
- 下载并解压 `vosk-model-small-cn-0.22`（约 42MB）到 `models/`

### 2. 验证中文识别（录音 → 识别 → 输出到屏幕）

```bash
bash scripts/02-asr-test.sh
```

### 3. 验证直接输入（核心验证点）

```bash
bash scripts/03-direct-input.sh
```

先点击目标输入框获得焦点，然后说话，识别文字应直接进入输入框。

### 4. 跑测试用例 + 延迟记录

```bash
bash scripts/04-latency-suite.sh          # 全部 11 个用例
bash scripts/04-latency-suite.sh 1 5      # 只跑 1-5
```

### 5. 快捷键（P1）

```bash
bash scripts/05-keyboard-shortcut.sh
```

### 6. 应用兼容性（P1）

```bash
bash scripts/06-app-compat.sh
```

## 日常使用：按住右 Alt 说话（PTT）

日常服务通过本项目的 Fcitx5 插件直接提交 Unicode，仍然边说边输入。
GTK 输入框通过 surrounding-text 接口修正文字；终端通过输入法接口接收退格。
不再用 xdotool 逐个映射中文字，也不使用剪贴板。
目标程序需要连接 Fcitx5；如果输入焦点丢失，停止本次上屏。

插件源码在 `native/`。本机已安装；重新编译/安装时：

```bash
# 需要 g++、libfcitx5core-dev、libfcitx5utils-dev、libfcitx5config-dev
bash native/build.sh
bash native/install.sh
# 安装后重启 Fcitx5，再启动 voiceime-ptt 服务
```

安装脚本写入用户目录 `~/.local/share/fcitx5/addon/voiceime.conf`，引用
项目的 `build/libvoiceime.so`。移动项目后需要重新安装。插件使用当前用户的
D-Bus 会话，不需要 root。接口依据 [Fcitx5 InputContext API](https://github.com/fcitx/fcitx5/blob/5.1.7/src/lib/fcitx/inputcontext.h)。

```bash
systemctl --user enable --now voiceime-ptt   # 已配置，登录自动启动
./voiceime-status                            # 看守护进程 / 听写状态 / 当前麦克风
./voiceime-reset                             # 出问题时全部停掉
```

| 操作 | 行为 |
|---|---|
| **按住右 Alt** | 录音 + 边说边上屏；**松开**即停止并输出最后一段 |
| Ctrl+Alt+V | 免手持切换：按一下开始，再按一下停止 |
| Ctrl+Alt+B | 停止并上屏 |

### 设计

- **只允许一个 nerd-dictation 进程。** `begin` 会把自己的 PID 写进公共 cookie
  (`/tmp/nerd-dictation.cookie`)，第二次 `begin` 直接覆盖它，第一个实例就变成
  没人能通知到的孤儿——按 N 次热键就留 N 个实例，每个约 260MB 且各占一路麦克风。
- 所以进程由 `voiceime-ptt` 守护进程独占，用信号切换状态，不再反复 begin/end：

  | 信号 | 效果 |
  |---|---|
  | `SIGCONT` | 开始录音（`parec` 起来） |
  | `SIGUSR1` | 冲刷文字 → 关掉 `parec` → 进程自己 `SIGSTOP` |

  空闲时进程是 `T`（停止）状态：**0% CPU、不占麦克风**，但模型留在内存里
  （约 260MB），所以按下键 ~100ms 就能录，不用每次重载模型（~1-3s，会吞掉开头几个字）。
- **按键来源是 `xinput test-xi2 --root`**：GNOME 自己的快捷键只有按下事件、也绑不了
  单独的修饰键，做不了「按住说话」。右 Alt = keycode 108（`xmodmap -pke | grep Alt_R`），
  换布局时用 `VOICEIME_PTT_KEYCODE` 覆盖。自动重复的按下事件会被忽略。
- **忽略 XTEST 合成按键**：上屏时 `xdotool --clearmodifiers` 会产生修饰键松开/恢复
  事件，这些事件不能当作真人的 PTT 操作。文字修正的退格也会清除修饰键，避免变成
  Alt+BackSpace 等应用快捷键。仍然保留边说边输入。
  日常服务已改用 Fcitx5；这些防护继续用于旧版 xdotool 测试路径。
- **及时读取积压音频**：每轮读取当前可用数据，保留不足完整 PCM 采样的碎片。
  日常服务每 20ms 检查一次输入，避免较慢的识别/输出让录音积压到松键才处理。
- **暂停在主循环处理**：信号只记录请求，不在信号处理器中再次调用 Vosk 或启动
  按键输出。暂停前停止并读完录音缓冲，回收录音子进程，再冲刷最后的文字。
- **独立状态文件**：日常服务使用 `$XDG_RUNTIME_DIR/voiceime-<uid>.cookie`
  （无运行目录时使用 `/tmp`），与手动测试的默认 cookie 隔离。
- **麦克风每次按键重新解析**（`voiceime-mic`）：优先当前默认输入（若是 USB）→ 任意 USB
  输入 → 当前默认 → 任意输入。换了 USB 麦克风或重新插拔导致设备名变化时，
  守护进程会用新设备重启听写进程（那一次按键会慢 1-3s）。

### 文件

| 文件 | 作用 |
|---|---|
| `voiceime-ptt` | 守护进程：持有唯一听写进程 + 监听右 Alt |
| `voiceime-mic` | 解析该用哪个麦克风（优先 USB） |
| `voiceime-lib.sh` | 共用：单实例锁、状态查询、信号收发 |
| `voiceime-begin` / `voiceime-end` | Ctrl+Alt+V / Ctrl+Alt+B |
| `voiceime-status` / `voiceime-reset` | 查看状态 / 全部停掉 |
| `~/.config/systemd/user/voiceime-ptt.service` | 随图形会话自启，异常自动重启 |

> 右 Alt 仍然是普通 Alt 键，按住时其它程序也会当成 Alt。若不想要这个副作用，可以把它
> 映射掉：`xmodmap -e 'keycode 108 = VoidSymbol'`（xinput 读的是映射前的 keycode，PTT 不受影响）。

## 手动使用（原版 nerd-dictation）

```bash
# 开始听写（模型目录用绝对路径）
/mnt/data/james/Documents/sidework/laopan-voice-input-method/nerd-dictation/nerd-dictation begin \
    --vosk-model-dir /mnt/data/james/Documents/sidework/laopan-voice-input-method/models/vosk-model-small-cn-0.22 \
    --sample-rate 16000 \
    --defer-output

# 说话...

# 结束听写（触发识别并输入当前窗口）
/mnt/data/james/Documents/sidework/laopan-voice-input-method/nerd-dictation/nerd-dictation end
```

## 技术说明

- `end` 命令只是 touch 一个 cookie 文件，后台 `begin` 进程检测到后执行最终识别并上屏。
- `--defer-output`：说话过程中不上屏，结束时一次性输入（适合短句测试）。
- 不使用时 `cancel` 命令可丢弃本次录音。
- Vosk 中文模型（small-cn-0.22）要求 16kHz 采样率。
- xdotool 输入基于 XTEST，**仅 X11 可用**；Wayland 需 ydotool（需要 root 服务）。

## 已知问题

1. **GNOME/mutter 程序化焦点不稳定**：自动化测试需 `windowactivate`+点击组合；真人场景由用户手动聚焦，不受影响。
2. **xdotool 需 LD_LIBRARY_PATH 包装**（源码编译版）：已提供 `~/.local/bin/xdotool` 包装脚本。
3. **Vosk small 模型中英混合识别差**（24-58% 重合率）；短/中句可用（80%+）。
4. **声学回环（扬声器→mic）降质**：回环测试识别率低于真人语音，真人测试为准。
5. **xdotool 仅 X11**：Wayland 需 ydotool（root 服务），POC 限定 X11。
6. **fcitx5 兼容性待测**：fcitx 激活态下的直接输入需真人语音确认。

完整结论见 `POC-REPORT.md`（结论 B：POC 部分通过，先完成真人语音验证再二开）。

## 测试记录

- 回归检查：`python3 -m unittest discover -s tests -v`（不录音、不向桌面打字）。
- 2026-09-08 修复验证：隔离 X11 桌面中，以 16kHz 录音重放、真实 Vosk 和 xdotool
  连续测试 3 次即时上屏，约 1 秒出现首段文字；按住 Alt 的中文退格修正通过。
  此项不替代当前麦克风的真人语音验收。
- 后续原生输入验证：Fcitx5 + GTK4 连续 3 次实时识别上屏通过；首段文字约
  1 秒出现；VTE/Bash 终端按住 Alt 的中文输入与修正通过。原生接口测试还覆盖
  焦点丢失、拒绝删除本次听写之前的文字，源码见 `tests/native_bridge.py`。
  耗时日志只记录字符数，不保存识别内容，可用 `journalctl --user -u voiceime-ptt` 查看。

- 见 `logs/` 下的 `latency_results_*.tsv` 与 `app_compat_*.tsv`。
- POC 报告：`POC-REPORT.md`。
