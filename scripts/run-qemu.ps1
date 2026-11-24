<#
  Try GlassOS (amd64) in QEMU on Windows. The Windows counterpart of scripts/run-qemu.sh.

    .\scripts\run-qemu.ps1                     boot the ISO (live session) with a 24 GB disk attached to install onto
    .\scripts\run-qemu.ps1 -NoCd               boot the installed disk, as if the USB stick was removed
    .\scripts\run-qemu.ps1 -Fresh              wipe the virtual disk (and UEFI settings) first
    .\scripts\run-qemu.ps1 -Res 1920x1080      screen size
    .\scripts\run-qemu.ps1 -Share C:\Music\X   plug a folder in as a read-only USB drive (keep it under 500 MB)
    .\scripts\run-qemu.ps1 -UsbHost 046d:c52b  pass a real USB device through (vendor:product, repeatable with commas;
                                               the device needs the WinUSB driver, e.g. via Zadig)
    .\scripts\run-qemu.ps1 -Bios               old-style BIOS boot instead of UEFI
    .\scripts\run-qemu.ps1 -NoAccel            skip Windows Hypervisor Platform (pure emulation, slow)

  Sound goes to your default Windows output device (and the default mic is passed in).
  Ctrl+Alt+G releases the mouse/keyboard from the window. The live session password is "glass".
#>
param(
  [switch]$NoCd,
  [switch]$Fresh,
  [switch]$Bios,
  [switch]$NoAccel,
  [string]$Res = "",
  [string]$Share = "",
  [string[]]$UsbHost = @(),
  [string]$Iso = "",
  [ValidateSet('sdl', 'gtk')][string]$Display = 'sdl',
  [int]$MemoryMB = 6144,
  [int]$Cpus = 4
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Find QEMU
$qemuDir = $null
$cmd = Get-Command qemu-system-x86_64.exe -ErrorAction SilentlyContinue
if ($cmd) { $qemuDir = Split-Path -Parent $cmd.Source }
elseif (Test-Path "$env:ProgramFiles\qemu\qemu-system-x86_64.exe") { $qemuDir = "$env:ProgramFiles\qemu" }
else { throw "QEMU not found. Install it with:  winget install SoftwareFreedomConservancy.QEMU" }
$qemu = Join-Path $qemuDir 'qemu-system-x86_64.exe'
$qemuImg = Join-Path $qemuDir 'qemu-img.exe'
$fw = Join-Path $qemuDir 'share'

if (-not $Iso) {
  $found = Get-ChildItem out -Filter 'GlassOS-*-amd64.iso' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
  if ($found) { $Iso = $found.FullName }
}
if (-not $NoCd -and -not (Test-Path $Iso)) { throw "No GlassOS amd64 ISO in out\ (download it from the GitHub release, or build it)" }

$vmd = Join-Path $root 'out\vm'
New-Item -ItemType Directory -Force $vmd | Out-Null
$disk = Join-Path $vmd 'disk-amd64.qcow2'
$vars = Join-Path $vmd 'vars-amd64.fd'
if ($Fresh) { Remove-Item -Force -ErrorAction SilentlyContinue $disk, $vars }
if (-not (Test-Path $disk)) { & $qemuImg create -q -f qcow2 $disk 24G; if ($LASTEXITCODE) { throw "qemu-img failed" } }

$gpu = 'virtio-vga'
if ($Res) { $w, $h = $Res -split 'x'; $gpu += ",xres=$w,yres=$h" }

$a = @('-name', 'GlassOS amd64', '-machine', 'q35', '-m', "$MemoryMB", '-smp', "$Cpus")
# Hardware acceleration via Windows Hypervisor Platform, falling back to emulation if it's not enabled
if ($NoAccel) { $a += @('-accel', 'tcg,thread=multi', '-cpu', 'max') }
else { $a += @('-accel', 'whpx,kernel-irqchip=off', '-accel', 'tcg,thread=multi', '-cpu', 'qemu64,+ssse3,+sse4.1,+sse4.2,+popcnt,-svm') }

if (-not $Bios) {
  if (-not (Test-Path $vars)) { Copy-Item (Join-Path $fw 'edk2-i386-vars.fd') $vars }
  $a += @('-drive', "if=pflash,format=raw,readonly=on,file=$(Join-Path $fw 'edk2-x86_64-code.fd')",
          '-drive', "if=pflash,format=raw,file=$vars")
}

$a += @('-device', $gpu,
        # USB 3 controller with keyboard + tablet (absolute pointer, no mouse grab needed)
        '-device', 'qemu-xhci,id=xhci', '-device', 'usb-kbd', '-device', 'usb-tablet',
        # Network
        '-nic', 'user,model=virtio-net-pci',
        # Sound: Intel HD Audio, output + mic, through Windows' default devices
        '-audiodev', 'dsound,id=snd', '-device', 'intel-hda', '-device', 'hda-duplex,audiodev=snd',
        # Installed disk
        '-drive', "if=none,id=hd,file=$disk", '-device', 'virtio-blk-pci,drive=hd,bootindex=2')

if (-not $NoCd) {
  $a += @('-device', 'virtio-scsi-pci,id=scsi',
          '-drive', "if=none,id=cd,media=cdrom,readonly=on,file=$Iso",
          '-device', 'scsi-cd,drive=cd,bootindex=1')
}
if ($Share) {
  if (-not (Test-Path $Share -PathType Container)) { throw "-Share: $Share is not a folder" }
  $sharePath = (Resolve-Path $Share).Path
  $a += @('-drive', "if=none,id=share,format=raw,readonly=on,file=fat:$sharePath", '-device', 'usb-storage,bus=xhci.0,drive=share,removable=on')
}
foreach ($dev in ($UsbHost -join ',' -split ',' | Where-Object { $_ })) {
  $vid, $pid_ = $dev -split ':'
  $a += @('-device', "usb-host,bus=xhci.0,vendorid=0x$vid,productid=0x$pid_")
}
$a += @('-display', "$Display,show-cursor=on",
        # Local-only control port (screenshots, power button): e.g. {"execute":"screendump","arguments":{"filename":"x.png","format":"png"}}
        '-qmp', 'tcp:127.0.0.1:4445,server=on,wait=off')

Write-Host "Starting QEMU with $(if ($NoCd) { 'the installed disk' } else { $Iso })"
& $qemu @a
