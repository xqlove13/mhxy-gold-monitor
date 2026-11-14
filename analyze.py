# -*- coding: utf-8 -*-
"""
波动分析（两层维度）
  市场总计：老区/新区均价曲线、涨跌分布、整体时段模式（按各服务器偏离自身均值聚合）
  各区独立：每个服务器自己的小时/星期分布、波动率、历史曲线

产出 data/dashboard_data.json
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import WATCH_LIST

BASE = Path(__file__).parent
SNAP_PATH = BASE / "data" / "snapshots.jsonl"
OUT_PATH = BASE / "data" / "dashboard_data.json"

DOW_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def cst_now():
    return datetime.now(timezone(timedelta(hours=8)))


def agg_bucket(bucket):
    out = {}
    for k, v in sorted(bucket.items(), key=lambda kv: int(kv[0])):
        out[str(k)] = {
            "avg": round(sum(v) / len(v), 2),
            "min": round(min(v), 2),
            "max": round(max(v), 2),
            "count": len(v),
        }
    return out


def calc_extremes(points, keep_days=30):
    """points: [(datetime, price)]
    返回每日/每周金价最高最低出现的时刻，以及高/低点的时刻分布。
    """
    from collections import Counter

    by_date, by_week = defaultdict(list), defaultdict(list)
    for dt, p in points:
        by_date[dt.strftime("%Y-%m-%d")].append((dt, p))
        iso = dt.isocalendar()
        by_week[(iso[0], iso[1])].append((dt, p))

    daily, high_h, low_h = [], Counter(), Counter()
    for date, pts in sorted(by_date.items()):
        if len(pts) < 2:
            continue
        hi, lo = max(pts, key=lambda x: x[1]), min(pts, key=lambda x: x[1])
        daily.append(
            {
                "date": date,
                "high": hi[1],
                "high_time": hi[0].strftime("%H:%M"),
                "high_hour": hi[0].hour,
                "low": lo[1],
                "low_time": lo[0].strftime("%H:%M"),
                "low_hour": lo[0].hour,
                "range": round(hi[1] - lo[1], 2),
            }
        )
        high_h[hi[0].hour] += 1
        low_h[lo[0].hour] += 1

    weekly, wk_hi_d, wk_lo_d = [], Counter(), Counter()
    for (y, w), pts in sorted(by_week.items()):
        if len(pts) < 2:
            continue
        hi, lo = max(pts, key=lambda x: x[1]), min(pts, key=lambda x: x[1])
        weekly.append(
            {
                "week": f"{y}-W{w:02d}",
                "high": hi[1],
                "high_time": f"{DOW_NAMES[hi[0].isoweekday() - 1]} {hi[0].strftime('%H:%M')}",
                "low": lo[1],
                "low_time": f"{DOW_NAMES[lo[0].isoweekday() - 1]} {lo[0].strftime('%H:%M')}",
                "range": round(hi[1] - lo[1], 2),
            }
        )
        wk_hi_d[hi[0].isoweekday()] += 1
        wk_lo_d[lo[0].isoweekday()] += 1

    def top(counter, fmt_hour=True):
        if not counter:
            return None
        k, n = counter.most_common(1)[0]
        label = f"{int(k):02d}:00" if fmt_hour else DOW_NAMES[int(k) - 1]
        return {"label": label, "count": n}

    return {
        "daily": daily[-keep_days:],
        "weekly": weekly[-keep_days:],
        "high_hour_dist": {str(k): v for k, v in sorted(high_h.items())},
        "low_hour_dist": {str(k): v for k, v in sorted(low_h.items())},
        "high_dow_dist": {str(k): v for k, v in sorted(wk_hi_d.items())},
        "low_dow_dist": {str(k): v for k, v in sorted(wk_lo_d.items())},
        "top_high_time": top(high_h),
        "top_low_time": top(low_h),
        "top_high_week": top(wk_hi_d, fmt_hour=False),
        "top_low_week": top(wk_lo_d, fmt_hour=False),
    }


def main():
    rows = []
    if SNAP_PATH.exists():
        with SNAP_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    rows.sort(key=lambda r: (r["server"], r["ts"]))
    if not rows:
        print("库内暂无数据，请先运行 collector.py")
        return

    group_of = dict(WATCH_LIST)
    by_server = defaultdict(list)
    for r in rows:
        by_server[r["server"]].append(r)

    # 仅真实采集点参与统计（backfill 只用于补历史曲线）
    real_rows = [r for r in rows if r["source"] != "backfill"]
    stat_rows = real_rows if len(real_rows) >= 40 else rows

    def parse_ts(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    # ───────────── 各区独立 ─────────────
    servers = []
    for name, group in WATCH_LIST:
        hist = by_server.get(name, [])
        if not hist:
            continue
        cur = hist[-1]
        mine = [r for r in stat_rows if r["server"] == name]
        hour_b, dow_b = defaultdict(list), defaultdict(list)
        daily = defaultdict(list)
        for r in mine:
            dt = parse_ts(r["ts"])
            if not dt:
                continue
            hour_b[dt.hour].append(r["price"])
            dow_b[dt.isoweekday()].append(r["price"])
            daily[dt.strftime("%Y-%m-%d")].append(r["price"])

        prices = [r["price"] for r in mine] or [cur["price"]]
        mean_p = sum(prices) / len(prices)
        std_p = math.sqrt(sum((p - mean_p) ** 2 for p in prices) / len(prices))
        daily_ranges = [max(v) - min(v) for v in daily.values() if len(v) >= 2]
        pts = [(parse_ts(r["ts"]), r["price"]) for r in mine if parse_ts(r["ts"])]

        servers.append(
            {
                "name": name,
                "group": group,
                "price": cur["price"],
                "change_1d": cur["change_1d"],
                "change_7d": cur["change_7d"],
                "sample_count": len(mine) or len(hist),
                "volatility": {
                    "std": round(std_p, 2),
                    "daily_range_avg": round(sum(daily_ranges) / len(daily_ranges), 2)
                    if daily_ranges
                    else None,
                    "high": round(max(prices), 2),
                    "low": round(min(prices), 2),
                },
                "extremes": calc_extremes(pts, keep_days=14),
                "hour_stats": agg_bucket(hour_b),
                "dow_stats": agg_bucket(dow_b),
                "history": [
                    {"ts": h["ts"], "price": h["price"], "source": h["source"]} for h in hist
                ],
            }
        )

    # ───────────── 市场总计 ─────────────
    # 1) 每个时间点的老区均价（新区金价跳水剧烈，不做均价统计）
    ts_groups = defaultdict(list)
    for r in stat_rows:
        dt = parse_ts(r["ts"])
        if not dt:
            continue
        if group_of.get(r["server"]) != "人气新区":
            ts_groups[r["ts"]].append(r["price"])

    market_hist = [
        {"ts": ts, "old_avg": round(sum(v) / len(v), 2)}
        for ts, v in sorted(ts_groups.items())
    ]
    market_pts = [
        (parse_ts(ts), sum(v) / len(v))
        for ts, v in sorted(ts_groups.items())
        if parse_ts(ts)
    ]

    # 2) 时段模式：价格偏离该服务器自身均值的百分比，跨服聚合
    dev_hour, dev_dow = defaultdict(list), defaultdict(list)
    for name, group in WATCH_LIST:
        mine = [r for r in stat_rows if r["server"] == name]
        if len(mine) < 1:
            continue
        mean_p = sum(r["price"] for r in mine) / len(mine)
        if mean_p <= 0:
            continue
        for r in mine:
            dt = parse_ts(r["ts"])
            if not dt:
                continue
            dev = (r["price"] / mean_p - 1) * 100
            dev_hour[dt.hour].append(dev)
            dev_dow[dt.isoweekday()].append(dev)

    # 3) 涨跌家数与涨跌榜（老区）
    old_srvs = [s for s in servers if s["group"] != "人气新区"]
    up_1d = sum(1 for s in old_srvs if (s["change_1d"] or 0) > 0)
    down_1d = sum(1 for s in old_srvs if (s["change_1d"] or 0) < 0)
    movers = sorted(old_srvs, key=lambda s: abs(s["change_7d"] or 0), reverse=True)[:5]

    def avg(key, seq):
        vals = [s[key] for s in seq if s[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    market = {
        "old_avg_price": round(sum(s["price"] for s in old_srvs) / len(old_srvs), 2)
        if old_srvs
        else None,
        "avg_change_1d": avg("change_1d", old_srvs),
        "avg_change_7d": avg("change_7d", old_srvs),
        "up_1d": up_1d,
        "down_1d": down_1d,
        "flat_1d": len(old_srvs) - up_1d - down_1d,
        "history": market_hist,
        "extremes": calc_extremes(market_pts),
        "hour_dev": agg_bucket(dev_hour),
        "dow_dev": agg_bucket(dev_dow),
        "top_movers": [
            {"name": s["name"], "group": s["group"], "change_7d": s["change_7d"]}
            for s in movers
        ],
    }

    # ───────────── 洞察 ─────────────
    insights = {"note": "时段结论至少需要 3~7 天持续采集才稳定"}
    if market["hour_dev"]:
        pk = max(market["hour_dev"].items(), key=lambda kv: kv[1]["avg"])
        tr = min(market["hour_dev"].items(), key=lambda kv: kv[1]["avg"])
        insights["price_peak_hour"] = f"全市场 {int(pk[0]):02d}:00 前后相对最高（+{pk[1]['avg']}%）"
        insights["price_trough_hour"] = f"全市场 {int(tr[0]):02d}:00 前后相对最低（{tr[1]['avg']}%）"
    if market["dow_dev"]:
        pk = max(market["dow_dev"].items(), key=lambda kv: kv[1]["avg"])
        tr = min(market["dow_dev"].items(), key=lambda kv: kv[1]["avg"])
        insights["price_peak_dow"] = (
            f"{DOW_NAMES[int(pk[0]) - 1]} 相对最高（+{pk[1]['avg']}%）"
        )
        insights["price_trough_dow"] = f"{DOW_NAMES[int(tr[0]) - 1]} 相对最低（{tr[1]['avg']}%）"

    ex = market.get("extremes") or {}
    if ex.get("top_high_time"):
        t = ex["top_high_time"]
        insights["daily_high_time"] = f"日高点最常出现在 {t['label']}（{t['count']} 天）"
    if ex.get("top_low_time"):
        t = ex["top_low_time"]
        insights["daily_low_time"] = f"日低点最常出现在 {t['label']}（{t['count']} 天）"
    if ex.get("top_high_week"):
        t = ex["top_high_week"]
        insights["weekly_high_time"] = f"周高点最常出现在{t['label']}（{t['count']} 周）"
    if ex.get("top_low_week"):
        t = ex["top_low_week"]
        insights["weekly_low_time"] = f"周低点最常出现在{t['label']}（{t['count']} 周）"

    group_order = {"老牌火区": 0, "活跃老区": 1, "人气新区": 2}
    payload = {
        "updated_at": cst_now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_snapshots": len(rows),
        "real_snapshots": len(real_rows),
        "market": market,
        "servers": sorted(servers, key=lambda s: (group_order.get(s["group"], 9), -s["price"])),
        "insights": insights,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"已写出 {OUT_PATH}")
    print(
        f"服务器 {len(servers)} 个，快照 {len(rows)} 条（真实 {len(real_rows)}）；"
        f"老区均价 {market['old_avg_price']}"
    )
    for k, v in insights.items():
        if k != "note":
            print(" •", v)


if __name__ == "__main__":
    main()
