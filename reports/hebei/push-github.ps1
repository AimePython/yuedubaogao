# 将河北 1 月市场运营分析报告及相关数据流产出提交并推送到 GitHub（remote 见仓库 .git/config）
# 用法：在已安装 Git 且已配置 origin 的环境中执行
#   cd 本仓库\reports\hebei
#   powershell -ExecutionPolicy Bypass -File .\push-github.ps1
#
# 说明：reports.json 中 hebei / 2026-01 映射至
#   reports/hebei/河北1月市场运营分析报告.html

$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error '未在 PATH 中找到 git。请安装 Git for Windows 或将 git.exe 加入 PATH 后重试。'
}
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $RepoRoot

$rel = @(
    'reports/hebei/build_hebei_jan2026_report.py',
    'reports/hebei/_hb_jan2026_spot.json',
    'reports/hebei/河北1月市场运营分析报告.html',
    'reports/hebei/dataflow/output/河北1月市场运营分析报告.html',
    'reports/hebei/dataflow/processed/2026-01-meta.json',
    'reports/hebei/push-github.ps1',
    'reports.json'
)
foreach ($p in $rel) {
    $full = Join-Path $RepoRoot $p
    if (Test-Path -LiteralPath $full) {
        git add -- $p
    }
}

$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host '没有可暂存的变更（可能已提交或路径不存在）。'
    git status -sb
    exit 0
}

git commit -m "chore(hebei): publish Jan 2026 Hebei monthly operations report"
$branch = (git branch --show-current).Trim()
if (-not $branch) { Write-Error '无法检测当前分支。' }
git push origin $branch
Write-Host "已推送分支: $branch -> origin"
