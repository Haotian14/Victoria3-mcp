<#
.SYNOPSIS
    构建 V3Bridge.dll (x64)。

.NOTES
    必须是 x64 —— 游戏是 64 位进程，LoadLibrary 加载 32 位 DLL 会失败。
    游戏运行时 bin\V3Bridge.dll 不会被占用：launch.ps1 注入的是一份临时副本。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$Here   = $PSScriptRoot
$OutDir = Join-Path (Split-Path (Split-Path $Here -Parent) -Parent) 'bin'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# --- 定位 MSVC ------------------------------------------------------------
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = $null
if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
}
# 安装器的实例登记损坏时 vswhere 什么也列不出（本机就是这样），按默认安装位置兜底
if (-not $vsPath) {
    $vsPath = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools"
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools"
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community"
    ) | Where-Object { Test-Path (Join-Path $_ 'VC\Auxiliary\Build\vcvars64.bat') } | Select-Object -First 1
}
if (-not $vsPath) { throw "未找到含 C++ 工具集的 VS 安装" }

$vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) { throw "找不到 vcvars64.bat: $vcvars" }

Write-Host "[信息] VS: $vsPath"

# --- 把 vcvars 的环境变量导入当前 PowerShell 会话 --------------------------
# vcvars64.bat 只影响它自己的 cmd 进程，必须把结果 set 回来才能在此调用 cl。
& cmd /c "call `"$vcvars`" >nul 2>&1 && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        Set-Item -Path "Env:\$($matches[1])" -Value $matches[2] -ErrorAction SilentlyContinue
    }
}

$cl = Get-Command cl.exe -ErrorAction SilentlyContinue
if (-not $cl) { throw "vcvars 导入后仍找不到 cl.exe" }
Write-Host "[信息] cl: $($cl.Source)"

# --- 编译 -----------------------------------------------------------------
Push-Location $OutDir
try {
    $clArgs = @(
        '/nologo'
        '/LD'                       # 生成 DLL
        '/EHsc'
        '/O2'
        '/MT'                       # 静态链接 CRT：不依赖目标机上的 VC 运行库
        '/std:c++17'
        '/W3'
        '/utf-8'                    # 源文件是 UTF-8；不加则按系统代码页(936)解析，
                                    # 中文注释会引发 C4819 / C2001
        '/D_CRT_SECURE_NO_WARNINGS'
        '/DWIN32_LEAN_AND_MEAN'
        '/DNOMINMAX'
        "`"$Here\V3Bridge.cpp`""
        "`"$Here\scan.cpp`""
        "`"$Here\trace.cpp`""
        "`"$Here\datasys.cpp`""
        # 在输出目录里编译，.obj 自然落在那里；不用 /Fo:"目录\" —— 结尾反斜杠紧邻引号
        # 会被 Windows 命令行解析为转义引号(\")，导致后续所有参数被吞进字符串。
        '/Fe:V3Bridge.dll'
        '/link'
        '/MACHINE:X64'
        'user32.lib'
        'ws2_32.lib'
    )

    & $cl.Source @clArgs
    if ($LASTEXITCODE -ne 0) { throw "编译失败 (exit $LASTEXITCODE)" }
}
finally { Pop-Location }

$dll = Join-Path $OutDir 'V3Bridge.dll'
if (-not (Test-Path $dll)) { throw "编译似乎成功但产物不存在: $dll" }

# --- 校验位数 -------------------------------------------------------------
# 位数错误时注入只会得到一个失败的 LoadLibrary，这里先确认。
$fs = [System.IO.File]::OpenRead($dll)
try {
    $br = New-Object System.IO.BinaryReader($fs)
    $fs.Position = 0x3C
    $peOff = $br.ReadInt32()
    $fs.Position = $peOff + 4
    $machine = $br.ReadUInt16()
} finally { $fs.Dispose() }

$arch = switch ($machine) { 0x8664 { 'x64' } 0x14c { 'x86' } default { "未知(0x{0:X})" -f $machine } }

Write-Host ""
Write-Host "[成功] $dll"
Write-Host "[架构] $arch $(if ($arch -ne 'x64') { '  <-- 错误！必须是 x64' })"
