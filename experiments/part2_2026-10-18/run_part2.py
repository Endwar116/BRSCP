#!/usr/bin/env python3
"""BRSCP 第二部分：新基準與可調閥（協德，2026-10-18；設計見 00_預先登錄.md）。

9 組交叉：題庫格式 {自然語言 nl、SIC-JS 3.0 記帳格式 sicjs、SIC-JS 3.0＋說明 sicjs_primer} × 協議 {不加 none、保守端 v07、交付端 v10}。
4 個模型家族（10-18 真題探針通過）× 100 題（M01–M100）＝ 3600 次，一次跑完。
呼叫、解析、評分全部沿用 1.0 驗收實驗的凍結 runner（import 進來用，不改它）：遇 404／410 標下架不換備援；金鑰只經 hive._key()。
用法：
  python3 run_part2.py smoke     試跑 M01 × 9 組 × glm（寫 data/smoke.jsonl，不進分析）
  python3 run_part2.py run       正式跑（寫 data/results.jsonl，可中斷續跑；開始與結束時間記在 data/run_window.jsonl）
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("BRSCP_ACCEPT_DIR", "acceptance_runner"))  # 1.0 驗收實驗的凍結 runner（未公開）
import run_accept as RA  # noqa: E402

QB = os.environ.get("BRSCP_QBANK_DIR", "qbank_v3_ordering")  # 題庫（未公開，見 README）
POOL_B = open(f"{QB}/pool_B_natural.txt", encoding="utf-8").read()
METAS = RA.METAS + json.load(open(os.path.join(HERE, "data", "META_M51-M100.json"), encoding="utf-8"))
MODELS = {"nvidia/nemotron-3-super-120b-a12b": 4, "openai/gpt-oss-20b": 3, "z-ai/glm-5.3-flash": 3, "deepseek-ai/deepseek-v4.1-flash": 3}
FORMATS = ["nl", "sicjs", "sicjs_primer"]
PROTOCOLS = ["none", "v07", "v10"]
OUT = os.path.join(HERE, "data", "results.jsonl")
WINDOW = os.path.join(HERE, "data", "run_window.jsonl")


def pool(fmt):
    return {"nl": POOL_B, "sicjs": RA.POOL_A, "sicjs_primer": RA.PRIMER + "\n" + RA.POOL_A}[fmt]


def prompt(fmt, proto, m):
    p = pool(fmt)
    if proto == "none":
        return p + RA.naked_ord(m)
    if proto == "v07":
        return RA.L0_V07 + RA.BRIDGE_V07 + p + RA.naked_ord(m)
    if proto == "v10":
        return RA.G10 + RA.BRIDGE_V10 + p + RA.ord_v10(m, risk=False)
    raise ValueError(proto)


def one(model, fmt, proto, m):
    r = RA.call(model, prompt(fmt, proto, m))
    p = RA.first_json(r["raw"])
    s = RA.seq_of(p)
    gt = RA.gt_of(m)
    ts = str((p or {}).get("task_status", "")).lower()
    return dict(task_status=ts, seq=s, seq_correct=(s == gt), frac=round(RA.frac_of(s, gt), 3), parse_fail=(p is None), parsed=p, **r)


def run(out_path, models, metas):
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            x = json.loads(line)
            if "error" not in x:
                done.add((x["model"], x["fmt"], x["proto"], x["mid"]))
    todo = [(mo, f, pr, m) for m in metas for f in FORMATS for pr in PROTOCOLS for mo in models
            if (mo, f, pr, m["mid"]) not in done]
    sem = {mo: threading.Semaphore(n) for mo, n in models.items()}
    dead, lock, cnt = set(), threading.Lock(), [0]
    with open(WINDOW, "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": "start", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "todo": len(todo), "done_before": len(done)}, ensure_ascii=False) + "\n")
    print(f"待跑 {len(todo)}（已完成 {len(done)}）", flush=True)

    def work(c):
        mo, f, pr, m = c
        if mo in dead:
            return
        rec = dict(model=mo, fmt=f, proto=pr, cell=f"{f}×{pr}", mid=m["mid"], k=m["k"], at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        with sem[mo]:
            try:
                rec.update(one(mo, f, pr, m))
            except RA.ModelDead as e:
                dead.add(mo)
                rec["error"] = f"model_dead: {e}"
            except Exception as e:
                rec["error"] = str(e)[:160]
        with lock:
            with open(out_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            cnt[0] += 1
            if cnt[0] % 50 == 0 or cnt[0] == len(todo):
                print(f"[{cnt[0]}/{len(todo)}] {time.strftime('%H:%M')} {mo.split('/')[-1]} {f}×{pr} {m['mid']}", flush=True)

    with ThreadPoolExecutor(max_workers=sum(models.values())) as ex:
        list(ex.map(work, todo))
    with open(WINDOW, "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": "end", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "dead": sorted(dead)}, ensure_ascii=False) + "\n")
    print("死掉的模型：" + ("、".join(sorted(dead)) or "無"), flush=True)


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "smoke":
        run(os.path.join(HERE, "data", "smoke.jsonl"), {"z-ai/glm-5.3-flash": 3}, METAS[:1])
    elif c == "run":
        run(OUT, MODELS, METAS)
    else:
        sys.exit(__doc__)
