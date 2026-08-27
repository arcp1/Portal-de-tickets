<#
.SYNOPSIS
    Mantiene el Portal de Tickets arriba en una máquina Windows con WSL2.

.DESCRIPTION
    Resuelve un problema propio de WSL, no del portal: WSL2 apaga su máquina
    virtual cuando ningún proceso de Windows la está usando, y se lleva Docker
    y los contenedores con ella. El portal queda caído hasta que alguien
    ejecuta un comando de Docker sin saber que lo está reviviendo.

    Este script hace dos cosas:
      1. Levanta el stack.
      2. Deja un proceso de WSL vivo, que es lo que impide que la VM se duerma.

    Si el proceso muere, lo vuelve a levantar.

    En el servidor Linux nada de esto hace falta: ahí systemd se encarga
    (ver DESPLIEGUE.md, sección 2.7).

.PARAMETER Distro
    Nombre de la distro de WSL. Por defecto Ubuntu-20.04.

.PARAMETER Proyecto
    Ruta del proyecto dentro de WSL.

.EXAMPLE
    .\portal-arriba.ps1
    .\portal-arriba.ps1 -Instalar     # lo registra para que arranque solo
#>

[CmdletBinding()]
param(
    [string]$Distro = 'Ubuntu-20.04',
    [string]$Proyecto = '/mnt/c/Users/Practicante2/Documents/GitHub/Portal de tickets',
    [switch]$Instalar,
    [switch]$Desinstalar
)

$ErrorActionPreference = 'Stop'
$NombreTarea = 'PortalTickets-Arriba'

function Escribir($mensaje, $color = 'Gray') {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $mensaje) -ForegroundColor $color
}

# ---------------------------------------------------------------------
# Registrar / quitar la tarea programada
# ---------------------------------------------------------------------
if ($Instalar) {
    $ruta = $MyInvocation.MyCommand.Path
    $accion = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Distro "{1}" -Proyecto "{2}"' -f $ruta, $Distro, $Proyecto)
    $disparador = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    # RestartCount/Interval: si el proceso muere, Windows lo reintenta.
    $ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 0)

    Register-ScheduledTask -TaskName $NombreTarea -Action $accion -Trigger $disparador `
        -Settings $ajustes -Description 'Mantiene arriba el Portal de Tickets TI (CGR)' -Force | Out-Null

    Escribir "Tarea '$NombreTarea' registrada. Arranca sola al iniciar sesion." 'Green'
    Escribir "Para arrancarla ahora: Start-ScheduledTask -TaskName $NombreTarea" 'Gray'
    return
}

if ($Desinstalar) {
    Unregister-ScheduledTask -TaskName $NombreTarea -Confirm:$false -ErrorAction SilentlyContinue
    Escribir "Tarea '$NombreTarea' eliminada." 'Yellow'
    return
}

# ---------------------------------------------------------------------
# Levantar y sostener
# ---------------------------------------------------------------------
Escribir "Levantando el stack en $Distro..." 'Cyan'

$subir = 'cd "' + $Proyecto + '" && (sudo -n docker compose up -d 2>&1 | tail -3)'
& wsl.exe -d $Distro -e bash -lc $subir

while ($true) {
    try {
        # `sleep infinity` mantiene vivo un proceso de WSL, que es lo unico que
        # impide que la VM se duerma. Si WSL se reinicia por cualquier motivo,
        # el bucle vuelve a levantar el stack.
        Escribir "Sosteniendo la VM de WSL. Cierra esta ventana para detener." 'Green'
        & wsl.exe -d $Distro -e sleep infinity
    } catch {
        Escribir "El proceso de WSL termino: $($_.Exception.Message)" 'Yellow'
    }

    Escribir "WSL se cayo. Reintentando en 10 segundos..." 'Yellow'
    Start-Sleep -Seconds 10
    & wsl.exe -d $Distro -e bash -lc $subir
}
