---
title: "VoiceIME：Linux 上唯一免费的中文 / 中英混合语音输入法，对标豆包 80% 体验"
date: 2026-09-22
tags: [voice-input, linux, asr, fcitx5, side-project, free]
summary: Linux 上按住右 Alt 就能说话、中文带标点直接上屏。30 条真人样本 90.66% 内容准确率。一条 deploy.sh 完成安装。永久免费、开源。
project_url: https://voiceime.mogician.me
github_url: https://github.com/panjiangyi/laopan-voice-input-method
---

# VoiceIME：Linux 上唯一免费的中文 / 中英混合语音输入法，对标豆包 80% 体验

![status](https://img.shields.io/badge/status-alpha-9fe870) ![accuracy](https://img.shields.io/badge/30%20samples-90.66%25-9fe870) ![ubuntu](https://img.shields.io/badge/ubuntu-24.04-E95420) ![price](https://img.shields.io/badge/price-free-9fe870)

> 项目主页：[voiceime.mogician.me](https://voiceime.mogician.me) · 源码：[github.com/panjiangyi/laopan-voice-input-method](https://github.com/panjiangyi/laopan-voice-input-method) · 一个我每天都在用的 side project。

## 一句话

在 Ubuntu 上，**按住右 Alt 说话，松键后整句带标点直接上屏**——和微信、Notion、VS Code、终端里的"说一段就出来一段"是同一件事。

不是 demo，不是技术 PoC。我从今年 8 月开始用它替换大部分中文 / 中英混合输入。

## 这个项目解决的是什么

三个长期问题叠加：

1. **Linux 上没有免费的中文语音输入法**。macOS 用户可以用 typeless（付费）或系统听写（优秀），Windows 用户有微软语音输入法。Linux 上你只剩两件事：放弃中文语音输入，或者自己撸一个。
2. **typeless 是收费的**。typeless 本身是个好产品，但订阅制 + macOS only，Linux 用户根本用不上。
3. **豆包输入法没有 Linux 版**。豆包在中文识别上是体验天花板之一，但官方至今没有 Linux 客户端。

VoiceIME 的定位很直白：**把 typeless / 豆包那种"按住说话直接上屏"的体验，免费做到 Linux 上**。当前在我自己的真人样本上，内容准确率是 90.66%（30 条未公开样本）——距离豆包的体验还有距离，但作为免费的 Linux 替代，已经能日用。

## 为什么免费

因为这本来就不该是收费的东西。

- 模型是开源的（Sherpa streaming Paraformer、FireRedASR2）。
- 输入法协议是开源的（Fcitx5）。
- 我做这件事的成本是周末时间 + 一台麦克风好的开发机。
- 收费解决不了"Linux 用户用不上语音输入法"这件事——只会让一部分人用不上。

**typeless 的免费替代，就是 VoiceIME 的目标。** 开源不是慈善，是商业模型决定不了的"长尾平台用户"问题，开源能解决。

## 怎么做到的：一条管线

按一次右 Alt 发生的全部事情，按时间顺序：

```
Right Alt down
  │
  ▼
parec 16k PCM ─────► Sherpa streaming Paraformer（中英）
                            │ partial
                            ▼
                  voiceime-ptt supervisor
                  · 100ms 内恢复 idle
                  · 每 20ms 拉一次音频，避免积压
                  · 持久 Gio D-Bus 直连 Fcitx5（不再每 partial 启 busctl）
                            │ final transcript
                            ▼
                  DeepSeek punctuation-only   ← 默认开启
                  mode = punctuation（只补标点 / 空格）
                            │
                            ▼
                  Fcitx5 native commit        ← GTK surrounding-text / VTE backspace
                            │
                            ▼
                  当前焦点输入框 ← 真正上屏

Optional: 松键后接 FireRedASR2 二遍纠错（默认关闭，需 VOICEIME_FINAL_ENABLED=1）
```

几个有意思的设计选择：

- **每 20ms 拉一次音频**。如果识别 / 输出变慢，音频会积压到松键才处理——首字延迟看起来"还行"，但尾段经常吞字。改成每 20ms 检查一次输入后，识别器永远不会被甩在后面。
- **持久 Gio D-Bus 直连 Fcitx5**。旧实现每个 partial 都 `busctl call` 一次——子进程冷启动 + 鉴权，平均 30–80ms。改成持久连接后，partial 上屏 < 5ms。
- **PTT supervisor 有超时恢复**。最终识别超过 4 秒未回到 idle，直接重启引擎而不是整套输入法永久卡住。
- **每次听写独立 ASR stream / recorder**。一次异常不会污染下一次听写——这是和旧链路最大的体感差距。
- **DeepSeek 默认只补标点**。aggressive 模式理论上可以改错字，但风险是改掉"我故意说的词"（人名、产品代号、口头禅）。默认 `punctuation` 模式只接受标点和中英文空格变化，任何中文 / 数字 / 英文实词变化都会被拒绝并保留 ASR 原文。

## 真人评测，不用嘴炮

不放故事，放数字。30 条日常真人样本（不是 Wenet 测试集），覆盖不同长度、口音、中英混说比例。同一份 manifest 在两条链路上跑：

| 指标 | Sherpa streaming（默认） | FireRedASR2（可选） | 备注 |
|---|---|---|---|
| 内容准确率 | **90.66%** | 82.71% | 这批数据参与了调优，只能做开发集 |
| 首字延迟 | ≈ 1.0s | n/a | 首字即可在 Fcitx5 预编辑区出现 |
| 标点纠错延迟 | ≈ 0.8s | — | 仅在松键后发生，不阻塞边说边显示 |
| 100 次 PTT 无卡死率 | pass | — | supervisor 4s 超时直接重启引擎 |

几个非显然的发现：

- **FireRedASR2 在真人样本上反而更差**（82.71% vs 90.66%）。这跟我之前的假设相反——更"大"的离线模型不是必胜。最终识别里 FireRed 更倾向把"嗯"扩展成完整句子，结果反而错了。这是个让我记住的教训：**评测必须用真人数据，不能用论文 benchmark 替代表决**。
- **最终验收需要另录未参与调优的样本做盲测**。当前这 30 条参与了调优，本质是开发集。我会在未来 1-2 周内重新录 50 条未参与调优的样本做最终 A/B——在那之前，"对标豆包 80% 体验"是开发机上的体感估计，不是跨数据集的硬指标。

## 对比一下：免费 + Linux 这个交叉格里只有 VoiceIME

|  | VoiceIME | typeless | 豆包输入法 | nerd-dictation |
|---|---|---|---|---|
| 价格 | **永久免费** | 订阅制 | 免费 | 免费 |
| Linux 桌面 | **原生支持** | — | — | 支持 |
| 中文识别 | 90.66% | 优秀 | 顶级 | 弱 |
| 中英混输 | Sherpa 双语流式 | 支持 | 支持 | 弱 |
| 输入法上屏 | Fcitx5 原生 | 系统输入法 | 系统输入法 | xdotool 模拟 |
| 开源 | **是** | 否 | 否 | 是 |

**结论**：在"价格 + Linux 支持"两格的交叉格里，目前只有 VoiceIME 一个选项。typeless 不出 Linux，豆包没有 Linux 版，nerd-dictation 不支持中文。

## 为什么不用 xdotool / 剪贴板

不是装，是真的不行：

- **xdotool + XTEST**：在 GNOME 下经常被 mutter 的焦点管理吃掉；按住的修饰键会触发应用快捷键（Alt+Backspace、Alt+F4 之类）；中文需要 unicode 输入，得切输入法状态。每个坑都是不可预测的。
- **剪贴板**：一粘贴就破坏 surrounding-text——你不知道当前光标在句子的哪里、周围有没有待替换的选中文本、IME 状态是不是要清空。所有输入法都假设"我是被 InputContext 调用的"，剪贴板这条路走不通。
- **Fcitx5 + 持久 Gio D-Bus**：把文字作为 Unicode commit 给当前 IC，GTK 走 surrounding-text，Qt / VTE 走 backspace + commit。**输入法怎么干的，我就怎么干**。

## 怎么装的

Ubuntu 24.04 + GNOME + Fcitx5，PTT 热键监听仍以 X11 为主。

```bash
# 0. 装依赖和模型（一次性，详见 README）
sudo apt-get install -y g++ libfcitx5core-dev libfcitx5utils-dev libfcitx5config-dev
bash native/build.sh && bash native/install.sh && fcitx5 -r
bash scripts/09-setup-sherpa.sh
bash scripts/11-setup-quality.sh   # 可选：FireRedASR2

# 1. DeepSeek 后处理：项目根 .env，权限 600
cat > .env <<'EOF'
DEEPSEEK_API_KEY='...'
DEEPSEEK_BASE_URL='https://api.deepseek.com/anthropic'
DEEPSEEK_MODEL='deepseek-v4-flash'
EOF
chmod 600 .env

# 2. 用户级 systemd 服务
bash scripts/10-install-service.sh
```

之后日常更新一行：

```bash
./deploy.sh
```

默认开启 AI 标点纠错；想关闭：`VOICEIME_LLM_ENABLED=0 ./deploy.sh`。

## 现在的边界

**已经能做到**：中英混合 streaming 上屏、90.66% 真人内容准确率、DeepSeek punctuation-only 安全纠错、PTT supervisor 4s 必重启、100 次 PTT 无卡死、Fcitx5 原生提交（GTK / Qt / VTE / 终端均通过）、完全开源、永久免费。

**明确还没做**：Wayland（当前 X11 为主，Wayland 需要 ydotool）、多说话人分离（会议场景）、个人热词 / 替换表（行业词、口头禅）、更激进的纠错模式（aggressive 默认不开，避免改实词）、未参与调优的盲测集（当前数字只是开发集）。

## 你来试，然后告诉我数字

VoiceIME 现在的状态是"日用级 alpha"。它已经能替代我大部分中文 / 中英混合输入，但还差 Wayland 适配、差未参与调优的盲测集、差个人热词。

**特别想知道**：

- 在你的麦克风 / 口音 / 说话速度下，**90.66% 这个数字是天花板还是地板**？
- 中英混输在你的工作流里占比多少？（我的 > 30%，所以中英混输好是 day-1 需求）
- 你最想要但现在没有的功能是什么？（Wayland？热词？aggressive 纠错？）

如果你是 Linux 上日常需要中文 / 中英混合输入的人，欢迎来 [voiceime.mogician.me](https://voiceime.mogician.me) 看看，或者直接装：

```bash
git clone https://github.com/panjiangyi/laopan-voice-input-method
cd laopan-voice-input-method
./deploy.sh
```

源码：[github.com/panjiangyi/laopan-voice-input-method](https://github.com/panjiangyi/laopan-voice-input-method) · 主页：[voiceime.mogician.me](https://voiceime.mogician.me)
