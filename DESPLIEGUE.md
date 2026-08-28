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

`JWT_SECRET` es lo único que separa una sesión legítima de una falsificada:
quien lo conozca se firma un token de administrador. Los valores de ejemplo están
en el repositorio, así que valen tanto como no tener secreto — **con
`ENVIRONMENT` distinto de `development`, el backend se niega a arrancar si
detecta uno de ellos**. Cambiarlo cierra todas las sesiones abiertas, así que
conviene hacerlo antes de dar de alta a la gente, no después.

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

#### Qué es esto, en corto

Sin TLS, todo lo que se teclea en el portal viaja por la red **como texto plano**.
Cualquiera conectado al mismo switch puede leerlo con herramientas que se bajan
gratis: contraseñas, códigos de activación, todo. No hace falta ser hacker; hace
falta estar en la misma red.

TLS es lo que pone la "s" en `https` y el candado en el navegador. Hace dos cosas:

1. **Cifra** lo que va y viene, para que quien lo intercepte solo vea basura.
2. **Identifica** al servidor, para que el navegador sepa que está hablando con
   nuestro portal y no con la laptop de alguien haciéndose pasar por él.

El **certificado** es el archivo que hace la segunda parte: la credencial del
servidor. Como cualquier credencial, importa quién la firma.

- Un certificado **autofirmado** —el que genera el script— es como una credencial
  que uno mismo se imprime. Cifra exactamente igual de bien; lo que no tiene es
  quién responda por ella. Por eso el navegador enseña *"Tu conexión no es
  privada"*: no está diciendo que sea insegura, está diciendo *"no conozco a quien
  firmó esto"*.
- Un certificado firmado por una **autoridad conocida** —la CA interna de la
  empresa, o una pública— no enseña ese aviso, porque el navegador ya confía en
  quien lo firmó.

La solución para la planta es **decirle a las computadoras de la empresa que
confíen en nuestro certificado**. Eso se hace una vez, por GPO, y el aviso
desaparece en todas. Mientras no se haga, el candado funciona pero con
advertencia.

#### Por qué no es opcional

**Esto no es opcional en planta.** Sin TLS, la contraseña que teclea un operador
y el código de activación que le entrega TI viajan en claro por la red. Con 300
personas cargando sus contraseñas la primera semana, deja de ser teórico.

Ya no hay que editar configuración: NGINX sirve por HTTPS en cuanto encuentra el
certificado, y el 80 pasa a redirigir al 443.

```bash
./scripts/generar-certificado.sh portal.cgr.local 192.168.1.50
docker compose up -d nginx
```

Los nombres que se le pasan son **por los que la gente va a llegar al portal**.
Si no coinciden con lo que teclean, el navegador avisa aunque el certificado
esté bien.

#### Son dos certificados, y hay una razón

El script genera dos cosas:

| Archivo | Dura | Qué es |
|---|---|---|
| `ca.crt` | 10 años | La autoridad de la planta. **Esto es lo que se instala en los equipos**, una sola vez. |
| `portal.crt` | 397 días | El del servidor, firmado por la anterior. Se renueva cada año **sin tocar ningún equipo**. |

Con un solo certificado autofirmado, cada renovación obligaría a repetir el
despliegue en las 300 máquinas. Con la CA propia, se vuelve a correr el script y
ya está.

#### Dos cosas que invalidan un certificado en Chrome

Las dos se probaron y las dos dejaron el portal **inaccesible**, con
`NET::ERR_CERT_INVALID` y **sin ofrecer el botón de "continuar de todas
formas"**. El script las comprueba antes de terminar, pero conviene saberlas:

1. **Más de 398 días de validez.** Chrome no avisa: invalida el certificado. Por
   eso el del servidor dura 397.
2. **Una extensión duplicada.** `openssl req -x509` agrega `basicConstraints`
   por su cuenta; si además se le pasa otra con `-addext`, el certificado queda
   con la extensión dos veces y **malformado**. Por eso las extensiones van en un
   archivo aparte y no con `-addext`.

#### El aviso del navegador

Un certificado autofirmado cifra igual que uno comprado, pero nadie conocido lo
respalda, así que el navegador enseña "Tu conexión no es privada". Si eso pasa el
primer día que entran 300 personas, la conclusión de todas va a ser "el portal no
sirve". Dos salidas, en orden de preferencia:

1. **Que Sistemas lo emita desde la CA interna** de la empresa. Si hay dominio de
   Windows, casi seguro la hay, y entonces no hay aviso en ninguna máquina del
   dominio.
2. **Instalar `nginx/certs/ca.crt` como entidad de confianza** en los equipos,
   con una GPO. **Ojo: se instala `ca.crt`, no `portal.crt`.** En una máquina
   suelta: doble clic → Instalar certificado → Equipo local → Colocar todos los
   certificados en el siguiente almacén → Entidades de certificación raíz de
   confianza.

   Por GPO: Configuración del equipo → Directivas → Configuración de Windows →
   Configuración de seguridad → Directivas de clave pública → Entidades de
   certificación raíz de confianza.

Haga esto **antes** de anunciar el portal, no después. Comprobado: con la CA
instalada, la cadena valida limpia y el navegador no avisa.

#### El interruptor de marcha atrás

Si el aviso causa problemas y hace falta volver a HTTP en un minuto:

```bash
TLS_ACTIVO=off docker compose up -d nginx
```

Y `TLS_ACTIVO=auto` (o quitarlo) para volver a HTTPS. Es para salir del paso,
no para quedarse ahí.

#### Después de activarlo

- `PORTAL_URL` en el `.env` pasa a `https://...`: es la dirección que sale en
  los correos de aviso.
- Queda pendiente mover el token de `localStorage` a cookie `secure` +
  `samesite` (spec §12). Con TLS ya no viaja en claro, pero seguiría siendo
  legible por cualquier script en la página.

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
