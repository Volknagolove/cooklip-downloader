param(
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$IconPath = Join-Path $ProjectRoot "cooklip.ico"
$QrcPath = Join-Path $ProjectRoot "cooklip_resources.qrc"
$RcPyPath = Join-Path $ProjectRoot "cooklip_resources_rc.py"
$TempBuildRoot = Join-Path $ProjectRoot ".build_work"
$TempDistRoot = Join-Path $ProjectRoot ".dist_work"
$TempSpecRoot = Join-Path $ProjectRoot (".spec_work_" + [guid]::NewGuid().ToString("N"))
$ReleaseRoot = Join-Path $ProjectRoot "release"

function Find-RccPath {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\Scripts\pyside6-rcc.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\Lib\site-packages\PySide6\rcc.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    try {
        $cmd = Get-Command "pyside6-rcc.exe" -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
            return $cmd.Source
        }
    } catch {
    }

    return $null
}

function Find-CommandPath {
    param(
        [string[]]$Names,
        [string[]]$CandidatePaths = @()
    )

    foreach ($candidate in $CandidatePaths) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    foreach ($name in $Names) {
        try {
            $command = Get-Command $name -ErrorAction SilentlyContinue
            if ($command -and $command.Source -and (Test-Path -LiteralPath $command.Source)) {
                return $command.Source
            }
        } catch {
        }

        try {
            $whereResult = & where.exe $name 2>$null
            foreach ($line in $whereResult) {
                if ($line -and (Test-Path -LiteralPath $line)) {
                    return (Resolve-Path -LiteralPath $line).Path
                }
            }
        } catch {
        }
    }

    return $null
}

function Ensure-CleanDir {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }

    New-Item -ItemType Directory -Path $Path | Out-Null
}

function Copy-IfFound {
    param(
        [string]$Source,
        [string]$DestinationDir
    )

    if (-not $Source) {
        return $false
    }

    if (-not (Test-Path -LiteralPath $DestinationDir)) {
        New-Item -ItemType Directory -Path $DestinationDir | Out-Null
    }

    Copy-Item -LiteralPath $Source -Destination (Join-Path $DestinationDir ([System.IO.Path]::GetFileName($Source))) -Force
    return $true
}

function Remove-OptionalFile {
    param(
        [string]$BaseDir,
        [string]$RelativePath
    )

    $target = Join-Path $BaseDir $RelativePath
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force -Recurse
    }
}

function Write-ReleaseReadme {
    param(
        [string]$Path,
        [string]$Title,
        [string[]]$HeaderLines,
        [string[]]$Notes
    )

    $content = @($Title, "") + $HeaderLines + @("") + $Notes
    $utf8Bom = [System.Text.UTF8Encoding]::new($true)
    [System.IO.File]::WriteAllLines($Path, $content, $utf8Bom)
}

function Build-App {
    param(
        [string]$Name,
        [string]$ScriptPath
    )

    $args = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name", $Name,
        "--specpath", $TempSpecRoot,
        "--workpath", $TempBuildRoot,
        "--distpath", $TempDistRoot,
        "--collect-all", "qfluentwidgets",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "PySide6.QtXml"
    )

    if (Test-Path -LiteralPath $IconPath) {
        $args += @("--icon", $IconPath)
    }

    $args += $ScriptPath
    & py @args
}

function Create-ReleaseVariant {
    param(
        [string]$BuiltAppDir,
        [string]$VariantDir,
        [string]$SettingsFileName,
        [string]$SourceExeName,
        [string]$ReleaseExeName,
        [bool]$IncludeYtDlp,
        [bool]$IncludeDeno,
        [bool]$IncludeFfmpeg,
        [string]$ReadmeTitle,
        [string[]]$ReadmeHeaderLines,
        [string[]]$ReadmeNotes
    )

    Ensure-CleanDir $VariantDir
    Copy-Item -Path (Join-Path $BuiltAppDir "*") -Destination $VariantDir -Recurse -Force

    $sourceExePath = Join-Path $VariantDir $SourceExeName
    $releaseExePath = Join-Path $VariantDir $ReleaseExeName
    if ($SourceExeName -ne $ReleaseExeName -and (Test-Path -LiteralPath $sourceExePath)) {
        Rename-Item -LiteralPath $sourceExePath -NewName $ReleaseExeName -Force
    }

    Remove-OptionalFile -BaseDir $VariantDir -RelativePath "cookies.txt"
    Remove-OptionalFile -BaseDir $VariantDir -RelativePath "cooklip_settings.json"
    Remove-OptionalFile -BaseDir $VariantDir -RelativePath "cooklip_settings_en.json"
    Remove-OptionalFile -BaseDir $VariantDir -RelativePath "data\cookies.txt"
    Remove-OptionalFile -BaseDir $VariantDir -RelativePath ("data\" + $SettingsFileName)

    $binDir = Join-Path $VariantDir "bin"
    if (!(Test-Path -LiteralPath $binDir)) {
        New-Item -ItemType Directory -Path $binDir | Out-Null
    }

    if ($IncludeYtDlp) {
        Copy-IfFound -Source $script:ytDlpPath -DestinationDir $binDir | Out-Null
    }
    if ($IncludeDeno) {
        Copy-IfFound -Source $script:denoPath -DestinationDir $binDir | Out-Null
    }
    if ($IncludeFfmpeg) {
        Copy-IfFound -Source $script:ffmpegPath -DestinationDir $binDir | Out-Null
        Copy-IfFound -Source $script:ffprobePath -DestinationDir $binDir | Out-Null
    }

    Write-ReleaseReadme -Path (Join-Path $VariantDir "README.txt") -Title $ReadmeTitle -HeaderLines $ReadmeHeaderLines -Notes $ReadmeNotes
}

function Zip-Variant {
    param(
        [string]$SourceDir,
        [string]$ZipPath
    )

    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }

    Compress-Archive -Path (Join-Path $SourceDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
}

$pyInstallerInstalled = $true
try {
    py -m PyInstaller --version | Out-Null
} catch {
    $pyInstallerInstalled = $false
}

if (-not $pyInstallerInstalled) {
    throw "PyInstaller is not installed. Run: py -m pip install pyinstaller"
}

if (!(Test-Path -LiteralPath $IconPath)) {
    throw "Icon file not found: $IconPath"
}

if (!(Test-Path -LiteralPath $QrcPath)) {
    throw "Qt resource file not found: $QrcPath"
}

$rccPath = Find-RccPath
if (-not $rccPath) {
    throw "Qt resource compiler was not found. Install PySide6 and make sure pyside6-rcc.exe is available."
}

if (Test-Path -LiteralPath $ReleaseRoot) {
    Remove-Item -LiteralPath $ReleaseRoot -Recurse -Force
}

if (Test-Path -LiteralPath $TempBuildRoot) {
    Remove-Item -LiteralPath $TempBuildRoot -Recurse -Force
}

if (Test-Path -LiteralPath $TempDistRoot) {
    Remove-Item -LiteralPath $TempDistRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null
New-Item -ItemType Directory -Path $TempBuildRoot | Out-Null
New-Item -ItemType Directory -Path $TempDistRoot | Out-Null
New-Item -ItemType Directory -Path $TempSpecRoot | Out-Null

Write-Host "Generating Qt resource module..."
& $rccPath $QrcPath -o $RcPyPath

Write-Host "Building RU application..."
Build-App -Name "Cooklip_RU" -ScriptPath (Join-Path $ProjectRoot "cooklip_gui_ru.py")

Write-Host "Building EN application..."
Build-App -Name "Cooklip" -ScriptPath (Join-Path $ProjectRoot "cooklip_gui.py")

$BuiltRuDir = Join-Path $TempDistRoot "Cooklip_RU"
$BuiltEnDir = Join-Path $TempDistRoot "Cooklip"

if (-not (Test-Path -LiteralPath $BuiltRuDir)) {
    throw "PyInstaller finished without RU output folder $BuiltRuDir"
}

if (-not (Test-Path -LiteralPath $BuiltEnDir)) {
    throw "PyInstaller finished without EN output folder $BuiltEnDir"
}

$script:ytDlpPath = Find-CommandPath -Names @("yt-dlp", "yt-dlp.exe") -CandidatePaths @(
    (Join-Path $ProjectRoot "bin\yt-dlp.exe"),
    (Join-Path $ProjectRoot "yt-dlp.exe"),
    "$env:LocalAppData\Microsoft\WinGet\Links\yt-dlp.exe",
    "$env:UserProfile\AppData\Local\Microsoft\WinGet\Links\yt-dlp.exe"
)

$script:ffmpegPath = Find-CommandPath -Names @("ffmpeg", "ffmpeg.exe") -CandidatePaths @(
    (Join-Path $ProjectRoot "bin\ffmpeg.exe"),
    (Join-Path $ProjectRoot "ffmpeg.exe"),
    "$env:LocalAppData\Microsoft\WinGet\Links\ffmpeg.exe",
    "$env:UserProfile\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
)

$script:denoPath = Find-CommandPath -Names @("deno", "deno.exe") -CandidatePaths @(
    (Join-Path $ProjectRoot "bin\deno.exe"),
    (Join-Path $ProjectRoot "deno.exe"),
    "$env:USERPROFILE\.deno\bin\deno.exe",
    "$env:LocalAppData\Microsoft\WinGet\Links\deno.exe",
    "$env:UserProfile\AppData\Local\Microsoft\WinGet\Links\deno.exe"
)

$script:ffprobePath = Find-CommandPath -Names @("ffprobe", "ffprobe.exe") -CandidatePaths @(
    (Join-Path $ProjectRoot "bin\ffprobe.exe"),
    (Join-Path $ProjectRoot "ffprobe.exe"),
    "$env:LocalAppData\Microsoft\WinGet\Links\ffprobe.exe",
    "$env:UserProfile\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"
)

$RuLiteDir = Join-Path $ReleaseRoot "Cooklip-RU-lite"
$RuFullDir = Join-Path $ReleaseRoot "Cooklip-RU-full"
$EnLiteDir = Join-Path $ReleaseRoot "Cooklip-lite"
$EnFullDir = Join-Path $ReleaseRoot "Cooklip-full"

Create-ReleaseVariant -BuiltAppDir $BuiltRuDir -VariantDir $RuLiteDir -SettingsFileName "cooklip_settings.json" -IncludeYtDlp $true -IncludeDeno $true -IncludeFfmpeg $false -ReadmeTitle "Cooklip Downloader RU - Lite" -ReadmeHeaderLines @(
    "Быстрый старт:",
    "1. Запустите Cooklip RU Lite.exe",
    "2. При необходимости нажмите 'Запустить Edge для куков'",
    "3. Авторизуйтесь и нажмите 'Обновить куки из Edge'",
    "4. Вставьте ссылку и нажмите 'Скачать'"
) -ReadmeNotes @(
    "- В комплект входит yt-dlp.exe.",
    "- В комплект входит deno.exe для YouTube challenge solving.",
    "- ffmpeg не входит в lite. Для конвертации и склейки используйте full-версию."
) -SourceExeName "Cooklip_RU.exe" -ReleaseExeName "Cooklip RU Lite.exe"

Create-ReleaseVariant -BuiltAppDir $BuiltRuDir -VariantDir $RuFullDir -SettingsFileName "cooklip_settings.json" -IncludeYtDlp $true -IncludeDeno $true -IncludeFfmpeg $true -ReadmeTitle "Cooklip Downloader RU - Full" -ReadmeHeaderLines @(
    "Быстрый старт:",
    "1. Запустите Cooklip RU Full.exe",
    "2. При необходимости нажмите 'Запустить Edge для куков'",
    "3. Авторизуйтесь и нажмите 'Обновить куки из Edge'",
    "4. Вставьте ссылку и нажмите 'Скачать'"
) -ReadmeNotes @(
    "- В комплект входят yt-dlp.exe и deno.exe.",
    "- В комплект входят ffmpeg.exe и ffprobe.exe."
) -SourceExeName "Cooklip_RU.exe" -ReleaseExeName "Cooklip RU Full.exe"

Create-ReleaseVariant -BuiltAppDir $BuiltEnDir -VariantDir $EnLiteDir -SettingsFileName "cooklip_settings_en.json" -IncludeYtDlp $true -IncludeDeno $true -IncludeFfmpeg $false -ReadmeTitle "Cooklip Downloader - Lite" -ReadmeHeaderLines @(
    "Quick start:",
    "1. Run Cooklip Lite.exe",
    "2. If needed, click 'Launch Edge for cookies'",
    "3. Sign in and click 'Refresh cookies from Edge'",
    "4. Paste a link and download"
) -ReadmeNotes @(
    "- yt-dlp.exe is included.",
    "- deno.exe is included for YouTube challenge solving.",
    "- ffmpeg is not included in lite. Use the full release if conversion or merging is needed."
) -SourceExeName "Cooklip.exe" -ReleaseExeName "Cooklip Lite.exe"

Create-ReleaseVariant -BuiltAppDir $BuiltEnDir -VariantDir $EnFullDir -SettingsFileName "cooklip_settings_en.json" -IncludeYtDlp $true -IncludeDeno $true -IncludeFfmpeg $true -ReadmeTitle "Cooklip Downloader - Full" -ReadmeHeaderLines @(
    "Quick start:",
    "1. Run Cooklip Full.exe",
    "2. If needed, click 'Launch Edge for cookies'",
    "3. Sign in and click 'Refresh cookies from Edge'",
    "4. Paste a link and download"
) -ReadmeNotes @(
    "- yt-dlp.exe is included.",
    "- deno.exe is included for YouTube challenge solving.",
    "- ffmpeg.exe and ffprobe.exe are included."
) -SourceExeName "Cooklip.exe" -ReleaseExeName "Cooklip Full.exe"

if (-not $NoZip) {
    Zip-Variant -SourceDir $EnLiteDir -ZipPath (Join-Path $ReleaseRoot "Cooklip-lite-win64.zip")
    Zip-Variant -SourceDir $EnFullDir -ZipPath (Join-Path $ReleaseRoot "Cooklip-full-win64.zip")
    Zip-Variant -SourceDir $RuLiteDir -ZipPath (Join-Path $ReleaseRoot "Cooklip-RU-lite-win64.zip")
    Zip-Variant -SourceDir $RuFullDir -ZipPath (Join-Path $ReleaseRoot "Cooklip-RU-full-win64.zip")
}

Write-Host ""
Write-Host "Done."
Write-Host "EN Lite: $EnLiteDir"
Write-Host "EN Full: $EnFullDir"
Write-Host "RU Lite: $RuLiteDir"
Write-Host "RU Full: $RuFullDir"
if (-not $NoZip) {
    Write-Host "ZIP archives: $ReleaseRoot"
}

if (Test-Path -LiteralPath $TempBuildRoot) {
    Remove-Item -LiteralPath $TempBuildRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $TempDistRoot) {
    Remove-Item -LiteralPath $TempDistRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path -LiteralPath $TempSpecRoot) {
    Remove-Item -LiteralPath $TempSpecRoot -Recurse -Force -ErrorAction SilentlyContinue
}
