"""M1 — Efficiency Audit: MFU/MBU, the GPU-Util lie, and idle waste (deck §5).

Run: python missions/m1_efficiency_audit.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from collections import defaultdict
from missions._common import load_csv, num, catalog_by_type
from finops import metrics


def run(verbose: bool = True) -> dict:
    tel = load_csv("gpu_telemetry.csv")
    cat = catalog_by_type()

    # per-row MFU/MBU, then aggregate per GPU
    agg = defaultdict(lambda: {"util": [], "mfu": [], "mbu": [], "type": None, "idle_hours": 0})
    for r in tel:
        gtype = r["gpu_type"]
        peak_fp16 = num(cat[gtype]["peak_tflops_fp16"])
        peak_bw = num(cat[gtype]["peak_bw_tbs"])
        mfu = metrics.compute_mfu(num(r["achieved_tflops"]), peak_fp16)
        mbu = metrics.compute_mbu(num(r["achieved_bw_tbs"]), peak_bw)
        a = agg[r["gpu_id"]]
        a["type"] = gtype
        a["util"].append(num(r["gpu_util_pct"]))
        a["mfu"].append(mfu)
        a["mbu"].append(mbu)
        if num(r["gpu_util_pct"]) < 10:  # effectively idle this interval (1h)
            a["idle_hours"] += 1

    summary = []
    for gid, a in agg.items():
        gpu_type = a["type"]
        current_catalog = cat[gpu_type]
        summary.append({
            "gpu_id": gid, "gpu_type": gpu_type,
            "gpu_util_pct": round(sum(a["util"]) / len(a["util"]), 1),
            "mfu": round(sum(a["mfu"]) / len(a["mfu"]), 3),
            "mbu": round(sum(a["mbu"]) / len(a["mbu"]), 3),
            "idle_hours": a["idle_hours"],
            # Useful for comparing memory-bound inference hardware.
            "usd_per_gb_vram": round(
                num(current_catalog["on_demand_hr"]) / num(current_catalog["hbm_gb"]), 4
            ),
        })

    # Extension 2: right-size memory-bound workloads.  Preserve the observed
    # bandwidth while targeting at most 60% MBU, and require equal VRAM so the
    # recommendation does not silently reduce model capacity.
    target_mbu = 0.60
    right_sizing = []
    for s in summary:
        current = cat[s["gpu_type"]]
        achieved_bw = s["mbu"] * num(current["peak_bw_tbs"])
        required_peak_bw = achieved_bw / target_mbu if target_mbu else float("inf")
        candidates = []
        for candidate_type, candidate in cat.items():
            if (
                num(candidate["hbm_gb"]) >= num(current["hbm_gb"])
                and num(candidate["peak_bw_tbs"]) >= required_peak_bw
            ):
                candidates.append((num(candidate["on_demand_hr"]), candidate_type, candidate))
        candidates.sort(key=lambda x: (x[0], x[1]))
        chosen = candidates[0] if candidates else (
            num(current["on_demand_hr"]), s["gpu_type"], current
        )
        right_sizing.append({
            "gpu_id": s["gpu_id"],
            "current_gpu": s["gpu_type"],
            "mbu": s["mbu"],
            "achieved_bw_tbs": round(achieved_bw, 3),
            "recommended_gpu": chosen[1],
            "recommended_usd_hr": chosen[0],
            "hourly_savings": round(max(0.0, num(current["on_demand_hr"]) - chosen[0]), 4),
        })
        s["right_size_gpu"] = chosen[1]

    recommendations = [r for r in right_sizing if r["mbu"] < target_mbu and r["hourly_savings"] > 0]

    lies = metrics.flag_util_lies(summary)
    idle_waste = 0.0
    for s in summary:
        on_demand = num(catalog_by_type()[s["gpu_type"]]["on_demand_hr"])
        idle_waste += metrics.idle_waste_usd(s["idle_hours"], on_demand)

    if verbose:
        print("== M1 Efficiency Audit ==")
        print(f"{'GPU':14}{'type':7}{'util%':>7}{'MFU':>7}{'MBU':>7}{'idle_h':>8}")
        for s in sorted(summary, key=lambda x: x["mfu"]):
            print(f"{s['gpu_id']:14}{s['gpu_type']:7}{s['gpu_util_pct']:>7}{s['mfu']:>7}{s['mbu']:>7}{s['idle_hours']:>8}")
        print(f"\nGPU-Util LIES (util>=90% but MFU<30%): {[l['gpu_id'] for l in lies]}")
        print(f"Idle waste (1 day): ${idle_waste:,.2f}  ->  ${idle_waste*30:,.0f}/month")
        print("\nRight-sizing candidates (memory-bound, target MBU=60%):")
        for r in recommendations:
            print(
                f"  {r['gpu_id']}: {r['current_gpu']} -> {r['recommended_gpu']} "
                f"(${r['hourly_savings']:.2f}/GPU-hr saved)"
            )

    return {
        "summary": summary,
        "lies": lies,
        "idle_waste_daily": round(idle_waste, 2),
        "right_sizing": right_sizing,
        "right_sizing_savings": recommendations,
    }


if __name__ == "__main__":
    run()
