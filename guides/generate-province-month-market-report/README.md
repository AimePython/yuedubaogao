## Generate Province Month Market Report

This folder documents conventions for consistently generating **province monthly market insight HTML** pages in this repo.

Default section naming convention follows Jiangsu template: `江苏1月市场经营分析报告_完整版.html`.

### What it produces

- One HTML file in repo root (same folder level as `index.html`)
- Reuses the Zhejiang report proven layout:
  - `核心速览`
  - `市场供需情况 & 关键指标月度对比`
  - `集中竞价交易 (YYYY年M月)` / `交易组织与结算情况`
  - `现货市场交易 (M月)` (monthly summary, daily trends, daily detail table, 48-point intraday curves, monthly 48-point volume-weighted average curve)
  - `分时曲线（24小时）- 真实数据` (standalone module, with date selector + 2 charts + 4-stat summary strip)
  - `市场运行关注点`

### Required inputs (typical)

1. Province month official `docx` (narrative + monthly facts)
2. Province month spot detail `xlsx` (日期/时点/日前电量+电价/实时电量+电价)

### Spot (48-point) computations

For each day:
- Build arrays of length `48`:
  - `daPrice[48]`, `rtPrice[48]`
  - `daVolWanKWh[48]`, `rtVolWanKWh[48]` (MWh -> 万kWh via `*0.1`)
  - Daily weighted averages:
    - `daAvg = Σ(price * vol) / Σ(vol)`
    - `rtAvg = Σ(price * vol) / Σ(vol)`

For full month 48-point curve:
- For each period `i`:
  - `daWeighted[i] = Σ_day(price_i * vol_i) / Σ_day(vol_i)`
  - `rtWeighted[i] = Σ_day(price_i * vol_i) / Σ_day(vol_i)`

### Stability rules (important)

- Prefer embedding spot data into the HTML JS to avoid `fetch(local.xlsx)` failures (common with `file://` and some iframe/CORS cases).
- Validate:
  - Spot date range matches the claimed month.
  - Units in labels match computed data.
  - Monthly summary equals the aggregation of daily details.
  - 24h time-curve module always exists as an independent section and uses consistent visual style.

### Output verification checklist

Before finalizing:

1. HTML renders without console errors.
2. Spot daily table shows all parsed days.
3. Dropdown contains `YYYY-MM-DD` options.
4. Selecting a date updates the 48-point price/volume charts.
5. Monthly weighted 48-point curve is non-empty.
6. “Core summary” price numbers align with the spot computations.
7. No misleading mixing of settlement price vs spot weighted price in the same sentence.
8. Charts fit their cards and do not collapse/overlap text.
9. Only the requested parts are edited (avoid unrelated layout drift).
10. If user asks to retune visuals (height/width), adjust only target chart ids/classes.
11. Time-curve module follows shared UI baseline (selector row + dual charts + summary strip) across provinces.

