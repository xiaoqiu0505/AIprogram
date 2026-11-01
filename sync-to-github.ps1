# ============================================================================
#  sync-to-github.ps1  --  YiJianTongBu YuanMa Dao GitHub
# ---------------------------------------------------------------------------
#  CangKu: https://github.com/xiaoqiu0505/AIprogram
#
#  YongFa (zai PowerShell li zhi xing):
#      cd "D:\New Program"
#      powershell -ExecutionPolicy Bypass -File .\sync-to-github.ps1
#
#  ZiDong WanCheng:
#    1. JianCha API Key XieLu
#    2. JianCha git ZhuangTai
#    3. LaQu YuanCheng + ZiDong HeBing FenCha
#    4. TiJiao BenDi GaiDong
#    5. TuiSong (ShiBai ZiDong ChongShi 3 Ci)
#    6. DaYin JieGuo
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
Write-Host "   TongBu YuanMa Dao GitHub" -ForegroundColor White
Write-Host "   https://github.com/xiaoqiu0505/AIprogram" -ForegroundColor White
Write-Host "  ============================================" -ForegroundColor White

# ---- 0. MuLu JianCha ----
if (-not (Test-Path $RepoDir)) { Fail ("MuLu Bu CunZai: " + $RepoDir); exit 1 }
Set-Location $RepoDir
if (-not (Test-Path ".git")) { Fail ("Bu Shi git CangKu: " + $RepoDir); exit 1 }

# ---- 1. AnQuan JianCha ----
if (-not $SkipKeyCheck) {
    Step "1/6" "JianCha API Key XieLu..."

    $keyScan = Join-Path $RepoDir "check_no_keys.py"
    if (Test-Path $keyScan) {
        $env:PYTHONIOENCODING = "utf-8"
        $scanText = (& python $keyScan 2>&1) -join "`n"

        if ($scanText -match "LEAK") {
            Fail "FaXian API Key XieLu! Yi ZhongZhi"
            Info ""
            ($scanText -split "`n") | Where-Object { $_ -match "LEAK" } | ForEach-Object { Info $_.Trim() }
            Info ""
            Info "Qing Xian QingLi ZheXie WenJian Li De Key, Zai ChongXin YunXing."
            exit 1
        }
        Ok "MeiYou FaXian Key XieLu"
    } else {
        Warn "ZhaoBuDao check_no_keys.py, TiaoGuo JianCha"
    }

    $bad = & git ls-files 2>&1 | Where-Object { $_ -match "config\.json|\.env$|secret" }
    if ($bad) {
        Fail "YiXia MinGan WenJian YiBei git GenZong:"
        $bad | ForEach-Object { Info $_ }
        Info "Yong git rm --cached WENJIAN MingLing YiChu Hou Zai TongBu"
        exit 1
    }
    Ok "MinGan WenJian WeiBei GenZong"
} else {
    Step "1/6" "TiaoGuo Key JianCha (SkipKeyCheck)"
}

# ---- 2. git ZhuangTai ----
Step "2/6" "JianCha BenDi GaiDong..."

$statusLines = @(& git status --porcelain 2>&1 | Where-Object { $_ -and $_.Trim() })
$changedCount = $statusLines.Count
if ($changedCount -gt 0) { Ok ("You " + $changedCount + " Ge WenJian GaiDong") }
else { Ok "GongZuoQu GanJing" }

$currentBranch = (& git rev-parse --abbrev-ref HEAD 2>&1).Trim()
Info ("DangQian FenZhi: " + $currentBranch)

$remoteUrl = (& git remote get-url origin 2>&1).Trim()
if (-not $remoteUrl) { Fail "MeiYou PeiZhi origin YuanCheng"; exit 1 }
Info ("YuanCheng: " + $remoteUrl)

if ($remoteUrl -notmatch "xiaoqiu0505/AIprogram") {
    Warn "YuanCheng DiZhi He YuQi BuFu"
    if (-not $Force) { Info "QueRen MeiWenTi Qing Jia -Force JiXu"; exit 1 }
    & git remote set-url origin "https://github.com/xiaoqiu0505/AIprogram.git"
    Ok "Yi XiuZheng YuanCheng DiZhi"
}

# ---- 3. LaQu HeBing ----
Step "3/6" "TongBu YuanCheng ZuiXin DaiMa..."

$fetched = $false
for ($i = 1; $i -le 3; $i++) {
    & git fetch origin $Branch 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $fetched = $true; break }
    Warn ("LaQu ShiBai (Di " + $i + " Ci), 2 Miao Hou ChongShi...")
    Start-Sleep -Seconds 2
}
if (-not $fetched) { Fail "WuFa LianJie GitHub"; Info "Qing JianCha WangLuo Hou ChongShi"; exit 1 }
Ok "YuanCheng XinXi YiHuoQu"

$divOut = (& git rev-list --left-right --count ("origin/" + $Branch + "...HEAD") 2>&1)
if ($LASTEXITCODE -eq 0) {
    $parts = @(($divOut -split "\s+") | Where-Object { $_ -ne "" })
    if ($parts.Count -ge 2) {
        $remoteOnly = [int]$parts[0]
        $localOnly  = [int]$parts[1]
        Info ("YuanCheng DuYou: " + $remoteOnly + "   BenDi DuYou: " + $localOnly)

        if ($remoteOnly -gt 0 -and $localOnly -gt 0) {
            Warn "BenDi He YuanCheng Yi FenCha, ZiDong HeBing..."

            $stashed = $false
            if ($changedCount -gt 0) {
                & git stash push -u -m "auto-stash" 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $stashed = $true; Info "Yi ZanCun BenDi GaiDong" }
            }

            & git merge ("origin/" + $Branch) --no-edit -X ours 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Warn "PuTong HeBing ShiBai, ChangShi YunXu WuGuan LiShi..."
                & git merge ("origin/" + $Branch) --no-edit --allow-unrelated-histories -X ours 2>&1 | Out-Null
            }

            if ($LASTEXITCODE -eq 0) {
                Ok "HeBing WanCheng"
            } else {
                Fail "ZiDong HeBing ShiBai"
                (& git status --short 2>&1) | Select-Object -First 10 | ForEach-Object { Info $_ }
                Info ""
                Info "ShouDong ChuLi: git merge --abort RanHou ShouDong HeBing"
                if ($stashed) { & git stash pop 2>&1 | Out-Null }
                exit 1
            }

            if ($stashed) { & git stash pop 2>&1 | Out-Null; Info "Yi HuiFu BenDi GaiDong" }
        } elseif ($remoteOnly -gt 0) {
            Warn "YuanCheng You Xin TiJiao, KuaiJin HeBing..."
            & git merge ("origin/" + $Branch) --no-edit -X theirs 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Ok "Yi TongBu YuanCheng" }
        } else {
            Ok ("BenDi LingXian YuanCheng " + $localOnly + " Ge TiJiao")
        }
    }
}

# ---- 4. TiJiao ----
Step "4/6" "TiJiao BenDi GaiDong..."

$pending = @(& git status --porcelain 2>&1 | Where-Object { $_ -and $_.Trim() }).Count

if ($pending -gt 0) {
    if (-not $Message) { $Message = "GengXin YuanMa " + (Get-Date -Format "yyyy-MM-dd HH:mm") }
    & git add -A 2>&1 | Out-Null
    & git commit -m $Message 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok ("Yi TiJiao: " + $Message) }
    else { Warn "TiJiao FanHui Fei 0 (KeNeng MeiYou ShiJi GaiDong)" }
} else {
    Ok "MeiYou XuYao TiJiao De GaiDong"
}

$aheadCount = (& git rev-list --count ("origin/" + $Branch + "..HEAD") 2>&1).Trim()
Info ("Dai TuiSong TiJiao: " + $aheadCount + " Ge")

# ---- 5. TuiSong ----
Step "5/6" "TuiSong Dao GitHub..."

$pushed = $false
for ($i = 1; $i -le 3; $i++) {
    Info ("ChangShi TuiSong (Di " + $i + " Ci)...")
    $pushOut = (& git push origin ("HEAD:" + $Branch) 2>&1)
    $pushText = $pushOut -join "`n"

    if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
    if ($pushText -match "Everything up-to-date") { $pushed = $true; Ok "YuanCheng Yi Shi ZuiXin"; break }

    if ($pushText -match "rejected|non-fast-forward|fetch first") {
        Warn "YuanCheng You Xin TiJiao, ChongXin HeBing Hou ChongShi..."
        & git fetch origin $Branch 2>&1 | Out-Null
        & git merge ("origin/" + $Branch) --no-edit -X ours 2>&1 | Out-Null
        continue
    }

    if ($pushText -match "Authentication failed|could not read Username|403") {
        Fail "RenZheng ShiBai"
        Info ""
        Info "JieJue BanFa:"
        Info "  FangShi A:  git credential-manager github login"
        Info "  FangShi B:  1) DaKai https://github.com/settings/tokens ShengCheng token (Gou repo)"
        Info "              2) git remote set-url origin https://TOKEN@g ithub.com/xiaoqiu0505/AIprogram.git"
        Info "              (Ba TOKEN HuanCheng Ni De Token)"
        exit 1
    }

    if ($pushText -match "Connection was reset|timed out|Could not resolve|unable to access") {
        Warn "WangLuo WenTi, 3 Miao Hou ChongShi..."
        Start-Sleep -Seconds 3
        continue
    }

    Warn ("TuiSong ShiBai (Di " + $i + " Ci)")
    ($pushText -split "`n") | Select-Object -First 6 | ForEach-Object { Info $_.Trim() }
    Start-Sleep -Seconds 2
}

if (-not $pushed) {
    Fail "TuiSong ShiBai, Yi ChongShi 3 Ci"
    Info "BenDi TiJiao Dou Zai, WangLuo HuiFu Hou ChongXin YunXing."
    exit 1
}
Ok "TuiSong ChengGong"

# ---- 6. JieGuo ----
Step "6/6" "WanCheng"

$headShort = (& git rev-parse --short HEAD 2>&1).Trim()
$headMsg = (& git log -1 --pretty=format:"%s" 2>&1).Trim()

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "   TongBu WanCheng" -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ("   TiJiao: " + $headShort + "  " + $headMsg) -ForegroundColor White
Write-Host "   CangKu: https://github.com/xiaoqiu0505/AIprogram" -ForegroundColor White
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""

$open = Read-Host "  DaKai GitHub KanKan? (Y/n)"
if ($open -ne "n" -and $open -ne "N") {
    Start-Process "https://github.com/xiaoqiu0505/AIprogram"
}

exit 0
