#!/usr/bin/env python3
"""音色健康自检：确认 VOICES 表里的每个音色此刻真的能发声。

为什么需要这个：edge-tts 的 --list-voices 只是服务端的一份目录，音色可能在
没有任何通知的情况下失效（2026-10-28 实测 en-ZA-LeahNeural / en-SG-WayneNeural
就是"在册但发不出声"，同组其他音色正常）。所以"列得出来"≠"能用"。

用法:
  python check_voices.py                 # 全量自检（45 条，约 2-4 分钟）
  python check_voices.py --accent gb     # 只查某口音
  python check_voices.py --quick         # 每个口音只抽 1 个，几十秒
  python check_voices.py --json          # 机器可读输出
  python check_voices.py --update-stamp  # 自检通过后更新 SKILL.md 里的检测时间

退出码：0 = 全部可用；1 = 有音色不可用（可用于定时任务告警）
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tts import VOICES, ACCENT_CN, _filter  # noqa: E402

# 极短文本：够触发合成即可，省时间
PROBE = "Hello."
STAMP_FILE = os.path.join(os.path.dirname(HERE), "assets", "last_check.json")


async def probe(full, retries=2, timeout=25.0):
    """测一个音色。返回 (ok: bool, reason: str, secs: float)。

    用 Communicate.stream() 读第一块音频就停，比 save() 整个文件快。
    """
    import edge_tts
    for attempt in range(retries + 1):
        try:
            got = 0
            async def run():
                nonlocal got
                async for chunk in edge_tts.Communicate(PROBE, full).stream():
                    if chunk["type"] == "audio":
                        got += len(chunk["data"])
                        if got > 0:
                            return
            await asyncio.wait_for(run(), timeout=timeout)
            if got > 0:
                return True, "ok", 0.0
            return False, "无音频数据", 0.0
        except asyncio.TimeoutError:
            if attempt == retries:
                return False, "超时", 0.0
        except Exception as e:
            name = type(e).__name__
            msg = str(e)[:80]
            if "NoAudioReceived" in name or "NoAudio" in msg:
                if attempt == retries:
                    return False, "NoAudioReceived", 0.0
            elif "403" in msg or "WSServerHandshake" in name:
                # 403 是签名/版本问题，不是这个音色的问题，立刻上抛
                return None, "403 签名被拒", 0.0
            elif attempt == retries:
                return False, f"{name}: {msg}", 0.0
            await asyncio.sleep(1.2 * (attempt + 1))
    return False, "未知", 0.0


def verdict(results):
    """把逐条结果归纳成一句人话诊断。这是脚本最有价值的部分。"""
    total = len(results)
    bad = [r for r in results if not r["ok"]]
    if not bad:
        return "healthy", "全部音色可发声"

    # 全挂 + 都是 403 → 不是音色问题
    if all(r["reason"] == "403 签名被拒" for r in bad):
        return "auth", ("全部被 403 拒绝：这是 edge-tts 版本太旧、签名算法对不上，"
                        "不是音色坏了。执行 pip install -U edge-tts 再试。")

    # 全挂但不是 403 → 网络/服务故障
    if len(bad) == total:
        return "network", "全部失败：先确认网络能连通 speech.platform.bing.com，不像音色问题"

    # 少数挂 → 真的是这些音色不行
    names = "、".join(r["alias"] for r in bad)
    if len(bad) <= 3:
        return "voices", f"{len(bad)} 个音色无响应：{names}（其余 {total - len(bad)} 个正常，是该音色本身不可用）"
    return "voices", f"{len(bad)}/{total} 个音色无响应：{names}"


async def main_async(args):
    pool = _filter(args.accent)
    if not pool:
        sys.exit(f"没有匹配 --accent {args.accent} 的音色")

    # 全量检测 = 不限口音且不抽样；只有这种才写全局记录
    full_run = not args.accent and not args.quick

    if args.quick:                                        # 每个口音抽一个
        seen, picked = set(), []
        for v in pool:
            if v[3] not in seen:
                seen.add(v[3])
                picked.append(v)
        pool = picked

    print(f"检测 {len(pool)} 个音色"
          + (f"（口音 {ACCENT_CN.get(args.accent, args.accent)}）" if args.accent else "")
          + " ...\n")

    results = []
    for i, (full, alias, cn, acc, g, note) in enumerate(pool, 1):
        ok, reason, _ = await probe(full)
        results.append({"alias": alias, "full": full, "cn": cn, "accent": acc,
                        "ok": bool(ok), "reason": reason})
        mark = "ok" if ok else ("AUTH" if ok is None else "FAIL")
        print(f"  [{i:>2}/{len(pool)}] {alias:<12} {mark:<5} {reason if not ok else ''}")
        if ok is None:                                    # 403 就没必要继续问了
            print("\n遇到 403，提前中止。")
            break
        await asyncio.sleep(args.delay)                   # 温和一点，别被限流

    code, summary = verdict(results)
    print(f"\n结论：{summary}")

    stamp = {"checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
             "edge_tts": _ver(), "total": len(results),
             "failed": [r["alias"] for r in results if not r["ok"]],
             "verdict": code, "summary": summary}

    if args.json:
        print(json.dumps({"verdict": code, "summary": summary, "results": results},
                         ensure_ascii=False, indent=2))
    elif full_run:
        # 只有全量检测才写记录：抽样/单口音的结果代表不了全局，写进去会误导
        os.makedirs(os.path.dirname(STAMP_FILE), exist_ok=True)
        with open(STAMP_FILE, "w", encoding="utf-8") as f:
            json.dump(stamp, f, ensure_ascii=False, indent=2)
        print("（已记录到 assets/last_check.json）")
    else:
        print("（本次为抽样/单口音检测，不覆盖全量记录）")

    if args.update_stamp and code == "healthy" and full_run:
        _write_skill_stamp(stamp["checked_at"])

    return 0 if code == "healthy" else 1


def _ver():
    import importlib.metadata as m
    try:
        return m.version("edge-tts")
    except Exception:
        return "unknown"


def _write_skill_stamp(when):
    """把最近一次全量自检时间写进 SKILL.md，让人一眼看出数据是否新鲜。"""
    p = os.path.join(os.path.dirname(HERE), "SKILL.md")
    s = open(p, encoding="utf-8").read()
    line = f"> 最近一次全量音色自检：**{when}**（`python scripts/check_voices.py`）"
    if "最近一次全量音色自检" in s:
        import re
        s = re.sub(r"> 最近一次全量音色自检：.*", line, s, count=1)
    else:
        i = s.index("## 音色一览")
        s = s[:i] + line + "\n\n" + s[i:]
    open(p, "w", encoding="utf-8").write(s)
    print("已更新 SKILL.md 的检测时间")


def main():
    ap = argparse.ArgumentParser(description="音色健康自检")
    ap.add_argument("--accent", help="只查某个口音，如 gb / hk")
    ap.add_argument("--quick", action="store_true", help="每个口音只抽查 1 个")
    ap.add_argument("--json", action="store_true", help="只输出 JSON，不写记录")
    ap.add_argument("--delay", type=float, default=0.4, help="每个之间间隔秒数")
    ap.add_argument("--update-stamp", action="store_true", help="全通过时更新 SKILL.md 时间")
    a = ap.parse_args()
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
