# -*- coding: utf-8 -*-
"""
金价采集器 —— 从梦幻数据站抓取全服金价快照，存入 data/snapshots.jsonl
（JSONL 行式存储，方便进 git / GitHub Actions 持久化）

用法:
  python collector.py                # 采集一次
  python collector.py --loop         # 每 30 分钟循环
  python collector.py --backfill     # 用涨跌幅反推补种历史点
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import SOURCE_URLS, UA, WATCH_LIST

DATA_DIR = Path(__file__).parent / "data"
SNAP_PATH = DATA_DIR / "snapshots.jsonl"
ROW_RE = re.compile(
    r'<div class="price-rank">.*?</div>\s*'
    r'<div class="price-server">\s*'
    r'<div class="server-name">(.*?)</div>.*?'
    r'<div class="price-today">(.*?)</div>\s*'
    r'<div class="price-change[^"]*">\s*(.*?)\s*</div>\s*'
    r'<div class="price-change[^"]*">\s*(.*?)\s*</div>',
    re.S,
)


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def load_keys() -> set:
    """已有 (server, ts) 去重键"""
    keys = set()
    if SNAP_PATH.exists():
        with SNAP_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    keys.add((d["server"], d["ts"]))
                except Exception:
                    continue
    return keys


def append_rows(rows):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SNAP_PATH.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def fetch_prices() -> dict:
    """返回 {服务器名: (price, change_1d, change_7d)}，合并多个榜单页"""

    def num(s):
        s = s.strip().replace("+", "")
        try:
            return float(s)
        except ValueError:
            return None

    out = {}
    for url in SOURCE_URLS:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        for m in ROW_RE.finditer(html):
            name = m.group(1).strip()
            price = num(m.group(2))
            if name and price:
                out[name] = (price, num(m.group(3)), num(m.group(4)))
    return out


def collect_once(backfill: bool = False) -> int:
    prices = fetch_prices()
    ts = now_iso()
    seen = load_keys()
    rows, missing = [], []
    for name, group in WATCH_LIST:
        if name not in prices:
            missing.append(f"{name}({group})")
            continue
        price, c1, c7 = prices[name]
        if (name, ts) not in seen:
            rows.append(
                {
                    "server": name,
                    "price": price,
                    "change_1d": c1,
                    "change_7d": c7,
                    "ts": ts,
                    "source": "3jiebanzhuan",
                }
            )
        if backfill:
            for days, chg in ((1, c1), (7, c7)):
                if chg is None:
                    continue
                hist_ts = (
                    datetime.now(timezone(timedelta(hours=8))) - timedelta(days=days)
                ).strftime("%Y-%m-%d %H:%M:%S")
                if (name, hist_ts) not in seen:
                    rows.append(
                        {
                            "server": name,
                            "price": round(price - chg, 2),
                            "change_1d": None,
                            "change_7d": None,
                            "ts": hist_ts,
                            "source": "backfill",
                        }
                    )
    append_rows(rows)
    print(f"[{ts}] 采集完成：写入 {len(rows)} 条，命中 {len(WATCH_LIST) - len(missing)}/{len(WATCH_LIST)}")
    if missing:
        print("  未在榜单中找到：", ", ".join(missing))
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", nargs="?", const=1800, type=int, metavar="秒", help="循环采集，默认 1800 秒")
    ap.add_argument("--backfill", action="store_true", help="用涨跌幅反推补种历史点")
    args = ap.parse_args()

    if args.loop:
        print(f"开始循环采集，每 {args.loop} 秒一次（Ctrl+C 停止）")
        try:
            while True:
                try:
                    collect_once()
                except Exception as e:
                    print(f"[{now_iso()}] 采集失败：{e}", file=sys.stderr)
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n已停止")
    else:
        collect_once(backfill=args.backfill)
        n = sum(1 for _ in SNAP_PATH.open(encoding="utf-8")) if SNAP_PATH.exists() else 0
        print(f"库内累计快照：{n} 条")


if __name__ == "__main__":
    main()
