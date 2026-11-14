# -*- coding: utf-8 -*-
"""一次完整周期：采集 -> 分析 -> 刷新看板数据。

  python run_cycle.py          # 跑一次
  python run_cycle.py --loop   # 每 30 分钟循环（持续监测模式）
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
PY = sys.executable
INTERVAL = 1800  # 秒


def run(script):
    r = subprocess.run([PY, str(BASE / script)], capture_output=True, text=True, encoding="utf-8")
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print(line)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(r.returncode)


def cycle():
    run("collector.py")
    run("analyze.py")
    print("cycle ok")


if __name__ == "__main__":
    if "--loop" in sys.argv:
        print(f"持续监测模式：每 {INTERVAL} 秒一个周期，Ctrl+C 停止")
        while True:
            try:
                cycle()
            except Exception as e:
                print("cycle failed:", e, file=sys.stderr)
            time.sleep(INTERVAL)
    else:
        cycle()

