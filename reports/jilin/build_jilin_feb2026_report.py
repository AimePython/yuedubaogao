# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, json, re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r'c:\Users\wenjiel\Desktop\市场洞察网站')
J2 = ROOT / '吉林' / '2月'
TPL = ROOT / 'reports' / 'jilin' / '吉林电力市场2026年1月市场运营分析报告.html'
OUT = ROOT / 'reports' / 'jilin' / '吉林电力市场2026年2月市场运营分析报告.html'
OUT_DF = ROOT / 'reports' / 'jilin' / 'dataflow' / 'output' / '吉林2月市场运营分析报告.html'
META = ROOT / 'reports' / 'jilin' / 'dataflow' / 'processed' / '2026-02-meta.json'
SKILL = Path(r'c:\Users\wenjiel\Desktop\本家\吉林\市场运营分析报告')


def _label(ds: str) -> str:
    d = datetime.strptime(ds, '%Y-%m-%d')
    return f'{d.month}/{d.day}'


def load_price(path: Path):
    out = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        r = csv.DictReader(f)
        col = [c for c in r.fieldnames if c not in ('日期', '时点')][0]
        for row in r:
            raw = (row[col] or '').strip()
            try:
                val = float(raw)
            except Exception:
                val = None
            out.append((row['日期'].strip(), val))
    return out


da_rows = load_price(next(J2.glob('*日前*24点*.csv')))
rt_rows = load_price(next(J2.glob('*实时*24点*.csv')))

by_da: dict[str, list[float]] = defaultdict(list)
by_rt: dict[str, list[float]] = defaultdict(list)
for d, v in da_rows:
    if v is not None:
        by_da[d].append(v)
for d, v in rt_rows:
    if v is not None:
        by_rt[d].append(v)

days = sorted(by_da)
labels = [_label(d) for d in days]
da_daily = [round(sum(by_da[d]) / len(by_da[d]), 3) for d in days]
rt_daily = [round(sum(by_rt[d]) / len(by_rt[d]), 3) if by_rt[d] else None for d in days]

month_da = round(sum(da_daily) / len(da_daily), 3)
rt_vals = [x for x in rt_daily if x is not None]
month_rt = round(sum(rt_vals) / len(rt_vals), 3) if rt_vals else None
avg_spread = round(month_rt - month_da, 3) if month_rt is not None else None

da_min = min(da_daily)
da_max = max(da_daily)

html = TPL.read_text(encoding='utf-8')

# Header/title
html = html.replace('吉林电力市场运营分析 · 2026年1月', '吉林电力市场运营分析 · 2026年2月')
html = html.replace('基于吉林省2026年1月电力交易信息披露与现货24点披露价格', '基于吉林省2026年2月电力交易信息披露与现货24点披露价格')
html = html.replace('信息披露关键指标（1月）', '信息披露关键指标（2月）')
html = html.replace('现货市场图表看板（1月）', '现货市场图表看板（2月）')
html = html.replace('1月关键数据表', '2月关键数据表')
html = html.replace('<thead><tr><th>指标</th><th>1月数据</th></tr></thead>', '<thead><tr><th>指标</th><th>2月数据</th></tr></thead>')
html = html.replace(
    '电量与均价来自《2026年1月电力市场交易信息报告》发电侧结算；生物质披露原文单位为「千瓦时」此处按亿千瓦时理解（与合计86.92一致）。',
    '电量与均价来自《2026年2月电力市场交易信息报告》发电侧结算；生物质披露原文单位为「千瓦时」此处按亿千瓦时理解（与合计66.61一致）。',
)

# Core insight block
html = re.sub(
    r'<div class="insight-box">[\s\S]*?</div>\s*<div class="stats-grid">',
    (
        '<div class="insight-box">\n'
        f'      <p><strong>价格表现（现货披露）：</strong>2月日前统一结算点日均价算术均值 <span class="highlight">{month_da:.3f}元/MWh</span>；实时统一结算点电价披露为 <span class="highlight">--</span>（全月缺失），因此不计算实时月均价与价差。</p>\n'
        '      <p><strong>结算表现（信息披露）：</strong>全省发电企业上网结算电量 <span class="highlight">66.610亿kWh</span>，结算均价 <span class="highlight">350.847元/MWh</span>。</p>\n'
        '      <p><strong>中长期交易：</strong>2月月度双边协商成交 <span class="highlight">1.66亿kWh</span>（340.41元/MWh），月度集中成交 <span class="highlight">0.507亿kWh</span>（342.621元/MWh）；信息披露口径下，2月省内月内交易2.34亿kWh、代理购电3.94亿kWh、月内滚动4.7亿kWh、日滚动1.5亿kWh，年度交易中2月成交42.11亿kWh。</p>\n'
        '      <p><strong>运行特征：</strong>截至2月末市场成员7208户；市场违规与干预披露均为「无」。</p>\n'
        '    </div>\n'
        '    <div class="stats-grid">'
    ),
    html,
    count=1,
)
html = html.replace(
    '数据来源：《吉林省2026年1月份电力交易信息发布文稿》、2026年度集中竞价/月内交易/合同转让/代理购电成交通报；现货曲线来自「现货披露价格·统一结算点电价·24点」指标明细（2026-01-01—01-31）。</footer>',
    '',
)

# Stats cards
html = re.sub(
    r'<div class="stats-grid">[\s\S]*?</div>\s*</div>\s*\n\s*<div class="card">',
    (
        '    <div class="stats-grid">\n'
        f'      <div class="stat-item"><div class="stat-label">现货披露·日前日均价（月均值）</div><div class="stat-value">{month_da:.3f}<span class="stat-unit">元/MWh</span></div></div>\n'
        '      <div class="stat-item"><div class="stat-label">现货披露·实时日均价（月均值）</div><div class="stat-value">--<span class="stat-unit">元/MWh</span></div></div>\n'
        '      <div class="stat-item"><div class="stat-label">发电侧结算电量</div><div class="stat-value">66.610<span class="stat-unit">亿kWh</span></div></div>\n'
        '      <div class="stat-item"><div class="stat-label">发电侧结算均价</div><div class="stat-value">350.847<span class="stat-unit">元/MWh</span></div></div>\n'
        f'      <div class="stat-item"><div class="stat-label">日前日均价最低日均值</div><div class="stat-value">{da_min:.3f}<span class="stat-unit">元/MWh</span></div></div>\n'
        f'      <div class="stat-item"><div class="stat-label">日前日均价最高日均值</div><div class="stat-value">{da_max:.3f}<span class="stat-unit">元/MWh</span></div></div>\n'
        '    </div>\n'
        '  </div>\n\n  <div class="card">'
    ),
    html,
    count=1,
)

# Info key table rows
html = re.sub(
    r'<tbody id="infoKeyBody">[\s\S]*?</tbody>',
    '<tbody id="infoKeyBody">\n'
    '          <tr><td>全社会用电量</td><td>88.38亿kWh（同比+3.5%）</td></tr>\n'
    '          <tr><td>全口径发电量</td><td>91.59亿kWh（同比-3.78%）</td></tr>\n'
    '          <tr><td>发电装机（2月末）</td><td>5198.9万kW（同比+9.95%）</td></tr>\n'
    '          <tr><td>注册市场成员</td><td>7208户（同比+1817户）</td></tr>\n'
    '          <tr><td>发电利用小时</td><td>392小时（同比-27小时）</td></tr>\n'
    '        </tbody>',
    html,
    count=1,
)

# Chart titles
html = html.replace('图1：实时/日前日均价趋势（24点算术平均）', '图1：日前日均价趋势（24点算术平均）')
html = html.replace('图3：实时-日前价差（日度）', '图3：日前日均价柱状图（日度）')
html = html.replace('图4：日度价格波动区间（日前与实时日均价）', '图4：日前日均价趋势补充')
html = html.replace('正值为实时升水，负值为贴水。', '2月实时统一结算点电价披露为缺失值（--），本图展示日前日均价。')

# trade summary rows
html = re.sub(
    r'<tbody id="tradeSummaryBody">[\s\S]*?</tbody>',
    '<tbody id="tradeSummaryBody">\n'
    '          <tr><td>2026年度交易中2月成交（信息披露）</td><td>42.11</td><td>—</td><td>累计合同54.59亿kWh</td></tr>\n'
    '          <tr><td>2月月度双边协商交易</td><td>1.66</td><td>340.41</td><td>40家发电、25家用电侧成交</td></tr>\n'
    '          <tr><td>2月月度集中交易</td><td>0.507</td><td>342.621</td><td>147家发电、8家用电侧成交</td></tr>\n'
    '          <tr><td>2月省内月内交易（3次）</td><td>2.34</td><td>—</td><td>信息披露口径</td></tr>\n'
    '          <tr><td>2月代理购电交易（2次）</td><td>3.94</td><td>—</td><td>信息披露口径</td></tr>\n'
    '          <tr><td>2月月内滚动撮合（4次）</td><td>4.7</td><td>—</td><td>信息披露口径</td></tr>\n'
    '          <tr><td>2月日滚动撮合（19次）</td><td>1.5</td><td>—</td><td>信息披露口径</td></tr>\n'
    '          <tr><td>合同转让交易（2月）</td><td>3.36</td><td>—</td><td>信息披露口径（涉及合同）</td></tr>\n'
    '        </tbody>',
    html,
    count=1,
)

# Generation settlement table
html = re.sub(
    r'<h3>发电侧分类型结算（信息披露）</h3>[\s\S]*?<footer>',
    '<h3>发电侧分类型结算（信息披露）</h3>\n'
    '    <div class="overflow-x-auto">\n'
    '      <table>\n'
    '        <thead><tr><th>电源类型</th><th>结算电量（亿kWh）</th><th>结算均价（元/MWh）</th></tr></thead>\n'
    '        <tbody>\n'
    '          <tr><td>火电</td><td>32.94</td><td>495.851</td></tr>\n'
    '          <tr><td>风电</td><td>25.10</td><td>172.879</td></tr>\n'
    '          <tr><td>光伏</td><td>4.24</td><td>254.598</td></tr>\n'
    '          <tr><td>生物质（含垃圾）</td><td>4.30</td><td>372.375</td></tr>\n'
    '          <tr><td>水电</td><td>0.03</td><td>492.316</td></tr>\n'
    '          <tr><td>合计</td><td>66.61</td><td>350.847（加权）</td></tr>\n'
    '        </tbody>\n'
    '      </table>\n'
    '    </div>\n'
    '  </div>\n\n'
    '  <footer>数据来源：《吉林省2026年2月份电力交易信息发布文稿》、2026年2月月度集中交易与双边协商交易成交通报；现货曲线来自「现货披露价格·统一结算点电价·24点」指标明细（2026-02-01—02-28）。注：实时统一结算点电价披露全月为缺失值（--）。</footer>',
    html,
    count=1,
)

labels_js = json.dumps(labels, ensure_ascii=False)
da_js = json.dumps(da_daily)
rt_js = json.dumps(rt_daily)

script1 = f'''<script>
  if (window.Chart) {{ Chart.defaults.devicePixelRatio = Math.max(window.devicePixelRatio || 1, 2); }}
  const labels = {labels_js};
  const rtPrice = {rt_js};
  const daPrice = {da_js};
  const genLabels = ["火电", "风电", "光伏", "生物质", "水电"];
  const genVol = [32.94, 25.10, 4.24, 4.30, 0.03];
  const genPrice = [495.851, 172.879, 254.598, 372.375, 492.316];

  const hasRt = rtPrice.some(v => v !== null && Number.isFinite(v));
  const spread = rtPrice.map((v, i) => (v === null || !Number.isFinite(v)) ? null : +(v - daPrice[i]).toFixed(2));
  const rangeLow = rtPrice.map((v, i) => (v === null || !Number.isFinite(v)) ? daPrice[i] : Math.min(v, daPrice[i]));
  const rangeHigh = rtPrice.map((v, i) => (v === null || !Number.isFinite(v)) ? daPrice[i] : Math.max(v, daPrice[i]));
  const spreadValid = spread.filter(v => v !== null && Number.isFinite(v));
  const avgSpread = spreadValid.length ? spreadValid.reduce((a, b) => a + b, 0) / spreadValid.length : null;
  const maxSpread = spreadValid.length ? Math.max(...spreadValid) : null;
  const minSpread = spreadValid.length ? Math.min(...spreadValid) : null;
  const maxSpreadIdx = spreadValid.length ? spread.indexOf(maxSpread) : -1;
  const minSpreadIdx = spreadValid.length ? spread.indexOf(minSpread) : -1;

  const baseOption = {{ responsive: true, plugins: {{ legend: {{ position: "top" }} }}, scales: {{ x: {{ ticks: {{ maxTicksLimit: 12 }} }} }} }};

  const priceSets = [
    {{ label: "日前日均价", data: daPrice, borderColor: "#f97316", backgroundColor: "rgba(249,115,22,.15)", tension: 0.25, pointRadius: 1.6 }}
  ];
  if (hasRt) {{
    priceSets.unshift({{ label: "实时日均价", data: rtPrice, borderColor: "#2563eb", backgroundColor: "rgba(37,99,235,.15)", tension: 0.25, pointRadius: 1.6 }});
  }}

  new Chart(document.getElementById("priceChart"), {{
    type: "line",
    data: {{ labels, datasets: priceSets }},
    options: baseOption
  }});

  new Chart(document.getElementById("genMixChart"), {{
    type: "bar",
    data: {{
      labels: genLabels,
      datasets: [{{
        label: "结算电量（亿kWh）",
        data: genVol,
        backgroundColor: ["#c62828", "#2e7d32", "#f9a825", "#6a1b9a", "#0277bd"],
        borderWidth: 0
      }}]
    }},
    options: {{ ...baseOption, scales: {{ x: {{ ticks: {{ maxTicksLimit: 12 }} }}, y: {{ title: {{ display: true, text: "亿kWh" }}, beginAtZero: true }} }} }}
  }});

  new Chart(document.getElementById("spreadChart"), {{
    type: "bar",
    data: {{
      labels,
      datasets: [{{
        label: hasRt ? "实时-日前价差" : "日前日均价",
        data: hasRt ? spread : daPrice,
        backgroundColor: hasRt ? spread.map(v => (v === null ? "rgba(156,163,175,.5)" : (v >= 0 ? "rgba(37,99,235,.65)" : "rgba(239,68,68,.65)"))) : "rgba(37,99,235,.65)",
        borderColor: hasRt ? spread.map(v => (v === null ? "#9ca3af" : (v >= 0 ? "#2563eb" : "#ef4444"))) : "#2563eb",
        borderWidth: 1
      }}]
    }},
    options: {{ ...baseOption, scales: {{ ...baseOption.scales, y: {{ title: {{ display: true, text: "元/MWh" }} }} }} }}
  }});

  new Chart(document.getElementById("rangeChart"), {{
    type: "line",
    data: {{
      labels,
      datasets: [
        {{ label: "区间上沿", data: rangeHigh, borderColor: "#0ea5e9", backgroundColor: "rgba(14,165,233,0.2)", tension: 0.2, pointRadius: 0, fill: false }},
        {{ label: "区间下沿", data: rangeLow, borderColor: "#0ea5e9", backgroundColor: "rgba(14,165,233,0.2)", tension: 0.2, pointRadius: 0, fill: "+1" }}
      ]
    }},
    options: {{ ...baseOption, plugins: {{ ...baseOption.plugins, tooltip: {{ mode: "index", intersect: false }} }} }}
  }});

  const fmt = (v) => (v === null || !Number.isFinite(v)) ? '--' : v.toFixed(3);
  const spreadBody = document.getElementById("spreadDetailBody");
  spreadBody.innerHTML = labels.map((d, i) =>
    `<tr><td>${{d}}</td><td>${{fmt(rtPrice[i])}}</td><td>${{fmt(daPrice[i])}}</td><td>${{fmt(spread[i])}}</td></tr>`
  ).join("") + (hasRt ? `
    <tr style="background:#f4f8fb;font-weight:600;"><td>全月平均</td><td>-</td><td>-</td><td>${{avgSpread.toFixed(3)}}</td></tr>
    <tr style="background:#f9fbfd;"><td>最大价差日</td><td>-</td><td>-</td><td>${{maxSpread.toFixed(3)}}（${{labels[maxSpreadIdx]}}）</td></tr>
    <tr style="background:#f9fbfd;"><td>最小价差日</td><td>-</td><td>-</td><td>${{minSpread.toFixed(3)}}（${{labels[minSpreadIdx]}}）</td></tr>
  ` : `
    <tr style="background:#f4f8fb;font-weight:600;"><td>说明</td><td colspan="3">2月实时统一结算点电价披露为缺失值（--），价差相关指标不适用。</td></tr>
  `);
</script>'''

html = re.sub(r'<script>\s*if \(window\.Chart\)[\s\S]*?</script>', script1, html, count=1)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT_DF.parent.mkdir(parents=True, exist_ok=True)
META.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding='utf-8')
OUT_DF.write_text(html, encoding='utf-8')

meta = {
    'province':'吉林',
    'period':'2026-02',
    'output_html':'reports/jilin/dataflow/output/吉林2月市场运营分析报告.html',
    'sources':[str(p) for p in sorted(J2.glob('*'))],
    'spot_from_csv':{
        'method':'日前24点电价按日简单平均并再按日平均；实时字段全月缺失（--）。',
        'month_da_price_元每MWh': month_da,
        'month_rt_price_元每MWh': None,
        'avg_spread_元每MWh': None,
        'da_min_daily_avg_元每MWh': da_min,
        'da_max_daily_avg_元每MWh': da_max,
    },
    'notes':[
        '实时统一结算点电价24点限价CSV全月均为缺失值（--），未计算实时均价/价差。',
        '发电侧结算、生物质口径及中长期交易量价取自2月信息披露和月度交易通报。'
    ]
}
META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

if SKILL.is_dir():
    (SKILL / 'dataflow' / 'output').mkdir(parents=True, exist_ok=True)
    (SKILL / 'dataflow' / 'processed').mkdir(parents=True, exist_ok=True)
    (SKILL / 'dataflow' / 'inbox').mkdir(parents=True, exist_ok=True)
    (SKILL / 'dataflow' / 'output' / OUT_DF.name).write_text(html, encoding='utf-8')
    (SKILL / 'dataflow' / 'processed' / META.name).write_text(META.read_text(encoding='utf-8'), encoding='utf-8')
    for src in J2.glob('*'):
        if src.is_file():
            try:
                (SKILL / 'dataflow' / 'inbox' / src.name).write_bytes(src.read_bytes())
            except OSError:
                pass

print('Wrote', OUT)
print('Wrote', OUT_DF)
print('Wrote', META)
