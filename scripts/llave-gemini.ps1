# Pone la llave de Gemini en el .env, sin que quede en el historial.
#
# El problema de hacerlo con `echo GEMINI_API_KEY=AIza... >> .env` es que la
# llave queda escrita en el historial de PowerShell, en texto plano, para
# siempre. Quien lea ese historial gasta con la tarjeta de la empresa.
#
# Esto la pide sin mostrarla en pantalla y la escribe directo en el .env.
#
# Uso, desde la carpeta del proyecto:
#     powershell -ExecutionPolicy Bypass -File scripts\llave-gemini.ps1
#
# La llave se saca en https://aistudio.google.com/apikey
# OJO: la suscripcion de Google One / Gemini Pro NO incluye uso de la API.

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
$env_archivo = Join-Path $raiz ".env"

if (-not (Test-Path $env_archivo)) {
    Write-Host "No encuentro el .env en $raiz" -ForegroundColor Red
    Write-Host "Corra este script desde la carpeta del proyecto."
    exit 1
}

Write-Host ""
Write-Host "Llave de Gemini para el Portal de Tickets" -ForegroundColor Cyan
Write-Host "-----------------------------------------"
Write-Host "Se saca en: https://aistudio.google.com/apikey"
Write-Host "No se va a mostrar en pantalla ni a quedar en el historial."
Write-Host ""

$segura = Read-Host "Pegue la llave y presione Enter" -AsSecureString
$llave = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($segura))

if ([string]::IsNullOrWhiteSpace($llave)) {
    Write-Host "No se escribio nada. No se toco el .env." -ForegroundColor Yellow
    exit 0
}

$llave = $llave.Trim()

# Una comprobacion minima: las llaves de Google empiezan con AIza y son largas.
# No valida que sirva —eso lo dice la pantalla de Estado— pero atrapa el pegado
# a medias, que es el error de dedo mas comun.
if ($llave.Length -lt 30) {
    Write-Host "Esa llave se ve demasiado corta ($($llave.Length) caracteres)." -ForegroundColor Yellow
    Write-Host "Revise que se haya copiado completa. No se toco el .env."
    exit 1
}
if (-not $llave.StartsWith("AIza")) {
    Write-Host "Aviso: las llaves de Google normalmente empiezan con 'AIza'." -ForegroundColor Yellow
    $seguir = Read-Host "Continuar de todas formas? (s/N)"
    if ($seguir -ne "s") { exit 0 }
}

# Respaldo antes de tocar nada. Se borra al final si todo salio bien: un .env
# viejo tirado por ahi tiene la contrasena de la base de datos.
$respaldo = "$env_archivo.antes-de-gemini"
Copy-Item $env_archivo $respaldo -Force

$lineas = Get-Content $env_archivo
$puesta = $false
$salida = foreach ($linea in $lineas) {
    if ($linea -match '^\s*GEMINI_API_KEY\s*=') {
        "GEMINI_API_KEY=$llave"
        $puesta = $true
    } else {
        $linea
    }
}
if (-not $puesta) { $salida += "GEMINI_API_KEY=$llave" }

Set-Content -Path $env_archivo -Value $salida -Encoding utf8

Remove-Item $respaldo -Force
Remove-Variable llave

Write-Host ""
Write-Host "Llave guardada en el .env." -ForegroundColor Green
Write-Host ""
Write-Host "Falta reiniciar el backend para que la lea:"
Write-Host "    wsl -d Ubuntu-20.04 -- bash -lc `"cd '/mnt/c/Users/Practicante2/Documents/GitHub/Portal de tickets' && docker compose up -d backend`"" -ForegroundColor Cyan
Write-Host ""
Write-Host "Y para comprobar que quedo bien, sin ensenarsela a nadie:"
Write-Host "    entre al portal, menu Estado. Gemini debe decir 'Arriba'."
Write-Host ""
