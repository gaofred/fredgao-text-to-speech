#!/usr/bin/env python3
"""生成音色试听页：把全部音色（含中文）的同一句样音嵌进单文件 HTML。

用法:
  python make_audition.py            # 生成 assets/voices.html（已有样音直接复用）
  python make_audition.py --refresh  # 强制重新合成全部样音
  python make_audition.py --refresh aria sonia xiaoxiao   # 只重合指定的

样音缓存在 assets/samples/<别名>.mp3，删掉某个文件即可单独重生成。
英文音色用英文样句；中文/粤语/台湾音色用中文样句（口音差异由音色本身体现）。
"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tts import VOICES, ACCENT_CN, MAIN_ACCENTS, FFMPEG, UNAVAILABLE  # noqa: E402

# 只给实际发声的音色做样音；不可用的不进试听页（避免用户点了没声音以为坏了）
VOICES = [v for v in VOICES if v[0] not in UNAVAILABLE]

ASSETS = os.path.join(os.path.dirname(HERE), "assets")
SAMPLES = os.path.join(ASSETS, "samples")

# 这句同时含 /ɑː/ vs /æ/、词尾 -er、t 的闪音，口音差别听得出来
SAMPLE = ("Could you pass me the glass of water? "
          "I'd rather sit here and read a little longer.")

# 中文音色（普通话/粤语/台湾/方言）用的样句，含声调与停顿变化，听感差异明显
SAMPLE_ZH = "今天天气真好，我们一起朗读这篇课文，注意声调和停顿。"

# 哪些口音用中文样句（其余用英文样句）
ZH_ACCENTS = ("zh", "yue", "tw", "dialect")

CARD = """
<article class="card" data-accent="{acc}" data-alias="{alias}" data-sex="{sex}">
  <button class="play" aria-label="播放 {cn}">
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
  </button>
  <div class="meta">
    <div class="title"><b>{cn}</b><span class="tag {sex}">{sextxt}</span></div>
    <div class="id">{alias}</div>
    <div class="note">{note}</div>
  </div>
  <audio preload="none"></audio>
</article>"""


async def synth_all(force=False, only=None):
    import edge_tts
    os.makedirs(SAMPLES, exist_ok=True)
    todo = []
    for full, alias, cn, acc, g, note in VOICES:
        if only and alias not in only:
            continue
        out = os.path.join(SAMPLES, alias + ".mp3")
        if force or not os.path.exists(out) or os.path.getsize(out) < 2000:
            todo.append((full, alias, out, acc))

    if todo:
        print(f"合成样音 {len(todo)} 条 ...")
        for i, (full, alias, out, acc) in enumerate(todo, 1):
            text = SAMPLE_ZH if acc in ZH_ACCENTS else SAMPLE
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(text, full).save(out)
                    if os.path.getsize(out) > 2000:
                        print(f"  [{i}/{len(todo)}] {alias}")
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  [{i}/{len(todo)}] {alias} 失败: {type(e).__name__}")
                    else:
                        await asyncio.sleep(1.5)
    else:
        print("样音全部命中缓存")
    compress_all()
    return {alias: os.path.join(SAMPLES, alias + ".mp3") for _, alias, *_ in VOICES}


def compress_all():
    """样音压到 32kbps 单声道。几十条塞进单文件 HTML，不压会到 2MB+。"""
    if not FFMPEG:
        return
    for _, alias, *_ in VOICES:
        p = os.path.join(SAMPLES, alias + ".mp3")
        if not os.path.exists(p) or os.path.getsize(p) < 24000:
            continue
        tmp = p + ".tmp.mp3"
        r = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", p,
                            "-ac", "1", "-ar", "24000", "-b:a", "32k", tmp],
                           capture_output=True)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 1000:
            os.replace(tmp, p)
        elif os.path.exists(tmp):
            os.remove(tmp)


def _stamp_line():
    """读上次自检记录，给试听页一个数据新鲜度提示（音色会无声失效，别让人以为样音是刚测的）。"""
    p = os.path.join(ASSETS, "last_check.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        when = d.get("checked_at", "")[:16].replace("T", " ")
        bad = d.get("failed") or []
        extra = f"，其中 {len(bad)} 个音色当时无响应已剔除" if bad else ""
        return f"音色可用性检测：{when} · edge-tts {d.get('edge_tts','?')}{extra}"
    except Exception:
        return "音色可用性未检测 · 建议先跑 scripts/check_voices.py"


def build_html(samples):
    cards_meta = [v for v in VOICES if os.path.exists(samples.get(v[1], ""))]
    audio_js = ",\n".join(
        f'"{alias}":"data:audio/mpeg;base64,'
        f'{base64.b64encode(open(p, "rb").read()).decode()}"'
        for alias, p in samples.items() if os.path.exists(p))

    # 筛选条：常用口音排前面，其余口音归到「其他」下拉里
    present = []
    for v in VOICES:
        if v[3] not in present:
            present.append(v[3])
    main = [a for a in MAIN_ACCENTS if a in present]
    other = [a for a in present if a not in main]

    NV = len(cards_meta)
    STAMP = _stamp_line()
    accent_btns = "".join(f'<button data-f="{a}">{ACCENT_CN.get(a, a)}</button>' for a in main)
    other_opts = "".join(f'<option value="{a}">{ACCENT_CN.get(a, a)}</option>' for a in other)

    # 按口音分组打印，横向对比时同组挨着看
    groups = ""
    for a in present:
        gv = [v for v in VOICES if v[3] == a]
        groups += (f'\n<div class="group" data-g="{a}">'
                   f'<h2>{ACCENT_CN.get(a, a)}<span>{len(gv)}</span></h2>'
                   f'<div class="grid">'
                   + "".join(CARD.format(acc=v[3], alias=v[1], cn=v[2], note=v[5],
                                         sex="f" if v[4] == "f" else "m",
                                         sextxt="女" if v[4] == "f" else "男")
                             for v in gv)
                   + "</div></div>")

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>音色试听 · {NV} 个（含中文）</title>
<style>
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
body{{margin:0;padding:32px 20px 70px;background:#f4f5f7;color:#1b1d1f;
font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif}}
.head,.sample,.filters,.wrap{{max-width:960px;margin-left:auto;margin-right:auto}}
h1{{font-size:20px;margin:0 0 6px;font-weight:600;letter-spacing:.2px}}
.sub{{color:#767b82;font-size:13px;margin-bottom:16px}}
.stamp{{color:#a0a6ad;font-size:12px;margin:-10px 0 16px}}
.sample{{background:#fff;border:1px solid #e4e6e9;border-radius:11px;padding:14px 18px;
font-size:13.5px;color:#4a4f55;margin-bottom:18px}}
.sample b{{color:#1b1d1f;font-weight:600;display:block;margin-bottom:3px;font-size:11px;
text-transform:uppercase;letter-spacing:.7px}}
.filters{{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin-bottom:26px;
position:sticky;top:0;background:#f4f5f7;padding:10px 0;z-index:9}}
.filters button{{border:1px solid #d9dbdf;background:#fff;color:#4a4f55;border-radius:8px;
padding:6px 13px;font-size:13px;cursor:pointer;font-family:inherit;transition:.15s}}
.filters button:hover{{border-color:#aab0b7}}
.filters button.on{{background:#1b1d1f;border-color:#1b1d1f;color:#fff}}
.filters select{{border:1px solid #d9dbdf;background:#fff;color:#4a4f55;border-radius:8px;
padding:6px 9px;font-size:13px;font-family:inherit;cursor:pointer}}
.filters .seq{{margin-left:auto;background:#2b6cb0;border-color:#2b6cb0;color:#fff}}
.filters .seq:hover{{background:#245a94}}
.wrap{{max-width:960px;margin:0 auto}}
.group{{margin-bottom:26px}}
.group h2{{font-size:13px;font-weight:600;color:#5b6167;margin:0 0 9px;
letter-spacing:.3px;display:flex;align-items:center;gap:7px}}
.group h2 span{{font-weight:400;color:#a0a6ad;font-size:12px}}
.grid{{display:grid;gap:9px;grid-template-columns:repeat(auto-fill,minmax(272px,1fr))}}
.card{{display:flex;gap:11px;align-items:flex-start;background:#fff;border:1px solid #e4e6e9;
border-radius:10px;padding:11px 12px;transition:.15s;cursor:pointer}}
.card:hover{{border-color:#c5cad0}}
.card.on{{border-color:#2b6cb0;box-shadow:inset 0 0 0 1px #2b6cb0}}
.play{{flex:0 0 30px;height:30px;border-radius:50%;border:none;background:#eef1f5;color:#2b6cb0;
display:grid;place-items:center;cursor:pointer;transition:.15s;padding:0}}
.card:hover .play,.card.on .play{{background:#2b6cb0;color:#fff}}
.meta{{min-width:0;flex:1}}
.title{{display:flex;align-items:center;gap:6px;font-size:14.5px}}
.title b{{font-weight:600}}
.tag{{font-size:10.5px;line-height:1;padding:2.5px 4.5px;border-radius:4px;font-weight:500}}
.tag.f{{background:#fdeef2;color:#b8325a}}
.tag.m{{background:#eaf1fb;color:#2b5f9e}}
.id{{font-size:11px;color:#9aa0a7;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
margin:1px 0 2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.note{{font-size:12px;color:#6b7178;line-height:1.4}}
</style></head><body>

<div class="head">
  <h1>音色试听 · {NV} 个（含中文普通话/粤语/台湾）</h1>
  <div class="sub">英文音色读英文句，中文/粤语/台湾音色读中文句，同一音色横向对比。点卡片任意位置播放；按口音筛选；可全部连播。</div>
  <div class="stamp">{STAMP}</div>
</div>

<div class="sample"><b>英文试听文本</b>{SAMPLE}</div>
<div class="sample"><b>中文试听文本</b>{SAMPLE_ZH}</div>

<div class="filters">
  <button data-f="all" class="on">全部 {NV}</button>
  {accent_btns}
  <select id="other"><option value="">其他口音…</option>{other_opts}</select>
  <button class="seq" id="seq">▶ 连播</button>
</div>

<div class="wrap" id="wrap">{groups}
</div>

<script>
const A = {{
{audio_js}
}};
const cards = [...document.querySelectorAll('.card')];
const groups = [...document.querySelectorAll('.group')];
let cur = null, seq = false;

function stop() {{
  if (cur) {{ cur.querySelector('audio').pause(); cur.classList.remove('on'); }}
  cur = null;
}}

function play(card) {{
  if (cur === card) {{
    const a = card.querySelector('audio');
    if (a.paused) a.play(); else {{ a.pause(); card.classList.remove('on'); }}
    return;
  }}
  stop();
  cur = card;
  card.classList.add('on');
  const a = card.querySelector('audio');
  if (!a.src) a.src = A[card.dataset.alias];
  a.currentTime = 0;
  a.play();
  a.onended = () => {{
    card.classList.remove('on');
    if (cur === card) cur = null;
    if (seq) {{
      const list = visible();
      const i = list.indexOf(card);
      if (list.length > 1) play(list[(i + 1) % list.length]); else stopSeq();
    }}
  }};
}}

const visible = () => cards.filter(c => c.closest('.group').style.display !== 'none');
function stopSeq() {{
  seq = false;
  document.getElementById('seq').textContent = '▶ 连播';
}}

cards.forEach(c => c.addEventListener('click', e => {{
  if (e.target.closest('button')) return;
  play(c);
}}));
cards.forEach(c => c.querySelector('.play').onclick = () => play(c));

function filter(acc) {{
  groups.forEach(g => g.style.display = (acc === 'all' || g.dataset.g === acc) ? '' : 'none');
  stop(); stopSeq();
}}

document.querySelectorAll('.filters [data-f]').forEach(b => b.onclick = () => {{
  document.querySelectorAll('.filters [data-f]').forEach(x => x.classList.remove('on'));
  b.classList.add('on');
  document.getElementById('other').value = '';
  filter(b.dataset.f);
}});

document.getElementById('other').onchange = e => {{
  if (!e.target.value) return;
  document.querySelectorAll('.filters [data-f]').forEach(x => x.classList.remove('on'));
  filter(e.target.value);
}};

document.getElementById('seq').onclick = e => {{
  if (seq) {{ stopSeq(); stop(); return; }}
  seq = true;
  e.target.textContent = '⏸ 停止';
  stop();
  const l = visible();
  if (l.length) play(l[0]); else stopSeq();
}};
</script>
</body></html>"""
    out = os.path.join(ASSETS, "voices.html")
    open(out, "w", encoding="utf-8").write(html)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="强制重合成样音")
    ap.add_argument("only", nargs="*", help="只处理指定别名")
    a = ap.parse_args()
    samples = asyncio.run(synth_all(a.refresh, set(a.only) or None))
    p = build_html(samples)
    print("HTML ->", p, f"({os.path.getsize(p)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
