# -*- coding: utf-8 -*-
"""Build 江苏3月市场运行分析报告.html from 江苏2月 template + March 2026 data."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

BASE_USER = Path(r"c:\Users\wenjiel\Desktop\本家\江苏\市场运营分析报告")
XLSX = BASE_USER / "江苏省-现货价格-价格趋势-数据明细（2026-03-01~2026-03-31）.xlsx"
CSV_DA = BASE_USER / "指标数据明细-日前出清电量_市场运营（2026-03-01~2026-03-31）.csv"
CSV_RT = BASE_USER / "指标数据明细-实时出清电量_市场运营（2026-03-01~2026-03-31）.csv"

REPO = Path(__file__).resolve().parent
FEB_HTML = REPO / "江苏2月市场运行分析报告.html"
OUT_HTML = REPO / "江苏3月市场运行分析报告.html"
OUT_OUTPUT = REPO / "dataflow" / "output" / "江苏3月市场运行分析报告.html"


def load_merged():
    px = pd.read_excel(XLSX, sheet_name=0)
    cols = list(px.columns)
    px = px.rename(columns={cols[1]: "da_price", cols[2]: "rt_price"})
    px["da_price"] = pd.to_numeric(px["da_price"], errors="coerce")
    px["rt_price"] = pd.to_numeric(px["rt_price"], errors="coerce")
    px["row_id"] = range(len(px))

    def vol_csv(p: Path):
        df = pd.read_csv(p, encoding="utf-8-sig")
        c = list(df.columns)
        df = df.rename(columns={c[0]: "date", c[1]: "time_slot", c[2]: "vol_mwh"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["vol_mwh"] = pd.to_numeric(df["vol_mwh"], errors="coerce")
        df["row_id"] = range(len(df))
        return df

    da_v = vol_csv(CSV_DA)
    rt_v = vol_csv(CSV_RT)
    m_da = pd.merge(px[["row_id", "da_price"]], da_v, on="row_id")
    m_rt = pd.merge(px[["row_id", "rt_price"]], rt_v, on="row_id")
    return m_da, m_rt


def add_hour_index(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for d, g in df.groupby("date", sort=True):
        g = g.reset_index(drop=True).copy()
        g["hr"] = (pd.Series(range(len(g))) // 4).astype(int).clip(upper=23)
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def build_daily_spot(m_da: pd.DataFrame, m_rt: pd.DataFrame):
    def wavg(g, pc, vc):
        num = (g[pc] * g[vc]).sum()
        den = g[vc].sum()
        return float(num / den) if den else float("nan"), float(den)

    daily = []
    dates = sorted(m_da["date"].unique())
    for d in dates:
        gda = m_da[m_da["date"] == d]
        grt = m_rt[m_rt["date"] == d]
        p_da, _ = wavg(gda, "da_price", "vol_mwh")
        p_rt, _ = wavg(grt, "rt_price", "vol_mwh")
        daily.append({"date": d, "daPrice": p_da, "rtPrice": p_rt})
    return daily


def build_hourly_real(m_da: pd.DataFrame, m_rt: pd.DataFrame) -> dict:
    m_da = add_hour_index(m_da)
    m_rt = add_hour_index(m_rt)
    out = {}
    for d in sorted(m_da["date"].unique()):
        gda = m_da[m_da["date"] == d].sort_values("hr")
        grt = m_rt[m_rt["date"] == d].sort_values("hr")
        da_p = [float("nan")] * 24
        da_v = [0.0] * 24
        rt_p = [float("nan")] * 24
        rt_v = [0.0] * 24
        for _, r in gda.iterrows():
            h = int(r["hr"])
            if 0 <= h < 24:
                num = r["da_price"] * r["vol_mwh"]
                da_v[h] += float(r["vol_mwh"])
                # store numerator for weighted combine
                if da_p[h] != da_p[h]:  # nan check
                    da_p[h] = 0.0
                da_p[h] += float(num)
        for hi in range(24):
            if da_v[hi] > 0:
                da_p[hi] = da_p[hi] / da_v[hi]
            else:
                da_p[hi] = 0.0
        for _, r in grt.iterrows():
            h = int(r["hr"])
            if 0 <= h < 24:
                num = r["rt_price"] * r["vol_mwh"]
                rt_v[h] += float(r["vol_mwh"])
                if rt_p[h] != rt_p[h]:
                    rt_p[h] = 0.0
                rt_p[h] += float(num)
        for hi in range(24):
            if rt_v[hi] > 0:
                rt_p[hi] = rt_p[hi] / rt_v[hi]
            else:
                rt_p[hi] = 0.0
        da_tot = sum(da_v)
        rt_tot = sum(rt_v)
        da_w = sum(da_p[i] * da_v[i] for i in range(24)) / da_tot if da_tot else 0.0
        rt_w = sum(rt_p[i] * rt_v[i] for i in range(24)) / rt_tot if rt_tot else 0.0
        out[d] = {
            "daPrice": da_p,
            "rtPrice": rt_p,
            "daVol": da_v,
            "rtVol": rt_v,
            "daTotalVol": da_tot,
            "rtTotalVol": rt_tot,
            "daWeightedPrice": da_w,
            "rtWeightedPrice": rt_w,
        }
    return out


def fmt_js_obj_hourly(data: dict) -> str:
    """Format hourlyRealData like existing template (2-space indent per key)."""
    lines = ["        const hourlyRealData = {"]
    keys = sorted(data.keys())
    for i, k in enumerate(keys):
        v = data[k]
        lines.append(f'    "{k}": {{')
        for subk in ["daPrice", "rtPrice", "daVol", "rtVol"]:
            arr = v[subk]
            lines.append(f'        "{subk}": [')
            chunk = ",\n            ".join(json.dumps(x) for x in arr)
            lines.append("            " + chunk)
            lines.append("        ],")
        lines.append(f'        "daTotalVol": {v["daTotalVol"]},')
        lines.append(f'        "rtTotalVol": {v["rtTotalVol"]},')
        lines.append(f'        "daWeightedPrice": {repr(v["daWeightedPrice"])},')
        lines.append(f'        "rtWeightedPrice": {repr(v["rtWeightedPrice"])}')
        lines.append("    }," if i < len(keys) - 1 else "    }")
    lines.append("};")
    return "\n".join(lines)


def fmt_daily_spot_js(arr: list) -> str:
    lines = ["        const dailySpotMar = ["]
    for d in arr:
        lines.append("        {")
        lines.append(f'                "date": "{d["date"]}",')
        lines.append(f'                "daPrice": {d["daPrice"]},')
        lines.append(f'                "rtPrice": {d["rtPrice"]}')
        lines.append("        },")
    lines.append("];")
    return "\n".join(lines)


def main():
    m_da, m_rt = load_merged()
    daily = build_daily_spot(m_da, m_rt)
    hourly = build_hourly_real(m_da, m_rt)

    # monthly totals (96-point weighted)
    da_num = (m_da["da_price"] * m_da["vol_mwh"]).sum()
    da_den = m_da["vol_mwh"].sum()
    rt_num = (m_rt["rt_price"] * m_rt["vol_mwh"]).sum()
    rt_den = m_rt["vol_mwh"].sum()
    da_m = float(da_num / da_den)
    rt_m = float(rt_num / rt_den)
    da_vol_yi = round(float(da_den) / 1e5, 2)
    rt_vol_yi = round(float(rt_den) / 1e5, 2)

    feb = FEB_HTML.read_text(encoding="utf-8")
    s = feb

    # --- Global titles / labels ---
    s = s.replace("<title>江苏2月市场运行分析报告</title>", "<title>江苏3月市场运行分析报告</title>")
    s = s.replace("江苏2月市场运行分析报告", "江苏3月市场运行分析报告")
    s = s.replace("基于江苏电力交易中心2月交易信息报告", "基于江苏电力交易中心3月交易信息报告")
    s = s.replace("2026年2月《江苏电网电力市场交易信息报告》", "2026年3月《江苏电网电力市场交易信息报告》")
    s = s.replace("2月集中竞价交易结果公示", "3月集中竞价交易结果公示")
    s = s.replace("2026-02-01—02-28", "2026-03-01—03-31")
    s = s.replace("全月28天", "全月31天")
    s = s.replace("截至2026年2月累计用电量", "截至2026年3月累计用电量")
    s = s.replace("'截至2026年2月累计用电量'", "'截至2026年3月累计用电量'")

    # --- Core insight (replace whole insight box inner HTML) ---
    core_new = """            <p><strong>💰 市场价格对比与波动</strong><br>
            3月月度集中竞价（无约束出清）成交电量 <span class="highlight">80.38亿kWh</span>，加权均价 <span class="highlight">317.62元/MWh</span>。发电侧：火电64.66亿kWh均价317.98元/MWh，风电0.96亿kWh均价314.94元/MWh，光伏0.30亿kWh均价314.00元/MWh，核电14.45亿kWh均价316.30元/MWh。<br>
            现货市场出清（电量加权，基于统一结算点电价 xlsx 与日前/实时出清电量 csv 按行序对齐）：3月日前均价 <span class="highlight">""" + f"{da_m:.2f}" + """元/MWh</span>，出清电量约""" + f"{da_vol_yi:.2f}" + """亿kWh；实时均价 <span class="highlight">""" + f"{rt_m:.2f}" + """元/MWh</span>，出清电量约""" + f"{rt_vol_yi:.2f}" + """亿kWh。<br>
            绿电交易：省内绿电4.59亿kWh（年度分月计划3.02亿kWh@405.18元/MWh、月度1.28亿kWh@405.89元/MWh、月内0.29亿kWh@394.52元/MWh）；省间绿电7.72亿kWh@349.74元/MWh。<br>
            <strong>成因简析：</strong> 1）3月工商业复工达产、气温回升带动负荷，现货价格在部分时段高于2月春节月；2）中长期直接交易372.94亿kWh、均价331.09元/MWh，能量块55.88亿kWh、均价297.75元/MWh，反映锁价与灵活交易并行；3）现货分时仍呈早晚高峰特征，可结合下方分时图查看。</p>
            <p><strong>📌 用电与市场供需：</strong> 截至3月底全社会用电量累计 <strong>2104.06亿kWh</strong>（同比+5.59%）。分产业累计：第一产业18.01亿kWh（+9.72%），第二产业1383.19亿kWh（+4.42%），第三产业384.83亿kWh（+9.22%），城乡居民生活318.03亿kWh（+6.27%）。下方「分产业用电量」表含 <strong>1—3月单月</strong>；3月各产业由「1—3月累计」与「1—2月累计」差分推算。</p>
            <p><strong>📈 中长期市场：</strong> 3月全月直接交易电量372.94亿kWh，均价331.09元/MWh；其中年度交易225.11亿kWh（均价344.93）、集中竞价88.19亿kWh（均价315.73）、能量块55.88亿kWh（均价297.75）、月度及月内绿电3.76亿kWh（均价358.58）。与表「市场化交易情况」一致。</p>
            <p><strong>⚡ 现货与结算：</strong> 3月用电侧结算合计855.95亿kWh，均价337.06元/MWh（直接交易用户14.87亿kWh@333.18、售电公司420.54亿kWh@326.49、零售市场420.54亿kWh@347.76）。现货不平衡及结构性偏差等费用详见信息披露报告。</p>
            <p><strong>📊 市场主体：</strong> 截至3月31日，江苏电力市场经营主体共计194535家，其中发电企业2546家，售电公司438家，电力用户191426家（一类24家、二类191402家）；独立储能67家、虚拟电厂58家。</p>
            <p class="note">注：现货出清均价按96点电价与出清电量加权核算；与月结算均价口径不同。分产业累计、中长期与结算数据来自《2026年3月江苏电网电力市场交易信息报告》；集中竞价来自《2026年3月江苏电力市场集中竞价交易结果公示》。</p>"""

    s = re.sub(
        r'<div class="insight-box" id="coreInsight">[\s\S]*?</div>\s*</div>\s*\n\s*<!-- 市场供需模块 -->',
        '<div class="insight-box" id="coreInsight">\n' + core_new + "\n        </div>\n    </div>\n\n    <!-- 市场供需模块 -->",
        s,
        count=1,
    )

    # --- consumptionData ---
    cons = """
        const consumptionData = [
        {
                "month": "2026年1月",
                "total": 815.58,
                "primary": 6.42,
                "secondary": 530.61,
                "tertiary": 148.69,
                "residential": 129.86
        },
        {
                "month": "2026年2月",
                "total": 552.71,
                "primary": 5.24,
                "secondary": 335.6,
                "tertiary": 111.63,
                "residential": 100.24
        },
        {
                "month": "2026年3月",
                "total": 735.77,
                "primary": 6.35,
                "secondary": 516.98,
                "tertiary": 124.51,
                "residential": 87.92
        }
];"""
    s = re.sub(
        r"const consumptionData = \[[\s\S]*?\];",
        cons.strip(),
        s,
        count=1,
    )

    # --- capacityData month label ---
    s = re.sub(r'"monthLabel": "2026年2月"', '"monthLabel": "2026年3月"', s, count=1)

    # --- generationData table body template (披露未更新，标*) ---
    s = s.replace(
        "<tr><td>2026年2月</td><td>${g.type}</td>",
        "<tr><td>2026年3月*</td><td>${g.type}</td>",
    )
    s = s.replace(
        "注：市场主体数据截至2026年2月28日",
        "注：市场主体数据截至2026年3月31日",
    )
    s = s.replace(
        "注：现货每日均价基于Excel文件96点电价加权平均计算。",
        "注：发电量结构表*：本月收到的《交易信息报告》电子版未附发电量分项，暂沿用2月报告同表数值仅作版式参考，正式分析请以官方后续披露为准。现货每日均价基于电价明细与出清电量加权。",
    )

    # --- city consumption (亿kWh, 万kWh/10000) ---
    city_js = """
        const cityConsumption = [
            { name: "南京", value: 198.77 }, { name: "苏州", value: 450.97 }, { name: "无锡", value: 218.48 },
            { name: "徐州", value: 127.20 }, { name: "常州", value: 163.62 }, { name: "镇江", value: 78.82 },
            { name: "扬州", value: 93.37 }, { name: "泰州", value: 101.82 }, { name: "南通", value: 188.11 },
            { name: "盐城", value: 126.98 }, { name: "淮安", value: 83.66 }, { name: "宿迁", value: 80.27 },
            { name: "连云港", value: 97.47 }
        ];"""
    s = re.sub(r"const cityConsumption = \[[\s\S]*?\];", city_js.strip(), s, count=1)

    # --- hourly auction ---
    hv = [3.87, 4.08, 4.56, 5.02, 4.35, 4.68, 3.45, 3.33, 2.26, 1.78, 1.69, 1.66, 1.61, 1.67, 1.66, 3.05, 3.8, 4, 3.83, 4.01, 4.02, 3.83, 3.74, 4.43]
    hp = [318, 316.85, 320, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 312.8, 330, 331.5, 330, 320, 320, 320, 320, 312.8]
    auc_lines = ["        const hourlyAuction = ["]
    for i in range(24):
        auc_lines.append(
            f'            {{ hour: "{i+1}时", vol: {hv[i]}, price: {hp[i]} }},'
        )
    auc_lines.append("        ];")
    s = re.sub(r"const hourlyAuction = \[[\s\S]*?\];", "\n".join(auc_lines), s, count=1)

    gen_side = """        const genSide = [
            { type: "火电", vol: 64.66, price: 317.98 }, { type: "风电", vol: 0.96, price: 314.94 },
            { type: "光伏", vol: 0.30, price: 314.00 }, { type: "核电", vol: 14.45, price: 316.30 },
            { type: "发电类虚拟电厂", vol: 0.00024, price: 316.90 }
        ];"""
    buy_side = """        const buySide = [
            { type: "售电公司", vol: 48.61, price: 317.92 }, { type: "一类用户", vol: 0.37, price: 317.26 },
            { type: "国网代理购电", vol: 31.40451, price: 317.17 }
        ];"""
    s = re.sub(r"const genSide = \[[\s\S]*?\];", gen_side.strip(), s, count=1)
    s = re.sub(r"const buySide = \[[\s\S]*?\];", buy_side.strip(), s, count=1)

    # --- spot summary ---
    spot_sum = f"""        const spotSummary = [
        {{
                "market": "日前市场",
                "volume": {da_vol_yi},
                "price": {da_m}
        }},
        {{
                "market": "实时市场",
                "volume": {rt_vol_yi},
                "price": {rt_m}
        }}
];"""
    s = re.sub(r"const spotSummary = \[[\s\S]*?\];", spot_sum.strip(), s, count=1)

    # --- daily spot block ---
    daily_js = fmt_daily_spot_js(daily)
    s = re.sub(r"const dailySpotFeb = \[[\s\S]*?\];", daily_js.strip(), s, count=1)
    s = s.replace("dailySpotFeb", "dailySpotMar")

    # --- hourly real data (large block: splice by anchor) ---
    hourly_js = fmt_js_obj_hourly(hourly)
    h0 = s.index("        const hourlyRealData = {")
    h1 = s.index("\n        const hourLabels", h0)
    s = s[:h0] + hourly_js.strip() + "\n" + s[h1:]

    # --- green / settlement / participants ---
    green = """        const greenPower = [
            { type: "年度绿电分月计划", vol: 3.02, price: 405.18 },
            { type: "月度绿电交易", vol: 1.28, price: 405.89 },
            { type: "月内绿电交易", vol: 0.29, price: 394.52 },
            { type: "省间绿电交易", vol: 7.72, price: 349.74 }
        ];"""
    sett = """        const settlement = [
            { type: "批发市场-直接交易用户", vol: 14.87, price: 333.18 },
            { type: "批发市场-售电公司", vol: 420.54, price: 326.49 },
            { type: "零售市场", vol: 420.54, price: 347.76 },
            { type: "合计", vol: 855.95, price: 337.06 }
        ];"""
    part = """        const participants = [
            { type: "发电企业", count: 2546 },
            { type: "售电公司", count: 438 },
            { type: "独立储能企业", count: 67 },
            { type: "虚拟电厂", count: 58 },
            { type: "电力用户", count: 191426 }
        ];"""
    s = re.sub(r"const greenPower = \[[\s\S]*?\];", green.strip(), s, count=1)
    s = re.sub(r"const settlement = \[[\s\S]*?\];", sett.strip(), s, count=1)
    s = re.sub(r"const participants = \[[\s\S]*?\];", part.strip(), s, count=1)

    # --- charts: industry bar (March only) ---
    s = s.replace(
        "label: '2026年2月用电量', data: [5.24, 335.6, 111.63, 100.24]",
        "label: '2026年3月用电量', data: [6.35, 516.98, 124.51, 87.92]",
    )

    # --- section headings 2月 -> 3月 in cards ---
    s = re.sub(r"集中竞价交易 \(2026年2月\)", "集中竞价交易 (2026年3月)", s)
    s = re.sub(r"现货市场交易 \(2月\)", "现货市场交易 (3月)", s)
    s = re.sub(r"📈 2月现货市场每日出清均价趋势", "📈 3月现货市场每日出清均价趋势", s)
    s = re.sub(r"📋 2月现货市场每日明细表", "📋 3月现货市场每日明细表", s)
    s = re.sub(r"🔹 2月集中竞价分时段", "🔹 3月集中竞价分时段", s)

    # --- footer ---
    s = s.replace(
        "数据基于江苏电力交易中心2026年2月《江苏电网电力市场交易信息报告》、2月集中竞价交易结果公示，以及现货出清与统一结算点电价明细（2026-02-01—02-28）。分时曲线由96点电量与电价按24时段聚合。",
        "数据基于江苏电力交易中心2026年3月《江苏电网电力市场交易信息报告》、3月集中竞价交易结果公示，以及现货出清与统一结算点电价明细（2026-03-01—03-31）。分时曲线由96点电量与电价按24时段聚合。",
    )

    # --- Excel export filename（先整体替换报告名后，需再替换月份后缀）---
    s = s.replace("江苏2月市场运行分析报告_2026年2月.xlsx", "江苏3月市场运行分析报告_2026年3月.xlsx")
    s = s.replace("江苏3月市场运行分析报告_2026年2月.xlsx", "江苏3月市场运行分析报告_2026年3月.xlsx")

    cdn_scripts = """    <script src="https://cdn.sheetjs.com/xlsx-0.20.2/package/dist/xlsx.full.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.0.0/dist/chartjs-plugin-datalabels.min.js"></script>"""
    local_reports = """    <script src="../../assets/xlsx.full.min.js"></script>
    <script src="../../assets/chart.umd.min.js"></script>
    <script src="../../assets/chartjs-plugin-datalabels.min.js"></script>"""
    local_output = """    <script src="../../../assets/xlsx.full.min.js"></script>
    <script src="../../../assets/chart.umd.min.js"></script>
    <script src="../../../assets/chartjs-plugin-datalabels.min.js"></script>"""

    OUT_HTML.write_text(s.replace(cdn_scripts, local_reports), encoding="utf-8")
    OUT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUT_OUTPUT.write_text(s.replace(cdn_scripts, local_output), encoding="utf-8")
    print("Wrote", OUT_HTML)
    print("Wrote", OUT_OUTPUT)


if __name__ == "__main__":
    main()
