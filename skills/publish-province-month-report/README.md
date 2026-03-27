# publish-province-month-report

用于维护“省份-年月-报告 HTML”网站的发布流程，目标是把重复操作标准化：

- 上传新的报告 HTML
- 更新 `reports.json` 映射（`provinceSlug -> YYYY-MM -> file/label`）
- （可选）替换同月旧 HTML
- 提交并推送到 GitHub Pages（`main`）

---

## 适用场景

当你有以下需求时使用本 SKILL：

- 新增某省某月报告（例如：河南 `2026-03`）
- 重发某省某月报告（同一个 `YYYY-MM`，更换为新 HTML）
- 批量连续发布多个省份报告

---

## 目录结构

```text
skills/
└── publish-province-month-report/
    ├── SKILL.md
    └── README.md
```

项目核心文件：

- `index.html`：省份入口
- `province.html`：年份/月份选择并加载报告
- `reports.json`：报告映射源（最关键）

---

## 使用方式（给 AI 的指令示例）

直接对 AI 说：

- `按 publish-province-month-report 发布 河北省 2026-03 报告`
- `按 publish-province-month-report 重发 安徽 2026-01，html 已替换`
- `按 publish-province-month-report 发布 江苏 2026-02，并同步到 GitHub Pages`

---

## reports.json 规范

映射格式：

```json
{
  "henan": {
    "2026-02": {
      "file": "河南电力市场全景分析2月.html",
      "label": "2026年2月"
    }
  }
}
```

说明：

- `provinceSlug` 需与 `index.html` 的省份 slug 一致（如 `anhui`、`shandong`、`henan`）。
- `YYYY-MM` 为月份主键。
- `file` 必须与仓库根目录实际文件名完全一致。
- `label` 用于页面展示，可读性更好，建议保留。

---

## 替换同月 HTML（重发）规则

当需要“同月重发”时：

1. 上传新 HTML 到项目根目录
2. 更新 `reports.json` 同一 `provinceSlug + YYYY-MM` 的 `file`
3. 提交新 HTML + `reports.json`
4. 如旧文件不再被任何映射引用，则删除旧文件并一并提交
5. 推送到 `main`，等待 Pages 更新

---

## 发布后验证

1. 打开：`province.html?province=<slug>`
2. 选择年份与月份（对应 `YYYY-MM`）
3. 确认 `iframe` 成功加载新报告
4. 若未更新：强制刷新（Cmd/Ctrl + Shift + R）并等待 1-2 分钟

---

## 常见问题

- 文件名不一致（最常见）
- 月份 key 写错（`2026-2` 应写成 `2026-02`）
- 推送到了非 `main` 分支
- 旧 HTML 删除过早（仍被其他月份映射引用）

---

## 维护建议

- 每次发布只提交必要文件（`reports.json` + 本次 HTML + 必要删除）
- 使用规范提交信息，便于追踪历史
- 定期清理不再被映射引用的旧报告文件

