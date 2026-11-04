#!/usr/bin/env python3
"""text-to-speech —— 英文文本转朗读 mp3（音色可选）

引擎：Microsoft Edge TTS（免费、无需 API key、神经音色）
ffmpeg：长文本分块后拼接用

用法:
  # 1) 直接给文本
  python tts.py -t "The passage goes here..." -o out.mp3 --voice aria

  # 2) 给文件（.txt / .md / .docx）
  python tts.py passage.txt --voice sonia --speed slow

  # 3) 挑音色
  python tts.py --list                 # 表格列出全部推荐音色
  python tts.py --list --accent gb     # 只看英音
  python tts.py --list --accent us --gender f

参数:
  --voice V     音色：别名(aria/sonia/ryan...) 或完整名(en-US-AriaNeural) 或序号(3)
  --accent A    us / gb / au / ie / ca / in / nz / za / sg / hk
  --gender G    f / m
  --speed S     slow(-15%) / slower(-25%) / normal(0%) / fast(+10%) / faster(+20%)
  --rate R      原始语速，如 "--rate=-15%"（等号形式！）
  --pitch P     音高偏移，如 "--pitch=+2Hz"
  --volume V    音量，如 "--volume=+10%"
  -o OUT        输出 mp3 路径
  --html        额外生成单文件 HTML 播放页（音频 base64 内嵌）
  --no-concat   长文本时不拼接，按块输出 01.mp3 02.mp3 ...
"""
import argparse
import asyncio
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- 音色表
# 全量 47 个英语音色，按口音分组（顺序 = --list 的序号，改顺序会改变序号）
# 字段：(完整名, 别名, 中文名, 口音, 性别, 特点)
# 别名带 -ml = 同一说话人的 Multilingual 模型版，纯英文朗读与普通版差别很细微
VOICES = [
    # ---- 美音 US (17) ----
    ("en-US-AriaNeural", "aria", "阿丽亚", "us", "f", "新闻播报感，最接近高考听力"),
    ("en-US-JennyNeural", "jenny", "珍妮", "us", "f", "亲切平稳，适合跟读"),
    ("en-US-AvaNeural", "ava", "艾娃", "us", "f", "表现力强，适合叙事文"),
    ("en-US-EmmaNeural", "emma", "艾玛", "us", "f", "明亮活泼，适合对话"),
    ("en-US-MichelleNeural", "michelle", "米歇尔", "us", "f", "温和亲切，不抢戏"),
    ("en-US-AnaNeural", "ana", "安娜", "us", "f", "童声，适合低龄角色对话"),
    ("en-US-AvaMultilingualNeural", "ava-ml", "艾娃·多语", "us", "f", "同艾娃，多语言模型版"),
    ("en-US-EmmaMultilingualNeural", "emma-ml", "艾玛·多语", "us", "f", "同艾玛，多语言模型版"),
    ("en-US-GuyNeural", "guy", "盖伊", "us", "m", "有力沉稳，适合议论性文本"),
    ("en-US-AndrewNeural", "andrew", "安德鲁", "us", "m", "温暖自信，自然口语"),
    ("en-US-AndrewMultilingualNeural", "andrew-ml", "安德鲁·多语", "us", "m", "同安德鲁，多语言模型版"),
    ("en-US-BrianNeural", "brian", "布莱恩", "us", "m", "随和，像真人在说话"),
    ("en-US-BrianMultilingualNeural", "brian-ml", "布莱恩·多语", "us", "m", "同布莱恩，多语言模型版"),
    ("en-US-ChristopherNeural", "christopher", "克里斯托弗", "us", "m", "权威可靠，适合说明文"),
    ("en-US-EricNeural", "eric", "埃里克", "us", "m", "理性冷静，语速匀"),
    ("en-US-RogerNeural", "roger", "罗杰", "us", "m", "活泼有起伏，适合故事"),
    ("en-US-SteffanNeural", "steffan", "斯特凡", "us", "m", "理性克制，适合科普"),
    # ---- 英音 UK (5) ----
    ("en-GB-SoniaNeural", "sonia", "索尼娅", "gb", "f", "标准 BBC 播音，英音首选"),
    ("en-GB-LibbyNeural", "libby", "莉比", "gb", "f", "自然亲切，不那么播音腔"),
    ("en-GB-MaisieNeural", "maisie", "梅茜", "gb", "f", "少女声，适合青少年角色"),
    ("en-GB-RyanNeural", "ryan", "瑞安", "gb", "m", "清爽清晰，英音男声首选"),
    ("en-GB-ThomasNeural", "thomas", "托马斯", "gb", "m", "沉稳，适合正式语篇"),
    # ---- 澳音 AU (2) ----
    ("en-AU-NatashaNeural", "natasha", "娜塔莎", "au", "f", "澳洲口音女声，元音偏扁"),
    ("en-AU-WilliamMultilingualNeural", "william", "威廉", "au", "m", "澳洲口音男声"),
    # ---- 加音 CA (2) ----
    ("en-CA-ClaraNeural", "clara", "克拉拉", "ca", "f", "加拿大口音女声，近美音"),
    ("en-CA-LiamNeural", "liam", "利亚姆", "ca", "m", "加拿大口音男声，近美音"),
    # ---- 爱尔兰 IE (2) ----
    ("en-IE-EmilyNeural", "emily", "艾米莉", "ie", "f", "爱尔兰口音女声"),
    ("en-IE-ConnorNeural", "connor", "康纳", "ie", "m", "爱尔兰口音男声"),
    # ---- 印度 IN (3) ----
    ("en-IN-NeerjaNeural", "neerja", "妮尔佳", "in", "f", "印度口音女声，清晰"),
    ("en-IN-NeerjaExpressiveNeural", "neerja-x", "妮尔佳·情感", "in", "f", "同妮尔佳，语气更起伏"),
    ("en-IN-PrabhatNeural", "prabhat", "普拉巴特", "in", "m", "印度口音男声"),
    # ---- 新西兰 NZ (2) ----
    ("en-NZ-MitchellNeural", "mitchell", "米切尔", "nz", "m", "新西兰口音男声"),
    ("en-NZ-MollyNeural", "molly", "莫莉", "nz", "f", "新西兰口音女声"),
    # ---- 南非 ZA (2) ----
    ("en-ZA-LukeNeural", "luke", "卢克", "za", "m", "南非口音男声"),
    # ---- 新加坡 SG (2) ----
    ("en-SG-LunaNeural", "luna", "露娜", "sg", "f", "新加坡口音女声"),
    # ---- 中国香港 HK (2) ----
    ("en-HK-YanNeural", "yan", "欣", "hk", "f", "港式英语女声"),
    ("en-HK-SamNeural", "sam", "山姆", "hk", "m", "港式英语男声"),
    # ---- 菲律宾 PH (2) ----
    ("en-PH-RosaNeural", "rosa", "罗莎", "ph", "f", "菲律宾口音女声"),
    ("en-PH-JamesNeural", "james", "詹姆斯", "ph", "m", "菲律宾口音男声"),
    # ---- 肯尼亚 KE (2) ----
    ("en-KE-AsiliaNeural", "asilia", "阿西莉亚", "ke", "f", "肯尼亚口音女声"),
    ("en-KE-ChilembaNeural", "chilemba", "奇伦巴", "ke", "m", "肯尼亚口音男声"),
    # ---- 尼日利亚 NG (2) ----
    ("en-NG-EzinneNeural", "ezinne", "埃津妮", "ng", "f", "尼日利亚口音女声"),
    ("en-NG-AbeoNeural", "abeo", "阿贝奥", "ng", "m", "尼日利亚口音男声"),
    # ---- 坦桑尼亚 TZ (2) ----
    ("en-TZ-ImaniNeural", "imani", "伊曼妮", "tz", "f", "坦桑尼亚口音女声"),
    ("en-TZ-ElimuNeural", "elimu", "埃利穆", "tz", "m", "坦桑尼亚口音男声"),
]

ACCENT_CN = {
    "us": "美音 US", "gb": "英音 UK", "au": "澳音 AU", "ca": "加音 CA",
    "ie": "爱尔兰 IE", "in": "印度 IN", "nz": "新西兰 NZ", "za": "南非 ZA",
    "sg": "新加坡 SG", "hk": "中国香港 HK", "ke": "肯尼亚 KE", "ng": "尼日利亚 NG",
    "ph": "菲律宾 PH", "tz": "坦桑尼亚 TZ",
}
# 试听页筛选条只放这几个常用口音，其余归入「其他」
MAIN_ACCENTS = ["us", "gb", "au", "ca", "ie", "in"]

# 2026-10-28 实测：edge-tts 的 --list-voices 列出 47 个英语音色，但其中
# en-ZA-LeahNeural / en-SG-WayneNeural 在免费端点上始终返回 NoAudioReceived（重试 3 次均失败，
# 同组 luke / luna 正常），已从 VOICES 中移除 —— 所以这里是 45 个而不是 47 个。
# 以后若微软修复，把这两条补回 VOICES 即可；补回前若要临时停用某个音色，加进这个集合。
UNAVAILABLE = set()
SPEED_MAP = {"slower": "-25%", "slow": "-15%", "normal": "0%", "fast": "+10%", "faster": "+20%"}
# edge-tts 7.3.0 起改用 v2 签名（CS64+SHA256）。7.2.x 及更早一律 403。
MIN_EDGE_TTS = (7, 3)
PY = sys.executable


def _find_ffmpeg():
    for cand in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "ffmpeg"),
                 os.path.expanduser("~/.workbuddy/skills/generatevoice/bin/ffmpeg"),
                 shutil.which("ffmpeg")):
        if cand and os.path.exists(cand):
            return cand
    return None


FFMPEG = _find_ffmpeg()


# ---------------------------------------------------------------- 音色解析
def resolve_voice(spec, accent=None, gender=None):
    """把别名 / 完整名 / 序号 解析成 edge-tts 的完整音色名。"""
    if spec:
        s = str(spec).strip()
        if re.fullmatch(r"\d+", s):                        # 序号：取 --list 里的第 N 个
            idx = int(s) - 1
            pool = _filter(accent, gender)
            if 0 <= idx < len(pool):
                return pool[idx][0]
            sys.exit(f"序号 {s} 超出范围（1-{len(pool)}）")
        low = s.lower()
        for full, alias, *_ in VOICES:                     # 别名
            if low == alias:
                return full
        for full, *_ in VOICES:                            # 短名：en-US-Aria / en-us-aria
            if low == full.lower().replace("neural", ""):
                return full
        for full, *_ in VOICES:                            # 只给名字：aria、sonia
            if low == full.split("-")[2].replace("neural", "").lower():
                return full
        if re.fullmatch(r"[a-zA-Z]{2}-[A-Za-z]{2}-\w+", s):  # 已是完整名
            return s if s.endswith("Neural") else s + "Neural"
        sys.exit(f"认不出音色「{s}」，用 --list 看看有哪些")
    pool = _filter(accent, gender)
    return pool[0][0] if pool else "en-US-AriaNeural"


def _filter(accent=None, gender=None):
    """按口音/性别筛音色，保持 VOICES 原序（序号靠这个顺序）。"""
    g = {"f": "f", "female": "f", "女": "f", "女声": "f",
         "m": "m", "male": "m", "男": "m", "男声": "m"}.get((gender or "").strip().lower(),
                                                          (gender or "").strip().lower() or None)
    a = (accent or "").strip().lower()
    a = {"uk": "gb", "british": "gb", "英音": "gb", "英式": "gb",
         "american": "us", "美音": "us", "美式": "us", "usa": "us",
         "australian": "au", "澳音": "au", "canadian": "ca", "加音": "ca"}.get(a, a)
    out = [v for v in VOICES if (not a or v[3] == a) and (not g or v[4] == g)]
    return out


def _meta(full):
    for v in VOICES:
        if v[0] == full:
            return v
    return (full, "", full.split("-")[2].replace("Neural", ""), full.split("-")[1].lower(), "?", "")


def _pad(s, width):
    """按显示宽度补空格（中文算 2 格），终端里对齐才好看。"""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def print_list(all_voices=False, accent=None, gender=None):
    if all_voices:                                        # 直接问 edge-tts 要全量
        r = subprocess.run([PY, "-m", "edge_tts", "--list-voices"],
                           capture_output=True, text=True)
        rows = [l.split("\t") for l in r.stdout.splitlines() if l.startswith("en-")]
        print(f"{'完整音色名':38} {'性别':6} 特点")
        for row in rows:
            print(f"{row[0]:38} {row[1]:6} {row[3].strip() if len(row) > 3 else ''}")
        return

    # 序号必须和 resolve_voice 的序号池严格一致：都走 _filter + VOICES 原序
    pool = _filter(accent, gender)
    if not pool:
        print("该条件下没有音色")
        return
    num = {v[0]: i + 1 for i, v in enumerate(pool)}
    cur = None
    for full, alias, cn, a, g, note in pool:
        if a != cur:                                      # 口音变化就插分组标题
            cur = a
            print(f"\n{ACCENT_CN.get(a, a)}")
            print("-" * 60)
        flag = "  ⚠ 当前发不出音" if full in UNAVAILABLE else ""
        print(f"{num[full]:>2}. {_pad(cn, 12)}{'女' if g == 'f' else '男'}  "
              f"{_pad(alias, 14)}{note}{flag}")
    ok = sum(1 for v in pool if v[0] not in UNAVAILABLE)
    cnt = f"共 {len(pool)} 个" if ok == len(pool) else f"共 {len(pool)} 个，实际可用 {ok} 个"
    print(f"\n{cnt}。用法：--voice aria / --voice 3 / --voice en-US-AriaNeural")
    print("按口音筛：--accent gb    按性别筛：--gender m")


# ---------------------------------------------------------------- 文本处理
def read_source(args):
    if args.text:
        return args.text.strip()
    if not args.file:
        sys.exit("需要文本：-t \"内容\" 或给一个文件")
    p = args.file
    if not os.path.exists(p):
        sys.exit(f"文件不存在: {p}")
    low = p.lower()
    if low.endswith(".docx"):
        import docx
        d = docx.Document(p)
        lines = [x.text.strip() for x in d.paragraphs]
        for t in d.tables:                                 # 课文常在表格里
            for row in t.rows:
                seen = set()
                for cell in row.cells:
                    if cell._tc in seen:
                        continue
                    seen.add(cell._tc)
                    lines.append(cell.text.strip())
        return "\n".join(x for x in lines if x)
    if low.endswith(".doc"):
        sys.exit("旧版 .doc 请先另存为 .docx")
    return open(p, encoding="utf-8", errors="ignore").read().strip()


def chunk_text(text, limit=1200):
    """按句切分再合并到 limit 字符以内；保证不切断句子。"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    sents = re.split(r"(?<=[.!?。！？])\s+", text)
    chunks, buf = [], ""
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if buf and len(buf) + len(s) + 1 > limit:
            chunks.append(buf)
            buf = s
        elif not buf and len(s) > limit:                   # 单句超长，硬切
            for i in range(0, len(s), limit):
                chunks.append(s[i:i + limit])
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        chunks.append(buf)
    return chunks or [text]


# ---------------------------------------------------------------- 合成
async def _synth(text, voice, out, rate, pitch, volume):
    import edge_tts
    kw = {}
    if rate:
        kw["rate"] = rate
    if pitch:
        kw["pitch"] = pitch
    if volume:
        kw["volume"] = volume
    await edge_tts.Communicate(text, voice, **kw).save(out)


def synth(text, voice, out, rate, pitch, volume, retries=2):
    """合成；对偶发网络错误重试，对「在册但不发声」的音色给出人话提示。"""
    last = None
    err403 = False
    for i in range(retries + 1):
        try:
            asyncio.run(_synth(text, voice, out, rate, pitch, volume))
            if os.path.exists(out) and os.path.getsize(out) > 500:
                return
            last = "空音频"
        except Exception as e:
            last = type(e).__name__
            msg = str(e)
            if "403" in msg or "WSServerHandshake" in last:
                err403 = True
                break                                     # 签名被拒，重试无用
            if "NoAudioReceived" in last:
                break                                     # 这个错重试也没用
            import time
            time.sleep(1.5 * (i + 1))
    print()                                               # 断掉 "合成 x/y ..." 那行
    if err403:
        sys.exit(
            "连接被拒（403）：微软的签名校验没过，通常是 edge-tts 版本太旧，\n"
            "不是网络问题、也不是音色问题。执行这条即可：\n"
            f"  {PY} -m pip install -U edge-tts\n"
            f"当前版本 {_ver()}，需要 ≥ {MIN_EDGE_TTS}。")
    alt = UNAVAILABLE.get(voice)
    if alt:
        sys.exit(f"音色 {voice} 在微软免费端点上发不出音（不是你的问题）。"
                 f"换同组另一个：--voice {_meta(alt)[1]}")
    if last == "NoAudioReceived":
        sys.exit(f"音色 {voice} 没有返回音频（该音色可能已下线）。"
                 f"跑 `{PY} scripts/check_voices.py` 看是它一个还是全都这样。")
    sys.exit(f"合成失败（{last}）。若反复出现，检查网络或稍后重试。")


def _ver():
    import importlib.metadata as m
    try:
        return m.version("edge-tts")
    except Exception:
        return "unknown"


def version_warning():
    """启动时轻提示：旧版 edge-tts 会遇到 403，提前告知省得排查半天。"""
    v = _ver()
    try:
        ok = tuple(int(x) for x in v.split(".")[:2]) >= MIN_EDGE_TTS
    except Exception:
        return
    if not ok:
        print(f"提示：edge-tts {v} 偏旧，微软签名已升到 v2，可能报 403。"
              f"升级：{PY} -m pip install -U edge-tts\n")


def concat(files, out, pad=0.15):
    """把分块音频首尾相接。每块尾部补一点静音，块与块之间不粘字。"""
    if not FFMPEG:
        sys.exit("需要 ffmpeg 拼接长文本，但没找到")
    if len(files) == 1:
        shutil.copy(files[0], out)
        return
    ins, graphs = [], []
    for i, f in enumerate(files):
        ins += ["-i", f]
        if pad:
            graphs.append(f"[{i}:a]apad=pad_dur={pad}[a{i}]")
    n = len(files)
    head = "".join(f"[a{i}]" for i in range(n)) if pad else "".join(f"[{i}:a]" for i in range(n))
    graphs.append(f"{head}concat=n={n}:v=0:a=1[out]")
    r = subprocess.run([FFMPEG, *ins, "-filter_complex", ";".join(graphs),
                        "-map", "[out]", "-y", out], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg 拼接失败: " + r.stderr[-400:])


def build_html(mp3, out_html, title):
    b64 = base64.b64encode(open(mp3, "rb").read()).decode()
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:32px 20px;background:#f5f6f8;color:#1c1e21;
font:16px/1.7 -apple-system,"PingFang SC","Helvetica Neue",sans-serif}}
.wrap{{max-width:720px;margin:0 auto;background:#fff;border:1px solid #e3e5e8;
border-radius:14px;padding:26px 28px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
h1{{font-size:17px;margin:0 0 18px;font-weight:600;color:#1c1e21}}
.bar{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
button{{border:none;border-radius:9px;padding:9px 18px;font-size:15px;cursor:pointer;
background:#2b6cb0;color:#fff;font-family:inherit}}
button:hover{{background:#245a94}}
.seg{{display:inline-flex;border:1px solid #d7dade;border-radius:9px;overflow:hidden}}
.seg button{{background:#fff;color:#4a4f55;border-radius:0;padding:8px 14px;font-size:14px}}
.seg button.on{{background:#2b6cb0;color:#fff}}
#bar{{flex:1;height:6px;background:#e6e8eb;border-radius:3px;min-width:120px;cursor:pointer}}
#fill{{height:100%;width:0;background:#2b6cb0;border-radius:3px}}
#t{{font-variant-numeric:tabular-nums;color:#7a8087;font-size:14px;min-width:88px}}
</style></head><body><div class="wrap">
<h1>{title}</h1>
<div class="bar">
  <button id="pp">播放</button>
  <div class="seg" id="spd">
    <button data-r="1" class="on">1.0×</button>
    <button data-r="0.85">0.85×</button>
    <button data-r="0.7">0.7×</button>
  </div>
  <div id="bar"><div id="fill"></div></div>
  <span id="t">0:00 / 0:00</span>
</div></div>
<script>
window.__AUDIO__="data:audio/mpeg;base64,{b64}";
const a=new Audio(window.__AUDIO__),pp=document.getElementById('pp'),
  fill=document.getElementById('fill'),bar=document.getElementById('bar'),
  tt=document.getElementById('t');
const fmt=s=>isFinite(s)?Math.floor(s/60)+':'+String(Math.floor(s%60)).padStart(2,'0'):'0:00';
pp.onclick=()=>a.paused?a.play():a.pause();
a.onplay=()=>pp.textContent='暂停';a.onpause=()=>pp.textContent='播放';
a.ontimeupdate=()=>{{fill.style.width=(a.currentTime/a.duration*100||0)+'%';
tt.textContent=fmt(a.currentTime)+' / '+fmt(a.duration);}};
bar.onclick=e=>{{const r=bar.getBoundingClientRect();
a.currentTime=(e.clientX-r.left)/r.width*a.duration;}};
document.querySelectorAll('#spd button').forEach(b=>b.onclick=()=>{{
a.playbackRate=+b.dataset.r;
document.querySelectorAll('#spd button').forEach(x=>x.classList.remove('on'));
b.classList.add('on');}});
</script></body></html>"""
    open(out_html, "w", encoding="utf-8").write(html)


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="英文文本转朗读 mp3（音色可选）")
    p.add_argument("file", nargs="?", help=".txt / .md / .docx")
    p.add_argument("-t", "--text")
    p.add_argument("-o", "--out")
    p.add_argument("--voice")
    p.add_argument("--accent")
    p.add_argument("--gender")
    p.add_argument("--speed", choices=list(SPEED_MAP))
    p.add_argument("--rate")
    p.add_argument("--pitch")
    p.add_argument("--volume")
    p.add_argument("--list", action="store_true", help="列出推荐音色")
    p.add_argument("--all", action="store_true", help="配合 --list：列出 edge-tts 全部音色")
    p.add_argument("--html", action="store_true", help="额外生成单文件 HTML 播放页")
    p.add_argument("--no-concat", action="store_true")
    p.add_argument("--check", action="store_true",
                   help="音色健康自检（= scripts/check_voices.py，可追加 --quick / --accent）")
    p.add_argument("--quick", action="store_true", help="配合 --check：每个口音只抽 1 个")
    args, unknown = p.parse_known_args()

    if args.check:
        import subprocess as sp
        cmd = [PY, os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_voices.py")]
        if args.quick:
            cmd.append("--quick")
        if args.accent:
            cmd += ["--accent", args.accent]
        cmd += unknown                                    # 其余透传
        sys.exit(sp.run(cmd).returncode)

    if args.list:
        print_list(args.all, args.accent, args.gender)
        return

    version_warning()

    text = read_source(args)
    if not text:
        sys.exit("文本是空的")

    voice = resolve_voice(args.voice, args.accent, args.gender)
    rate = args.rate or SPEED_MAP.get(args.speed or "", None)
    if rate in ("0%", "0"):
        rate = None

    out = args.out
    if not out:
        base = os.path.splitext(os.path.basename(args.file))[0] if args.file else "speech"
        out = os.path.join(os.getcwd(), base + ".mp3")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)

    full, alias, cn, acc, g, note = _meta(voice)
    print(f"音色: {cn}（{voice}｜{ACCENT_CN.get(acc, acc)}·{'女声' if g == 'f' else '男声'}）")
    print(f"文本: {len(text)} 字符")

    chunks = chunk_text(text)
    if args.no_concat and len(chunks) > 1:                 # 分块各存一份，不拼接
        d = os.path.splitext(out)[0] + "_分块"
        os.makedirs(d, exist_ok=True)
        for i, c in enumerate(chunks, 1):
            print(f"  合成 {i}/{len(chunks)} ...", end="", flush=True)
            synth(c, voice, os.path.join(d, f"{i:02d}.mp3"), rate, args.pitch, args.volume)
            print(" ok")
        print("DONE ->", d)
        return
    elif len(chunks) == 1:                                 # 常见情况：一次合成
        print("  合成 1/1 ...", end="", flush=True)
        synth(chunks[0], voice, out, rate, args.pitch, args.volume)
        print(" ok")
        print("DONE ->", out)
        final = out
    else:
        print(f"长文本分 {len(chunks)} 段合成后拼接")
        tmpdir = tempfile.mkdtemp(prefix="tts_")
        parts = []
        try:
            for i, c in enumerate(chunks, 1):
                f = os.path.join(tmpdir, f"{i:02d}.mp3")
                print(f"  合成 {i}/{len(chunks)} ...", end="", flush=True)
                synth(c, voice, f, rate, args.pitch, args.volume)
                parts.append(f)
                print(" ok")
            concat(parts, out)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        print("DONE ->", out)
        final = out

    if args.html and final:
        hp = os.path.splitext(final)[0] + ".html"
        build_html(final, hp, os.path.splitext(os.path.basename(final))[0])
        print("HTML ->", hp)


if __name__ == "__main__":
    main()
