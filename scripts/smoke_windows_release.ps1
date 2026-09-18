param(
    [string]$WorkRoot = $env:RUNNER_TEMP
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:PYTHONUTF8 = "1"
$utf8 = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8

# This archives a fixed published-release check; it does not test current source
# installation or claim broad Windows support.
$ReleaseVersion = "0.15.0a2"
$WheelName = "intentir-$ReleaseVersion-py3-none-any.whl"
$ExpectedSha256 = "8c82ebddaced33d9eba4dd7bcb9014057ebeced21ec51d21e09329d7bbeebdf8"
$WheelUrl = "https://github.com/oyasumiholiday/ailex/releases/download/intentir-v$ReleaseVersion/$WheelName"

function Assert-NativeSuccess {
    param([string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE"
    }
}

function Invoke-NativeJson {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Operation
    )
    $lines = @(& $FilePath @Arguments)
    Assert-NativeSuccess $Operation
    try {
        return ($lines -join "`n") | ConvertFrom-Json
    }
    catch {
        throw "$Operation did not return valid JSON"
    }
}

if ($PSVersionTable.PSVersion -lt [version]"7.3") {
    throw "PowerShell 7.3 or newer is required"
}
if (-not $IsWindows) {
    throw "This smoke script runs only on Windows"
}
$PSNativeCommandArgumentPassing = "Standard"
if ([string]::IsNullOrWhiteSpace($WorkRoot)) {
    $WorkRoot = [System.IO.Path]::GetTempPath()
}
if (-not (Test-Path -LiteralPath $WorkRoot -PathType Container)) {
    throw "WorkRoot must be an existing directory"
}

$RunRoot = Join-Path $WorkRoot "intentir release smoke $([guid]::NewGuid())"
$null = New-Item -ItemType Directory -Path $RunRoot
$WheelPath = Join-Path $RunRoot $WheelName
Invoke-WebRequest -Uri $WheelUrl -OutFile $WheelPath

$ActualSha256 = (Get-FileHash -LiteralPath $WheelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "wheel SHA-256 mismatch"
}

# Hash verification intentionally precedes all virtual-environment writes.
$Venv = Join-Path $RunRoot "fresh venv"
& python --version | Out-Null
Assert-NativeSuccess "setup Python version check"
& python -m venv $Venv | Out-Null
Assert-NativeSuccess "virtual environment creation"

$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Intentir = Join-Path $Venv "Scripts\intentir.exe"
& $VenvPython -m pip install --no-index --no-deps $WheelPath | Out-Null
Assert-NativeSuccess "offline wheel installation"
$InstalledVersion = @(& $VenvPython -I -X utf8 -c "import importlib.metadata; print(importlib.metadata.version('intentir'))") -join ""
Assert-NativeSuccess "installed package version check"
if ($InstalledVersion -ne $ReleaseVersion) {
    throw "installed package version did not match the published release"
}

$SmokeScript = Join-Path $PSScriptRoot "smoke_todo_starter.py"
Push-Location $RunRoot
try {
    & $VenvPython -I -X utf8 $SmokeScript | Out-Null
    Assert-NativeSuccess "cross-process Todo starter smoke"

    $Concurrent = Invoke-NativeJson $Intentir @("demo", "concurrent-agent", "--json") "concurrent-agent demo"
    if ($Concurrent.ok -ne $true) {
        throw "concurrent-agent demo returned ok=false"
    }

    $Notation = Invoke-NativeJson $Intentir @("demo", "notation-lab", "--json") "notation-lab demo"
    $NotationResults = @($Notation.representations.PSObject.Properties.Value | ForEach-Object { $_.result })
    if ($Notation.ok -ne $true -or $Notation.equivalent -ne $true -or
        $NotationResults.Count -ne 3 -or
        ($NotationResults | Where-Object { $_ -ne 380 }).Count -ne 0 -or
        $Notation.patch.result -ne 390) {
        throw "notation-lab demo results did not match 380/390"
    }

    $PowerShellTodo = Join-Path $RunRoot "PowerShell Todo 日本語"
    $Initialized = Invoke-NativeJson $Intentir @("init", "todo", $PowerShellTodo, "--json") "PowerShell Todo init"
    if ($Initialized.ok -ne $true) {
        throw "PowerShell Todo init returned ok=false"
    }

    $TodoSource = Join-Path $PowerShellTodo "todo.intent"
    $TodoDatabase = Join-Path $PowerShellTodo "todo.db"
    $Title = "日本語 title with spaces"
    $Created = Invoke-NativeJson $Intentir @(
        "run", $TodoSource, "CreateTask", "--input",
        '{"id":"ps-task-1","title":"日本語 title with spaces"}',
        "--db", $TodoDatabase
    ) "PowerShell CreateTask"
    if ($Created.ok -ne $true -or $Created.state.Task[0].title -ne $Title) {
        throw "PowerShell CreateTask did not preserve the title"
    }

    $Completed = Invoke-NativeJson $Intentir @(
        "run", $TodoSource, "CompleteTask", "--input",
        '{"id":"ps-task-1"}', "--db", $TodoDatabase
    ) "PowerShell CompleteTask"
    if ($Completed.ok -ne $true -or $Completed.state.Task[0].title -ne $Title -or
        $Completed.state.Task[0].done -ne $true) {
        throw "PowerShell CompleteTask did not preserve title and done state"
    }

    $PythonVersion = @(& $VenvPython -c "import platform; print(platform.python_version())") -join ""
    Assert-NativeSuccess "installed Python version check"
    [ordered]@{
        ok = $true
        release = $ReleaseVersion
        python = $PythonVersion
        powershell = $PSVersionTable.PSVersion.ToString()
        result = "published-wheel-windows-smoke"
    } | ConvertTo-Json -Compress
}
finally {
    Pop-Location
}
