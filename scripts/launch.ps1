<#
.SYNOPSIS
    不经启动器直接开《维多利亚 3》，注入 V3Bridge，等桥接层就绪。

.DESCRIPTION
    - 以 -debug_mode 启动（文本存档 + 控制台可用），工作目录 binaries\。
    - SteamAppId / SteamGameId 环境变量让游戏跳过启动器直接初始化 Steam API。
    - 注入的是 bin\V3Bridge.dll 的临时副本：游戏运行时也能重新编译。
    - 不改游戏目录里的任何文件。

.EXAMPLE
    .\scripts\launch.ps1                       # 继续最近的存档
    .\scripts\launch.ps1 -Restart              # 先关掉正在运行的游戏
    .\scripts\launch.ps1 -Save autosave_exit   # 载入指定存档（不带 .v3）
    .\scripts\launch.ps1 -Attach               # 不启动，只给已运行的游戏注入
#>
[CmdletBinding()]
param(
    [string]$Save = '',
    [switch]$Restart,
    [switch]$Attach,
    [switch]$NoNotifications,
    [string[]]$ExtraArgs = @(),
    [int]$Port = 8766,
    [int]$TimeoutSec = 240
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path $PSScriptRoot -Parent

# --- 游戏目录 -------------------------------------------------------------
$GameDir = $env:V3MCP_GAME_DIR
if (-not $GameDir) {
    $libs = @("${env:ProgramFiles(x86)}\Steam")
    $vdf = "${env:ProgramFiles(x86)}\Steam\steamapps\libraryfolders.vdf"
    if (Test-Path $vdf) {
        $libs += Select-String -Path $vdf -Pattern '"path"\s+"([^"]+)"' -AllMatches |
            ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value -replace '\\\\', '\' }
    }
    $GameDir = $libs | ForEach-Object { Join-Path $_ 'steamapps\common\Victoria 3' } |
        Where-Object { Test-Path (Join-Path $_ 'binaries\victoria3.exe') } | Select-Object -First 1
}
if (-not $GameDir) { throw "找不到 Victoria 3 安装目录，请设置 V3MCP_GAME_DIR" }
$Bin = Join-Path $GameDir 'binaries'
$Exe = Join-Path $Bin 'victoria3.exe'

$Dll = Join-Path $Repo 'bin\V3Bridge.dll'
if (-not (Test-Path $Dll)) { throw "没有 $Dll —— 先运行 src\V3Bridge\build.ps1" }

# --- 注入用的 Win32 调用 ----------------------------------------------------
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class V3Inject {
    [DllImport("kernel32", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32", SetLastError = true)] static extern IntPtr VirtualAllocEx(IntPtr h, IntPtr addr, UIntPtr size, uint type, uint protect);
    [DllImport("kernel32", SetLastError = true)] static extern bool WriteProcessMemory(IntPtr h, IntPtr addr, byte[] buf, UIntPtr size, out UIntPtr written);
    [DllImport("kernel32", SetLastError = true)] static extern IntPtr CreateRemoteThread(IntPtr h, IntPtr attr, UIntPtr stack, IntPtr start, IntPtr param, uint flags, out uint tid);
    [DllImport("kernel32", SetLastError = true)] static extern uint WaitForSingleObject(IntPtr h, uint ms);
    [DllImport("kernel32", SetLastError = true)] static extern bool GetExitCodeThread(IntPtr h, out uint code);
    [DllImport("kernel32", SetLastError = true)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32", CharSet = CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr mod, string name);
    [DllImport("kernel32", CharSet = CharSet.Unicode)] static extern IntPtr GetModuleHandleW(string name);

    // kernel32 在所有进程里映射到同一地址，本进程里取到的 LoadLibraryW 地址可直接用
    public static string Inject(int pid, string dll) {
        IntPtr h = OpenProcess(0x043A, false, pid);   // CREATE_THREAD | VM_OPERATION | VM_WRITE | VM_READ | QUERY_INFORMATION
        if (h == IntPtr.Zero) return "OpenProcess 失败 " + Marshal.GetLastWin32Error();
        try {
            byte[] path = Encoding.Unicode.GetBytes(dll + "\0");
            IntPtr mem = VirtualAllocEx(h, IntPtr.Zero, (UIntPtr)path.Length, 0x3000, 0x04);
            if (mem == IntPtr.Zero) return "VirtualAllocEx 失败 " + Marshal.GetLastWin32Error();
            UIntPtr n;
            if (!WriteProcessMemory(h, mem, path, (UIntPtr)path.Length, out n)) return "WriteProcessMemory 失败 " + Marshal.GetLastWin32Error();
            IntPtr load = GetProcAddress(GetModuleHandleW("kernel32.dll"), "LoadLibraryW");
            uint tid;
            IntPtr t = CreateRemoteThread(h, IntPtr.Zero, UIntPtr.Zero, load, mem, 0, out tid);
            if (t == IntPtr.Zero) return "CreateRemoteThread 失败 " + Marshal.GetLastWin32Error();
            WaitForSingleObject(t, 30000);
            uint code;
            GetExitCodeThread(t, out code);   // HMODULE 的低 32 位；0 表示 LoadLibrary 失败
            CloseHandle(t);
            return code == 0 ? "LoadLibraryW 返回 NULL（DLL 路径或依赖有误）" : "";
        } finally { CloseHandle(h); }
    }
}
'@

function Get-Health {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
    } catch { $null }
}

# --- 启动 -----------------------------------------------------------------
$running = Get-Process victoria3 -ErrorAction SilentlyContinue
if ($running -and $Restart) {
    Write-Host "[信息] 结束正在运行的游戏 (pid $($running.Id -join ','))"
    $running | Stop-Process -Force
    $running | Wait-Process -Timeout 30 -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $running = $null
}

if ($Attach) {
    if (-not $running) { throw "-Attach：游戏没有在运行" }
    $proc = $running | Select-Object -First 1
} else {
    if ($running) { throw "游戏已在运行 (pid $($running.Id))。用 -Restart 重开，或 -Attach 只注入" }
    $env:SteamAppId = '529340'
    $env:SteamGameId = '529340'
    $env:V3MCP_PORT = "$Port"
    New-Item -ItemType Directory -Force -Path (Join-Path $Repo 'logs') | Out-Null
    $env:V3MCP_BRIDGE_LOG = Join-Path $Repo 'logs\bridge.log'
    $gameArgs = @('-debug_mode')
    if ($Save) { $gameArgs += "-loadsave=$Save" } else { $gameArgs += '-continuelastsave' }
    if ($NoNotifications) { $gameArgs += '-no_notifications' }   # 不弹窗、不因事件自动暂停
    $gameArgs += $ExtraArgs
    Write-Host "[信息] 启动 $Exe $($gameArgs -join ' ')"
    $proc = Start-Process -FilePath $Exe -ArgumentList $gameArgs -WorkingDirectory $Bin -PassThru
    # 等主模块映射、加载器初始化完再注入
    Start-Sleep -Seconds 3
}

if (Get-Health) {
    Write-Host "[信息] 桥接层已在 127.0.0.1:$Port 上，不重复注入"
} else {
    $tmpDir = Join-Path $env:TEMP 'V3Bridge'
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    Get-ChildItem $tmpDir -Filter 'V3Bridge-*.dll' -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item $_.FullName -ErrorAction SilentlyContinue }   # 仍被占用的会删不掉，正常
    $copy = Join-Path $tmpDir ("V3Bridge-{0}.dll" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Copy-Item $Dll $copy
    $err = [V3Inject]::Inject($proc.Id, $copy)
    if ($err) { throw "注入失败：$err" }
    Write-Host "[信息] 已注入 $copy"
}

# --- 等桥接层就绪（主窗口出现、控制台函数已定位）---------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) { throw "游戏进程已退出 (exit $($proc.ExitCode))" }
    $h = Get-Health
    if ($h -and $h.ok) {
        Write-Host "[成功] 桥接层就绪：pid $($h.pid)，主线程 $($h.main_thread)，Execute $($h.execute)"
        exit 0
    }
    if ($h -and $h.error) { throw "桥接层报错：$($h.error)" }
    Start-Sleep -Seconds 2
}
throw "$TimeoutSec 秒内桥接层没有就绪（看 logs\bridge.log）"
