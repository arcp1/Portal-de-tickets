# Despliegue y migración a servidor

## 1. Para qué se usa WSL

El sistema corre en Docker, y Docker necesita un kernel de Linux. Windows no lo
tiene, así que WSL2 provee uno: es una máquina virtual ligera de Linux dentro de
Windows donde vive el motor de Docker.

Concretamente, WSL aquí hace tres cosas:

| Función | Por qué |
|---|---|
| Kernel de Linux para Docker | Los contenedores son procesos de Linux aislados. Sin kernel Linux no hay contenedores. |
| Evitar Docker Desktop | Su licencia es gratuita solo para empresas de menos de 250 empleados. CGR rebasa ese umbral, así que usarlo sería un hallazgo de auditoría. Docker Engine dentro de WSL2 es open source y sin restricción. |
| Paridad con producción | El servidor de la planta es Linux. Desarrollar sobre Linux real evita las sorpresas de "en mi máquina sí funcionaba". |

**WSL es andamio de desarrollo, no parte del producto.** En el servidor
desaparece: ahí hay Linux directamente y el mismo `docker compose` corre igual.

### Lo que WSL cuesta hoy

Durante las pruebas encontré dos problemas que **son de WSL, no del código**, y
que desaparecen al migrar:

1. **El portal se cae solo cada minuto.** WSL2 apaga su máquina virtual unos
   60 segundos después de que ningún proceso de Windows la esté usando, y se
   lleva Docker y los cinco contenedores. El portal queda caído hasta que
   alguien ejecuta un comando de Docker sin saber que lo está reviviendo.

   Se resuelve de dos formas, y conviene aplicar las dos.

   **a) Tarea programada** que levanta el stack al iniciar sesión y mantiene
   viva la máquina virtual:

```powershell
.\scripts\portal-arriba.ps1 -Instalar
```

```powershell
Start-ScheduledTask -TaskName PortalTickets-Arriba
```

   **b) Que la VM no se duerma nunca.** Ya está configurado en `~/.wslconfig`
   con `vmIdleTimeout=-1`, pero ese archivo solo se lee cuando WSL arranca de
   cero:

```powershell
wsl --shutdown
```

   Verificado: con la tarea activa, `dockerd` deja de reiniciarse cada 60
   segundos y el portal responde de forma continua.

2. **El proyecto vive en `/mnt/c/`.** La spec §10 lo marca como el error más
   común: los contenedores corren entre cinco y diez veces más lento sobre el
   sistema de archivos de Windows montado. Debería estar en `~/proyectos/` dentro
   de WSL.

---

## 2. Migración al servidor Linux

### 2.1 Qué cambia

Casi nada. El mismo `docker-compose.yml` funciona. Lo que cambia:

| En Windows + WSL | En el servidor Linux |
|---|---|
| WSL provee el kernel | El servidor ya es Linux |
| Ollama nativo en Windows, alcanzado con `host.docker.internal` | Ollama como contenedor del compose (`http://ollama:11434`) |
| Proyecto en `/mnt/c/...` (lento) | Proyecto en `/opt/portal-tickets` (velocidad nativa) |
| Se levanta a mano | `systemd` lo levanta al arrancar la máquina |
| HTTP en el puerto 80 | HTTPS con certificado |

### 2.2 Conexión con MobaXterm

MobaXterm es un cliente SSH: te da terminal y transferencia de archivos contra el
servidor. No cambia nada del despliegue, solo es la ventana desde la que trabajas.

1. **Session → SSH**
2. **Remote host:** la IP del servidor · **Specify username:** tu usuario
3. Puerto 22 salvo que TI lo haya movido

MobaXterm abre a la izquierda un panel SFTP con los archivos del servidor: puedes
arrastrar archivos ahí directamente, que es cómodo para subir el `.env` sin
tener que escribirlo a mano.

> **Recomendación:** autentícate con llave SSH, no con contraseña.
> En MobaXterm: *Tools → MobaKeyGen*, generas la llave, pegas la pública en
> `~/.ssh/authorized_keys` del servidor y apuntas la privada en la sesión.

### 2.3 Preparar el servidor

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
```

Cierra y vuelve a abrir la sesión para que el grupo `docker` tome efecto.

**Importante — que Docker no se caiga solo** (el problema que sí tenemos en WSL):

```bash
sudo systemctl enable --now docker
sudo systemctl disable --now docker.socket
```

### 2.4 Traer el proyecto

```bash
sudo mkdir -p /opt/portal-tickets && sudo chown $USER:$USER /opt/portal-tickets
git clone <url-del-repo-de-CGR> /opt/portal-tickets
```

### 2.5 Configurar el entorno

`.env` **no está en el repositorio** y no debe estarlo. Se crea en el servidor a
partir de la plantilla:

```bash
cp .env.example .env
```

Y se generan secretos reales:

```bash
openssl rand -base64 48
```

Ese valor va en `JWT_SECRET`, y otro distinto en `POSTGRES_PASSWORD`. La
`DATABASE_URL` tiene que llevar la misma contraseña que `POSTGRES_PASSWORD`.

### 2.6 Levantar

```bash
docker compose up -d --build
```

Descargar los modelos de Ollama, una sola vez (quedan en un volumen):

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull qwen2.5:3b
```

Sembrar los datos iniciales:

```bash
docker compose exec backend python seed.py
```

Y el contenido de arranque: los pasos de diagnóstico y la base de conocimiento
inicial, sin los cuales la búsqueda por similitud no tiene nada que sugerir
durante las primeras semanas:

```bash
docker compose exec backend python seed_temas.py
```

**Cambia las contraseñas de los usuarios sembrados antes de dar acceso a nadie.**
`seed.py` crea `admin@cgr.mx` y `operador@cgr.mx` con contraseñas conocidas y
públicas en el repositorio.

### 2.7 Arranque automático

Para que el portal vuelva solo tras un corte de luz o un reinicio:

```bash
sudo tee /etc/systemd/system/portal-tickets.service > /dev/null <<'EOF'
[Unit]
Description=Portal de Tickets TI - CGR
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/portal-tickets
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now portal-tickets
```

Los contenedores ya traen `restart: always`, así que se recuperan solos si un
proceso muere. Esta unidad cubre el caso de reinicio de la máquina.

### 2.8 Activar TLS

La spec pide NGINX desde el día uno justo para que esto sean cinco líneas.
Con un certificado en `/opt/portal-tickets/nginx/certs/`, en
`nginx/default.conf`:

```nginx
listen 443 ssl;
ssl_certificate     /etc/nginx/certs/portal.crt;
ssl_certificate_key /etc/nginx/certs/portal.key;
```

Y montar los certificados en el servicio `nginx` del compose. Redirige el 80 al
443 y, en `AuthContext`, cambia el token de `localStorage` a cookie con
`secure` + `samesite` (spec §12).

### 2.9 Actualizar

```bash
cd /opt/portal-tickets
git pull
docker compose up -d --build
```

El backend aplica `alembic upgrade head` solo al arrancar y **no levanta si las
migraciones fallan**: es preferible un contenedor que no arranca a uno que
atiende peticiones contra un esquema equivocado.

---

## 3. Verificar que quedó bien

```bash
docker compose ps                                    # los 5 arriba
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/        # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/docs    # 200
docker compose exec backend python -m pytest app/tests -q          # 136 passed
docker compose exec ollama ollama list                             # 2 modelos
```

Prueba de degradación — el invariante más importante del sistema:

```bash
docker compose stop ollama
# Levanta un ticket desde el portal: debe crearse igual, y el chat desaparecer.
docker compose start ollama
```

---

## 4. Puertos

Solo el 80 (y el 443 en producción) quedan expuestos. Todo lo demás está
publicado únicamente en `127.0.0.1`, de modo que NGINX sea el único punto de
entrada, como pide la spec §3.

| Servicio | Publicado en | Alcanzable desde |
|---|---|---|
| nginx | `0.0.0.0:80` | La red de la planta |
| backend | `127.0.0.1:8000` | Solo el servidor (depuración y `/docs`) |
| frontend | `127.0.0.1:3000` | Solo el servidor |
| postgres | `127.0.0.1:5433` | Solo el servidor |
| ollama | `127.0.0.1:11434` | Solo el servidor |

Postgres usa el **5433** en el host a propósito: el 5432 suele estar ocupado por
un Postgres local. Dentro de la red de compose sigue siendo el 5432.

---

## 5. Requisitos del servidor

| Recurso | Mínimo | Por qué |
|---|---|---|
| RAM | 8 GB | 4 GB alcanzan solo si prescindes de `qwen2.5:3b`; entonces se pierden normalización y chatbot, pero la búsqueda por similitud sigue. |
| Disco | 20 GB | Imágenes, modelos de Ollama (~2.3 GB) y la base. |
| CPU | 4 núcleos | Ollama es lo que más consume. |

Sin GPU es suficiente: los modelos son pequeños y corren en CPU.
