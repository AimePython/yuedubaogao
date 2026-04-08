# 将江西市场运营分析报告及相关数据流产出提交并推送到 GitHub（remote 见仓库 .git/config）
# 用法：在已安装 Git 且已配置 origin 的环境中执行
#   cd 本仓库\reports\jiangxi
#   powershell -ExecutionPolicy Bypass -File .\push-github.ps1
#
# 说明：reports.json 中 jiangxi 各月已映射至 reports/jiangxi/ 下对应 HTML。
# 根目录 reports.json 若存在则一并暂存（与河北/江苏 push-github.ps1 一致）。

$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error 'git not found in PATH. Install Git for Windows or add git.exe to PATH.'
}
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $RepoRoot

$rel = @(
    'reports/jiangxi/build_jiangxi_jan2026_report.py',
    'reports/jiangxi/build_jiangxi_feb2026_report.py',
    'reports/jiangxi/_jx_jan2026_spot.json',
    'reports/jiangxi/江西电力市场2026年1月市场运营分析报告.html',
    'reports/jiangxi/江西电力市场2026年2月市场运营分析报告.html',
    'reports/jiangxi/dataflow/output/江西1月市场运营分析报告.html',
    'reports/jiangxi/dataflow/output/江西2月市场运营分析报告.html',
    'reports/jiangxi/dataflow/processed/2026-01-meta.json',
    'reports/jiangxi/dataflow/processed/2026-02-meta.json',
    'reports/jiangxi/push-github.ps1',
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
    Write-Host 'Nothing to stage (already committed or paths missing).'
    git status -sb
    exit 0
}

git commit -m "chore(jiangxi): publish Feb 2026 Jiangxi monthly operations report"
if ($LASTEXITCODE -ne 0) { Write-Error "git commit failed (exit $LASTEXITCODE)." }
$branch = (git branch --show-current).Trim()
if (-not $branch) { Write-Error 'Could not detect current git branch.' }
git push origin $branch
if ($LASTEXITCODE -ne 0) { Write-Error "git push failed (exit $LASTEXITCODE)." }
Write-Host "Pushed branch: $branch -> origin"
