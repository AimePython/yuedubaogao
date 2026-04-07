# 将河北 1–2 月市场运营分析报告及相关数据流产出提交并推送到 GitHub（remote 见仓库 .git/config）
# 用法：在已安装 Git 且已配置 origin 的环境中执行
#   cd 本仓库\reports\hebei
#   powershell -ExecutionPolicy Bypass -File .\push-github.ps1
#
# 说明：reports.json 中 hebei / 2026-01、2026-02 分别映射至
#   reports/hebei/河北1月市场运营分析报告.html
#   reports/hebei/河北2月市场运营分析报告.html

$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error 'git not found in PATH. Install Git for Windows or add git.exe to PATH.'
}
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $RepoRoot

$rel = @(
    'reports/hebei/build_hebei_jan2026_report.py',
    'reports/hebei/build_hebei_feb2026_report.py',
    'reports/hebei/_hb_jan2026_spot.json',
    'reports/hebei/_hb_feb2026_spot.json',
    'reports/hebei/河北1月市场运营分析报告.html',
    'reports/hebei/河北2月市场运营分析报告.html',
    'reports/hebei/dataflow/output/河北1月市场运营分析报告.html',
    'reports/hebei/dataflow/output/河北2月市场运营分析报告.html',
    'reports/hebei/dataflow/processed/2026-01-meta.json',
    'reports/hebei/dataflow/processed/2026-02-meta.json',
    'reports/hebei/push-github.ps1',
    'reports.json',
    '河北/',
    '_hb_feb_pdf_extract.txt'
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

git commit -m "chore(hebei): publish Jan–Feb 2026 Hebei monthly operations reports"
if ($LASTEXITCODE -ne 0) { Write-Error "git commit failed (exit $LASTEXITCODE)." }
$branch = (git branch --show-current).Trim()
if (-not $branch) { Write-Error 'Could not detect current git branch.' }
git push origin $branch
if ($LASTEXITCODE -ne 0) { Write-Error "git push failed (exit $LASTEXITCODE)." }
Write-Host "Pushed branch: $branch -> origin"
