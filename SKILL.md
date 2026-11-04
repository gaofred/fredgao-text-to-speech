---
name: fredgao-text-to-speech
description: 把英文文本转成朗读 mp3，音色可选（14 种口音、45 个音色，覆盖英音/美音/澳音/加音/爱尔兰/印度/新西兰/南非/新加坡/中国香港/菲律宾/肯尼亚/尼日利亚/坦桑尼亚），带试听页让用户先挑音色再配音。中文别名"转语音 / 文本转语音 / 配音 / 朗读 / 读一遍 / 念一下 / TTS / 给我读 / 音色 / 英音 / 美音 / 换个声音 / 换个人声 / 男声 / 女声 / 口音"。当用户说"把这段转成语音""读出来听听""用英音读""换个男声""有什么音色"时使用。引擎 Microsoft Edge TTS，免费无需密钥；长文本自动分块拼接；可顺手生成单文件 HTML 播放页。 | 作者：Fred老师 | 公众号：佛瑞德英语教学
agent_created: true
---

# text-to-speech（文本 → 朗读 mp3，音色可选）

## 环境（本机已就绪）

- Python：`/Users/foruide/.workbuddy/binaries/python/envs/default/bin/python`（edge-tts ≥7.3.1 + python-docx）
- 脚本：`~/.workbuddy/skills/fredgao-text-to-speech/scripts/tts.py`
- 试听页生成器：同目录 `make_audition.py` → 产出 `../assets/voices.html`
- 健康自检：同目录 `check_voices.py`
- ffmpeg：优先 `~/.workbuddy/skills/generatevoice/bin/ffmpeg`，其次系统 `/opt/homebrew/bin/ffmpeg`（长文本拼接用）
- **edge-tts 必须 ≥7.3.0**：7.3 起改用 v2 签名（CS64+SHA256 双重摘要），7.2.x 及更早一律
  `WSServerHandshakeError: 403`。脚本启动时会自检版本并提示。

## 原理（一句话版，出故障时靠这个判断）

不是 Azure 官方 Speech API，而是**复用了 Edge 浏览器「大声朗读」的后台端点**
`wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1`。
免费、无 API Key，靠三样东西过门：公开的 `TrustedClientToken` 常量、
`Sec-MS-GEC`（当前时间向下取整到 5 分钟再签哈希，等同"时间派生签名"）、随机 `ConnectionId`。

握手后发两帧：一帧声明输出格式 `audio-24khz-48kbitrate-mono-mp3`，一帧发 SSML
（`<voice name=...><prosody rate=...>`）。服务端回二进制 mp3 流，`turn.end` 收尾。

**推论**：
- 换音色 = 换 SSML 里 `voice name` 的字符串，不是换模型端点
- 签名每 5 分钟变一次，所以没人能硬编码一个永久地址 → 这是微软**主动防刷**的手段，
  算法一变旧客户端就全挂（我们上午就是这么碰到 403 的）
- `--list-voices` 只是服务端的一份**目录**，列得出来 ≠ 能发声（`leah`/`wayne` 即此）
- 单次消息在库内 4096 字节处切块，超长文本必须靠分块+拼接，不要指望一次发完

**这不是"随时会停服"的东西，是会悄悄失效的东西。** 教学配音完全够用；
但不要拿它做面向学生长期运营的服务（无 SLA、无支持、随时可能因算法变更断掉）。

## 出问题时的判断顺序（先跑自检，别猜）

```bash
$PY ~/.workbuddy/skills/fredgao-text-to-speech/scripts/check_voices.py --quick   # 每个口音抽 1 个，约 30 秒
$PY ~/.workbuddy/skills/fredgao-text-to-speech/scripts/check_voices.py           # 全量 45 个，约 2 分钟
```

自检会给出**归因结论**，直接照着做：

| 自检结论 | 含义 | 处理 |
|---|---|---|
| 全部音色可发声 | 服务正常 | 问题在输入或参数，检查文件路径/文本 |
| 全部 403 被拒 | edge-tts 版本旧，签名对不上 | `pip install -U edge-tts` |
| 全部失败（非 403） | 网络或服务端故障 | 查网络能不能连 `speech.platform.bing.com` |
| 少数几个无响应 | **这几个音色本身下线了** | 换同口音其他音色，把别名加进 `UNAVAILABLE` |

**别做的三件事**：不要因为 403 去改脚本（是版本问题）；不要因为单个音色哑就怀疑环境；
不要在不确认的情况下批量生成几十条（先跑一条小样）。


## 让用户"选音色"的标准流程

用户要配音但没指定音色时，**不要把 45 个音色当文字列表刷屏**，按这个顺序：

1. **先给试听页**：`~/.workbuddy/skills/fredgao-text-to-speech/assets/voices.html`
   单文件（音频 base64 内嵌），双击即听。45 个音色同一句横向对比，按 14 个口音分组，
   顶部可按口音筛选（常用 6 个大按钮 + 其余 8 个下拉），可连播。
   用 `present_files` 打开，然后说一句"点卡片试听，告诉我要哪个"。
2. **用户回话后直接配**：认四种说法——
   - 别名：`aria`、`sonia`、`ryan`、`neerja-x`
   - 序号：`44`（对应 `--list` 里的编号，1–45）
   - 描述：`英音男声` → `--accent gb --gender m`；`港式英语` → `--accent hk`
   - 只要名字：`aria`、`sonia`（自动匹配到完整音色名）
3. 用户说"就这个""随便"→ 用 `aria`（美音女声，最接近高考听力）并说明一声。

选完可以顺手记一句到用户级 MEMORY：`配音默认音色：<别名>`，下次不用再问。

## 用法

```bash
PY=/Users/foruide/.workbuddy/binaries/python/envs/default/bin/python
S=~/.workbuddy/skills/fredgao-text-to-speech/scripts/tts.py

# 列音色（带中文名和适用场景）
$PY $S --list
$PY $S --list --accent gb          # 只看英音
$PY $S --list --accent hk --gender f   # 港式英语女声
$PY $S --list --all                # 直接读 edge-tts 原始清单（无中文名）

# 文本 → mp3
$PY $S -t "英文段落..." -o out.mp3 --voice aria
$PY $S passage.txt -o out.mp3 --accent gb --gender m     # 英音男声（→ ryan）
$PY $S passage.docx -o out.mp3 --voice 44                # 按序号（44 → imani）
$PY $S passage.txt --speed slow                          # 慢速 -15%

# 顺手出单文件 HTML 播放页（1.0/0.85/0.7 倍速 + 进度条）
$PY $S -t "..." -o out.mp3 --voice sonia --html

# 健康自检（出问题先跑这个，别猜）
$PY $S --check --quick              # 每个口音抽 1 个，约 30 秒
$PY $S --check                      # 全量 45 个，约 2 分钟
$PY $S --check --accent gb          # 只查英音
```

参数：
| 参数 | 说明 |
|---|---|
| `--voice` | 别名 / 完整名 / 序号（1–45） |
| `--accent` | us gb au ca ie in nz za sg hk ph ke ng tz（也认 uk、英音、美音、英式） |
| `--gender` | f / m（也认 女 / 男 / 女声 / 男声） |
| `--speed` | slower(-25%) slow(-15%) normal fast(+10%) faster(+20%) |
| `--rate` | 原始值，**必须等号形式** `--rate=-15%` |
| `--pitch` `--volume` | `--pitch=+2Hz` `--volume=+10%` |
| `--html` | 额外生成播放页 |
| `--no-concat` | 长文本按块各存 01/02/03，不拼接 |
| `--check` | 音色健康自检（可配 `--quick` / `--accent`） |

输入支持 `-t` 直接给文本、`.txt` / `.md` / `.docx`（docx 会连表格一起读）。旧版 `.doc` 要先另存为 docx。

> 最近一次全量音色自检：**2026-10-28T18:08:29+08:00**（`python scripts/check_voices.py`）

## 音色一览（45 个，全部实测可发声）

`--list` 按口音分组打印，序号连续 1–45，`--voice N` 直接用序号。

| 口音 | 女声 | 男声 |
|---|---|---|
| 美音 US (17) | aria（最像高考听力）、jenny、ava、emma、michelle、ana（童声）、ava-ml、emma-ml | guy、andrew、christopher、brian、eric、roger、steffan、andrew-ml、brian-ml |
| 英音 UK (5) | sonia（BBC 播报）、libby、maisie（少女） | ryan、thomas |
| 澳音 AU (2) | natasha | william |
| 加音 CA (2) | clara | liam |
| 爱尔兰 IE (2) | emily | connor |
| 印度 IN (3) | neerja、neerja-x（情感版） | prabhat |
| 新西兰 NZ (2) | molly | mitchell |
| 南非 ZA (1) | — | luke |
| 新加坡 SG (1) | luna | — |
| 中国香港 HK (2) | yan | sam |
| 菲律宾 PH (2) | rosa | james |
| 肯尼亚 KE (2) | asilia | chilemba |
| 尼日利亚 NG (2) | ezinne | abeo |
| 坦桑尼亚 TZ (2) | imani | elimu |

**为什么是 45 而不是 edge-tts 列出的 47**：`en-ZA-LeahNeural`（南非女）和
`en-SG-WayneNeural`（新加坡男）在免费端点上始终返回 `NoAudioReceived`——`--list-voices`
能列出但发不出声，重试 3 次均失败，同组的 luke / luna 正常。这两个已从 `VOICES` 移除，
**所以南非只剩男声、新加坡只剩女声**。以后若微软修好，把两条补回 `VOICES` 表即可（文件内有注释）。

**`-ml` 结尾**是同一说话人的 Multilingual 模型版，纯英文朗读与普通版差别很细微，
除非要读中英混排，否则用普通版即可。

加音色：改 `tts.py` 的 `VOICES` 表（按口音分组，顺序即序号），再 `make_audition.py --refresh`。
只重合某几条样音：`make_audition.py aria sonia`。

## 坑位

1. **`--rate -15%` 会被 argparse 当成选项**报 `expected one argument`。必须 `--rate=-15%`；日常用 `--speed slow` 更省事。
2. **长文本必须分块**：库自己在单帧 4096 字节处切，但那是"不出错"的下限、不是"接得顺"的上限。
   `chunk_text()` 按句切、攒到 1200 字符一块（约 2-4 句），块间 ffmpeg 补 0.15s 静音再 concat，
   听感上接缝不明显。别指望一次发完 4000 字。
3. **ffmpeg 滤镜图少一个 `;` 就报 `No such filter: ''`**：每条 `[i:a]apad=...[ai]` 是独立滤镜要分号隔开，最后一条才是 `concat`。
4. **样音必须压缩**：45 条原样约 2.5MB，`make_audition.py` 自动转 32kbps 单声道压到 1.4MB。再压到 16k 人声发闷，32k 是下限。
5. **`-o` 省略时默认落在当前工作目录**，命名取文件名或 `speech.mp3`。批量跑时建议显式给 `-o`。
6. docx 里的表格要单独遍历（`document.paragraphs` 不含表格），合并单元格 `row.cells` 会重复返回同一 `<w:tc>`，用 `cell._tc` 做 key 去重。
7. **不是所有 `--list-voices` 里的音色都能发声**。音色会**无声下线**：目录还列着，合成返回
   `NoAudioReceived`。所以"表里有"不等于"能用" —— 这就是要有 `check_voices.py` 的原因，
   也是 `UNAVAILABLE` 集合存在的原因。批量生成前先 `--check --quick`。
8. **重试对 403 和 NoAudioReceived 都无效**：前者是签名对不上（版本问题），后者是音色真哑了。
   脚本对这两类直接放弃重试并给出归因提示，不要给它们加更多 retry。
9. **`--list-voices` 返回 47 个，我们只用 45 个**。差的两个已剔除，别以为数量对不上是代码错。

## 定期维护

音色会悄悄失效，`SKILL.md` 顶部的检测时间就是新鲜度标记。建议换机器、升级 edge-tts、
或发现某音色出问题时跑一次：

```bash
$PY scripts/check_voices.py --update-stamp    # 全量自检并更新时间戳
```

自检不通过时退出码为 1，可以直接挂定时任务告警。

## 交付

- 把 mp3 用 `present_files` 给用户（可直接播放）
- 顺带说一句用了哪个音色："索尼娅，英音女声，标准 BBC 播音感"
- 用户要网页内嵌：用 `--html` 生成的单文件页，或把 mp3 压到 24kbps 后 base64 塞进现有页面
