# ============================================================================
#  sync-to-github.ps1  --  一键把源码同步到 GitHub
# ---------------------------------------------------------------------------
#  仓库: https://github.com/xiaoqiu0505/AIprogram
#
#  用法（在 PowerShell 里执行）:
#      cd "D:\New Program"
#      powershell -ExecutionPolicy Bypass -File .\sync-to-github.ps1
#
#  自动完成:
#    1. 检查 API Key 泄露（关键）
#    2. 检查 git 状态
#    3. 拉取远程 + 自动合并分叉
#    4. 提交本地改动
#    5. 推送（失败自动重试 3 次）
#    6. 打印结果
# ============================================================================

[CmdletBinding()]
param(
    [string]$RepoDir = "D:\New Program",
    [string]$Branch  = "main",
    [string]$Message = "",
    [switch]$SkipKeyCheck,
    [switch]$Force
)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Step { param($n, $text) Write-Host ""; Write-Host ("  [" + $n + "] " + $text) -ForegroundColor Cyan }
function Ok   { param($text) Write-Host ("      OK  " + $text) -ForegroundColor Green }
function Warn { param($text) Write-Host ("      !   " + $text) -ForegroundColor Yellow }
function Fail { param($text) Write-Host ("      X   " + $text) -ForegroundColor Red }
function Info { param($text) Write-Host ("          " + $text) -ForegroundColor Gray }

Write-Host ""
Write-Host "  ============================================" -ForegroundColor White
Write-Host "   源码同步到 GitHub" -ForegroundColor White
Write-Host "   https://github.com/xiaoqiu0505/AIprogram" -ForegroundColor White
Write-Host "  ============================================" -ForegroundColor White

# ---- 0. 目录检查 ----
if (-not (Test-Path $RepoDir)) { Fail ("目录不存在: " + $RepoDir); exit 1 }
Set-Location $RepoDir
if (-not (Test-Path ".git")) { Fail ("不是 git 仓库: " + $RepoDir); exit 1 }

# ---- 1. 安全检查 ----
if (-not $SkipKeyCheck) {
    Step "1/6" "检查是否有 API Key 泄露..."

    $keyScan = Join-Path $RepoDir "check_no_keys.py"
    if (Test-Path $keyScan) {
        $env:PYTHONIOENCODING = "utf-8"
        $scanText = (& python $keyScan 2>&1) -join "`n"

        if ($scanText -match "LEAK") {
            Fail "发现 API Key 泄露！已中止同步"
            Info ""
            ($scanText -split "`n") | Where-Object { $_ -match "LEAK" } | ForEach-Object { Info $_.Trim() }
            Info ""
            Info "请先清理这些文件里的 Key，再重新运行。"
            exit 1
        }
        Ok "没有发现 Key 泄露"
    } else {
        Warn "找不到 check_no_keys.py，跳过检查"
    }

    $bad = & git ls-files 2>&1 | Where-Object { $_ -match "config\.json|\.env$|secret" }
    if ($bad) {
        Fail "以下敏感文件已被 git 跟踪："
        $bad | ForEach-Object { Info $_ }
        Info "用 git rm --cached 文件名 移除后再同步"
        exit 1
    }
    Ok "敏感文件未被跟踪"
} else {
    Step "1/6" "跳过 Key 检查 (-SkipKeyCheck)"
}

# ---- 2. git 状态 ----
Step "2/6" "检查本地改动..."

$statusLines = @(& git status --porcelain 2>&1 | Where-Object { $_ -and $_.Trim() })
$changedCount = $statusLines.Count
if ($changedCount -gt 0) { Ok ("You " + $changedCount + " 个文件改动") }
else { Ok "工作区干净" }

$currentBranch = (& git rev-parse --abbrev-ref HEAD 2>&1).Trim()
Info ("当前分支: " + $currentBranch)

$remoteUrl = (& git remote get-url origin 2>&1).Trim()
if (-not $remoteUrl) { Fail "没有配置 origin 远程"; exit 1 }
Info ("远程: " + $remoteUrl)

if ($remoteUrl -notmatch "xiaoqiu0505/AIprogram") {
    Warn "远程地址和预期不符"
    if (-not $Force) { Info "确认没问题请加 -Force 继续"; exit 1 }
    & git remote set-url origin "https://github.com/xiaoqiu0505/AIprogram.git"
    Ok "已修正远程地址"
}

# ---- 3. 拉取并合并 ----
Step "3/6" "同步远程最新代码..."

$fetched = $false
for ($i = 1; $i -le 3; $i++) {
    & git fetch origin $Branch 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $fetched = $true; break }
    Warn ("拉取失败（第 " + $i + " 次），2 秒后重试...")
    Start-Sleep -Seconds 2
}
if (-not $fetched) { Fail "无法连接 GitHub"; Info "请检查网络后重试"; exit 1 }
Ok "远程信息已获取"

$divOut = (& git rev-list --left-right --count ("origin/" + $Branch + "...HEAD") 2>&1)
if ($LASTEXITCODE -eq 0) {
    $parts = @(($divOut -split "\s+") | Where-Object { $_ -ne "" })
    if ($parts.Count -ge 2) {
        $remoteOnly = [int]$parts[0]
        $localOnly  = [int]$parts[1]
        Info ("远程独有: " + $remoteOnly + " 个提交   本地独有: " + $localOnly + " 个提交")

        if ($remoteOnly -gt 0 -and $localOnly -gt 0) {
            Warn "本地和远程已分叉，自动合并..."

            $stashed = $false
            if ($changedCount -gt 0) {
                & git stash push -u -m "auto-stash" 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $stashed = $true; Info "已暂存本地改动" }
            }

            & git merge ("origin/" + $Branch) --no-edit -X ours 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Warn "普通合并失败，尝试允许无关历史..."
                & git merge ("origin/" + $Branch) --no-edit --allow-unrelated-histories -X ours 2>&1 | Out-Null
            }

            if ($LASTEXITCODE -eq 0) {
                Ok "合并完成"
            } else {
                Fail "自动合并失败，需要手动处理"
                (& git status --short 2>&1) | Select-Object -First 10 | ForEach-Object { Info $_ }
                Info ""
                Info "手动处理: git merge --abort 然后手动合并"
                if ($stashed) { & git stash pop 2>&1 | Out-Null }
                exit 1
            }

            if ($stashed) { & git stash pop 2>&1 | Out-Null; Info "已恢复本地改动" }
        } elseif ($remoteOnly -gt 0) {
            Warn "远程有新提交，快进合并..."
            & git merge ("origin/" + $Branch) --no-edit -X theirs 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Ok "已同步远程" }
        } else {
            Ok ("本地领先远程 " + $localOnly + " 个提交")
        }
    }
}

# ---- 4. 提交 ----
Step "4/6" "提交本地改动..."

$pending = @(& git status --porcelain 2>&1 | Where-Object { $_ -and $_.Trim() }).Count

if ($pending -gt 0) {
    if (-not $Message) { $Message = "更新源码 " + (Get-Date -Format "yyyy-MM-dd HH:mm") }
    & git add -A 2>&1 | Out-Null
    & git commit -m $Message 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok ("已提交: " + $Message) }
    else { Warn "提交返回非 0（可能没有实际改动）" }
} else {
    Ok "没有需要提交的改动"
}

$aheadCount = (& git rev-list --count ("origin/" + $Branch + "..HEAD") 2>&1).Trim()
Info ("待推送提交: " + $aheadCount + " Ge")

# ---- 5. 推送 ----
Step "5/6" "推送到 GitHub..."

$pushed = $false
for ($i = 1; $i -le 3; $i++) {
    Info ("尝试推送（第 " + $i + " 次）...")
    $pushOut = (& git push origin ("HEAD:" + $Branch) 2>&1)
    $pushText = $pushOut -join "`n"

    if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
    if ($pushText -match "Everything up-to-date") { $pushed = $true; Ok "远程已是最新"; break }

    if ($pushText -match "rejected|non-fast-forward|fetch first") {
        Warn "远程有新提交，重新合并后重试..."
        & git fetch origin $Branch 2>&1 | Out-Null
        & git merge ("origin/" + $Branch) --no-edit -X ours 2>&1 | Out-Null
        continue
    }

    if ($pushText -match "Authentication failed|could not read Username|403") {
        Fail "认证失败"
        Info ""
        Info "解决办法（二选一）："
        Info "  方式 A: git credential-manager github login  触发登录弹窗"
        Info "  方式 B: 1) 打开 https://github.com/settings/tokens 生成 token（勾 repo 权限）"
        Info "        2) git remote set-url origin https://你的TOKEN@github.com/xiaoqiu0505/AIprogram.git"
        Info "                      （把 你的TOKEN 换成真实 token）"
        exit 1
    }

    if ($pushText -match "Connection was reset|timed out|Could not resolve|unable to access") {
        Warn "网络问题，3 秒后重试..."
        Start-Sleep -Seconds 3
        continue
    }

    Warn ("推送失败（第 " + $i + " 次）")
    ($pushText -split "`n") | Select-Object -First 6 | ForEach-Object { Info $_.Trim() }
    Start-Sleep -Seconds 2
}

if (-not $pushed) {
    Fail "推送失败，已重试 3 次"
    Info "本地提交都还在，网络恢复后重新运行本脚本即可。"
    exit 1
}
Ok "推送成功"

# ---- 6. 结果 ----
Step "6/6" "完成"

$headShort = (& git rev-parse --short HEAD 2>&1).Trim()
$headMsg = (& git log -1 --pretty=format:"%s" 2>&1).Trim()

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "   同步完成" -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ("   提交: " + $headShort + "  " + $headMsg) -ForegroundColor White
Write-Host "   仓库: https://github.com/xiaoqiu0505/AIprogram" -ForegroundColor White
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""

$open = Read-Host "  打开 GitHub 看看? (Y/n)"
if ($open -ne "n" -and $open -ne "N") {
    Start-Process "https://github.com/xiaoqiu0505/AIprogram"
}

exit 0
