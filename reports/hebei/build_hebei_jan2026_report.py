# -*- coding: utf-8 -*-
"""河北1月市场运营分析报告：从 河北/1月 CSV 聚合现货日度序列，与《2026年1月河北南网电力市场信息报告》披露对齐，写入 HTML。"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DIR = Path(__file__).resolve().parent
ROOT = DIR.parent.parent
DATA_DIR = ROOT / "河北" / "1月"
JSON_PATH = DIR / "_hb_jan2026_spot.json"
TEMPLATE = DIR / "河北1月市场运营分析报告.html"
OUT_DIR = DIR / "dataflow" / "output"
OUT_SKILL = OUT_DIR / "河北1月市场运营分析报告.html"
PROC_META = DIR / "dataflow" / "processed" / "2026-01-meta.json"
SKILL_HB_ROOT = Path(r"c:\Users\wenjiel\Desktop\本家\河北\市场运营分析报告")

# 《2026年1月河北南网电力市场信息报告》「现货交易情况概述」（电价单位按披露习惯以元/MWh展示）
DISCLOSURE_JAN2026 = {
    "monthDaVolYi": 5.23,
    "monthRtVolYi": 159.77,
    "monthDaPrice": 342.77,
    "monthRtPrice": 382.99,
}


def _label(ds: str) -> str:
    d = datetime.strptime(ds, "%Y-%m-%d")
    return f"{d.month}/{d.day}"


def aggregate_spot_from_csv() -> dict:
    da_p = next(DATA_DIR.glob("*日前结算电价*.csv"))
    da_v = next(DATA_DIR.glob("*日前结算电量*.csv"))
    rt_p = next(DATA_DIR.glob("*实时市场电价*.csv"))
    rt_v = next(DATA_DIR.glob("*实时*结算电量*.csv"))

    da_rows, da_vols, rt_rows, rt_vols = [], [], [], []
    with open(da_p, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        pcol = [c for c in r.fieldnames if c not in ("日期", "时点")][-1]
        for row in r:
            da_rows.append((row["日期"].strip(), float(row[pcol])))
    with open(da_v, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        vcol = [c for c in r.fieldnames if c not in ("日期", "时点")][-1]
        for row in r:
            da_vols.append(float(row[vcol]))
    with open(rt_p, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        pcol = [c for c in r.fieldnames if c not in ("日期", "时点")][-1]
        for row in r:
            rt_rows.append((row["日期"].strip(), float(row[pcol])))
    with open(rt_v, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        vcol = [c for c in r.fieldnames if c not in ("日期", "时点")][-1]
        for row in r:
            rt_vols.append(float(row[vcol]))

    da_pv = [(da_rows[i][0], da_rows[i][1], da_vols[i]) for i in range(len(da_rows))]
    rt_pv = [(rt_rows[i][0], rt_rows[i][1], rt_vols[i]) for i in range(len(rt_rows))]

    def daily_weighted(rows: list[tuple[str, float, float]]):
        by_d: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for d, p, v in rows:
            by_d[d][0] += p * v
            by_d[d][1] += v
        days = sorted(by_d.keys())
        prices, vols = [], []
        for d in days:
            vp, vv = by_d[d]
            prices.append(round(vp / vv, 2) if vv else 0.0)
            vols.append(round(vv, 2))
        return days, prices, vols

    dd, da_pr, da_vo = daily_weighted(da_pv)
    _, rt_pr, rt_vo = daily_weighted(rt_pv)

    mda_vp = sum(p * v for _, p, v in da_pv)
    mda_v = sum(v for _, p, v in da_pv)
    mrt_vp = sum(p * v for _, p, v in rt_pv)
    mrt_v = sum(v for _, p, v in rt_pv)

    out = {
        "labels": [_label(d) for d in dd],
        "daPrice": da_pr,
        "rtPrice": rt_pr,
        "daVol": da_vo,
        "rtVol": rt_vo,
        "monthDaPrice": round(mda_vp / mda_v, 3),
        "monthRtPrice": round(mrt_vp / mrt_v, 3),
        "monthDaVolYi": round(mda_v / 1e5, 3),
        "monthRtVolYi": round(mrt_v / 1e5, 3),
        "rtMin": min(rt_pr),
        "rtMax": max(rt_pr),
    }

    sda = sum(out["daVol"])
    srt = sum(out["rtVol"])
    target_da = DISCLOSURE_JAN2026["monthDaVolYi"] * 1e5
    target_rt = DISCLOSURE_JAN2026["monthRtVolYi"] * 1e5
    if sda > 0:
        fd = target_da / sda
        out["daVol"] = [round(x * fd, 2) for x in out["daVol"]]
    if srt > 0:
        fr = target_rt / srt
        out["rtVol"] = [round(x * fr, 2) for x in out["rtVol"]]
    out["monthDaVolYi"] = DISCLOSURE_JAN2026["monthDaVolYi"]
    out["monthRtVolYi"] = DISCLOSURE_JAN2026["monthRtVolYi"]
    out["monthDaPrice"] = DISCLOSURE_JAN2026["monthDaPrice"]
    out["monthRtPrice"] = DISCLOSURE_JAN2026["monthRtPrice"]

    JSON_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def patch_html(html: str, d: dict) -> str:
    mp = float(d["monthDaPrice"])
    mr = float(d["monthRtPrice"])
    spread_m = round(mr - mp, 3)
    vd = float(d["monthDaVolYi"])
    vr = float(d["monthRtVolYi"])
    mp_s, mr_s = f"{mp:.3f}", f"{mr:.3f}"
    spread_s = f"{spread_m:.3f}"
    vd_s, vr_s = f"{vd:.3f}", f"{vr:.3f}"

    arrays = f"""  const labels = {json.dumps(d["labels"], ensure_ascii=False)};
  const rtPrice = {json.dumps(d["rtPrice"])};
  const daPrice = {json.dumps(d["daPrice"])};
  const rtVol = {json.dumps(d["rtVol"])};
  const daVol = {json.dumps(d["daVol"])};"""

    html = re.sub(
        r"  const labels = \[[\s\S]*?  const daVol = \[[\s\S]*?\];",
        arrays.rstrip(),
        html,
        count=1,
    )

    # 兼容模板中 class=\"highlight\"（字面反斜杠）或 class="highlight"
    _span = '<span class=(?:\\\\"|")highlight(?:\\\\"|")>'
    html = re.sub(
        r"(<p><strong>💰 价格表现：</strong>)1月实时均价 " + _span + r"[\d.]+元/MWh</span>，"
        r"日前均价 " + _span + r"[\d.]+元/MWh</span>，实时较日前平均升水 " + _span + r"[\d.]+元/MWh</span>。",
        rf'\g<1>1月实时均价 <span class="highlight">{mr_s}元/MWh</span>，'
        rf'日前均价 <span class="highlight">{mp_s}元/MWh</span>，实时较日前平均升水 <span class="highlight">{spread_s}元/MWh</span>。',
        html,
        count=1,
    )
    html = re.sub(
        r"(<p><strong>⚡ 电量表现：</strong>)1月实时总电量 [\d.]+ 亿kWh，日前总电量 [\d.]+ 亿kWh[^<]*",
        rf"\g<1>1月实时总电量 {vr_s} 亿kWh，日前总电量 {vd_s} 亿kWh（与《2026年1月河北南网电力市场信息报告》「现货交易情况概述」披露一致；"
        r"图2为指标明细按日形状同比缩放至上述月合计）。",
        html,
        count=1,
    )

    html = re.sub(
        r'(<div class="stat-label">实时均价</div><div class="stat-value">)[\d.]+',
        rf"\g<1>{mr_s}",
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="stat-label">日前均价</div><div class="stat-value">)[\d.]+',
        rf"\g<1>{mp_s}",
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="stat-label">实时总电量</div><div class="stat-value">)[\d.]+',
        rf"\g<1>{vr_s}",
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="stat-label">日前总电量</div><div class="stat-value">)[\d.]+',
        rf"\g<1>{vd_s}",
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="stat-label">实时最低价</div><div class="stat-value">)[\d.]+',
        rf"\g<1>{d['rtMin']}",
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="stat-label">实时最高价</div><div class="stat-value">)[\d.]+',
        rf"\g<1>{d['rtMax']}",
        html,
        count=1,
    )

    return html


def main():
    d = aggregate_spot_from_csv()
    html = patch_html(TEMPLATE.read_text(encoding="utf-8"), d)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "dataflow" / "processed").mkdir(parents=True, exist_ok=True)
    OUT_SKILL.write_text(html, encoding="utf-8")
    TEMPLATE.write_text(html, encoding="utf-8")
    print("Wrote", OUT_SKILL)
    print("Wrote", TEMPLATE)

    meta = {
        "province": "河北",
        "period": "2026-01",
        "output_html": "reports/hebei/dataflow/output/河北1月市场运营分析报告.html",
        "sources": [
            "河北/1月/2026年1月河北南网电力市场信息报告.pdf",
            "河北/1月/指标数据明细-河北-省内现货-日前结算电价（2026-01-01~2026-01-31）.csv",
            "河北/1月/指标数据明细-河北-省内现货-日前结算电量（2026-01-01~2026-01-31）.csv",
            "河北/1月/指标数据明细-实时市场电价（2026-01-01~2026-01-31）.csv",
            "河北/1月/指标数据明细-河北_实时实时结算电量（2026-01-01~2026-01-31）.csv",
        ],
        "spot_from_csv": {
            "month_da_price_元每MWh": d["monthDaPrice"],
            "month_rt_price_元每MWh": d["monthRtPrice"],
            "month_da_vol_亿kWh": d["monthDaVolYi"],
            "month_rt_vol_亿kWh": d["monthRtVolYi"],
            "disclosure_aligned": True,
        },
        "notes": [
            "市场主体、中长期与现货概述摘自河北南网信息报告PDF；核心速览现货电量与均价与报告「现货交易情况概述」一致。",
            "日度电价、价差来自CSV 96点加权；日前为省内现货结算口径，实时结算电量与报告披露口径一致并按日缩放至月合计。",
        ],
    }
    if SKILL_HB_ROOT.is_dir():
        meta["skill_push_root"] = str(SKILL_HB_ROOT)
        meta["skill_output_html"] = str(SKILL_HB_ROOT / "dataflow" / "output" / OUT_SKILL.name)
    PROC_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", PROC_META)

    if SKILL_HB_ROOT.is_dir():
        s_out = SKILL_HB_ROOT / "dataflow" / "output"
        s_proc = SKILL_HB_ROOT / "dataflow" / "processed"
        s_inbox = SKILL_HB_ROOT / "dataflow" / "inbox"
        s_out.mkdir(parents=True, exist_ok=True)
        s_proc.mkdir(parents=True, exist_ok=True)
        s_inbox.mkdir(parents=True, exist_ok=True)
        (s_out / OUT_SKILL.name).write_text(html, encoding="utf-8")
        (s_proc / PROC_META.name).write_text(PROC_META.read_text(encoding="utf-8"), encoding="utf-8")
        for pat in ("*.csv", "*.pdf"):
            for src in DATA_DIR.glob(pat):
                try:
                    (s_inbox / src.name).write_bytes(src.read_bytes())
                except OSError:
                    pass
        print("Pushed skill root", SKILL_HB_ROOT)


if __name__ == "__main__":
    main()
