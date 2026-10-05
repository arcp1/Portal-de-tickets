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

> **Al cambiar el `.env`, `restart` no vale.** Un contenedor se queda con las
> variables que tenía cuando se creó; `docker compose restart` lo para y lo
> vuelve a arrancar con las mismas. Hay que recrearlo:
>
> ```bash
> docker compose up -d backend
> ```
>
> Comprobado en esta máquina: con el `.env` ya editado, después de `restart` el
> contenedor seguía con el valor viejo, y solo tras `up -d` tomó el nuevo. Es
> una trampa fea porque el cambio **parece** aplicado —el servicio se reinició,
> no hubo error— y no lo está. Para salir de dudas:
>
> ```bash
> docker compose exec -T backend printenv OLLAMA_TIMEOUT_CLASIFICACION
> ```

Descargar los modelos de Ollama, una sola vez (quedan en un volumen):

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull qwen2.5:3b
```

Crear la planta y su primer administrador, con los valores de la sección
«Siembra» del `.env` (`SEED_SITIO_*`, `SEED_ADMIN_*`):

```bash
docker compose exec backend python seed.py
```

Es **todo** lo que crea: ni equipos, ni personas, ni reglas de ejemplo. El
inventario arranca en cero y así lo enseña el portal; los equipos, las personas
y las reglas se dan de alta desde el propio portal. Si `SEED_ADMIN_PASSWORD`
está vacía, la contraseña del administrador se genera al azar y se imprime una
sola vez en la consola: anótela en ese momento.

Y el contenido de arranque: los pasos de diagnóstico y la base de conocimiento
inicial, sin los cuales la búsqueda por similitud no tiene nada que sugerir
durante las primeras semanas:

```bash
docker compose exec backend python seed_temas.py
```

Correr cualquiera de los dos otra vez no duplica nada ni toca la contraseña de
una cuenta que ya exista.

### 2.7 Arranque automático

Para que el portal vuelva solo tras un corte de luz o un reinicio:

> **Lo que pasó el 2026-10-02 sin esta unidad.** El servidor se reinició por
> una actualización de kernel y **el portal se quedó caído hora y media**:
> Docker levanta los contenedores (`restart: always`) en cuanto arranca, y eso
> es antes de que Tailscale tenga su IP. nginx se publica en `100.101.51.95:80`,
> no la pudo tomar ("cannot assign requested address") y quedó `Exited`.
> `restart: always` **no reintenta** un fallo de publicación de puerto. Lo mismo
> le puede pasar a Mosquitto con la IP de la LAN.
>
> La unidad de abajo lo resuelve: espera a Tailscale y a que las dos IP
> existan, y entonces corre `docker compose up -d`, que vuelve a crear lo que
> no arrancó. Ajuste `WorkingDirectory` y las IP a las del servidor.

```bash
sudo tee /etc/systemd/system/portal-tickets.service > /dev/null <<'EOF'
[Unit]
Description=Portal de Tickets TI - CGR
Requires=docker.service
Wants=tailscaled.service network-online.target
After=docker.service network-online.target tailscaled.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/arc/Portal-de-tickets
# nginx escucha en la IP del tailnet y Mosquitto en la de la LAN: sin ellas
# la publicación del puerto falla y el contenedor no vuelve solo.
ExecStartPre=/bin/sh -c 'for i in $(seq 1 90); do ip -4 addr | grep -q "100.101.51.95/" && ip -4 addr | grep -q "192.168.1.168/" && exit 0; sleep 2; done; exit 1'
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

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

NGINX es el único punto de entrada al portal (spec §3). Desde el 2026-10-02 hay
un segundo puerto hacia fuera, el de Mosquitto, porque los ESP32 viven en la red
de la planta y no en el tailnet. Todo lo demás no se publica: se alcanza solo
por la red interna de compose.

| Servicio | Publicado en | Alcanzable desde |
|---|---|---|
| nginx | `100.101.51.95:80` | El tailnet |
| nginx (Funnel) | `127.0.0.1:8080` | Solo el servidor; lo publica `tailscale funnel` si se activa |
| mosquitto | `${MQTT_PUBLICAR}` (hoy `192.168.1.168:1883`) | La red de la planta (ESP32), con usuario y ACL |
| backend, frontend | — | Solo la red de compose |
| postgres, redis | — | Solo la red de compose |
| ollama | — | Solo la red de compose |
| worker, ingestor | — | No escuchan; hablan con Redis, Postgres y Mosquitto |

`MQTT_PUBLICAR` usa la IP de la LAN, que hoy da el DHCP: **resérvela en el
router** o los ESP32 perderán el broker el día que cambie (pasó de `.169` a
`.168` en el reinicio del 2026-10-02).

### 4.1 Servicios de segundo plano (2026-10-02)

| Servicio | Qué hace | Si se cae |
|---|---|---|
| `redis` | Limitadores compartidos, sesiones revocadas, avisos en vivo entre procesos, cola del worker | El portal sigue en memoria (`core/redis_cliente.py`) |
| `worker` | Indexa al cerrar tickets, manda correos, vigila el SLA cada minuto y los sensores cada 5 | Lo encolado espera; sin Redis, todo se hace en la petición |
| `mosquitto` | Broker MQTT de los ESP32 (`mosquitto/`) | Los sensores no publican; el portal no se entera hasta la alerta «sin señal» |
| `ingestor` | Lee la telemetría y la guarda; abre y cierra alertas | Mosquitto le guarda los mensajes (sesión persistente, QoS 1) |

Las versiones de Python van fijadas en `backend/constraints.txt`: reconstruir
la imagen sin él subió SQLAlchemy a 2.1 y el backend no arrancaba.

---

## 5. Requisitos del servidor

| Recurso | Mínimo | Por qué |
|---|---|---|
| RAM | 8 GB | 4 GB alcanzan solo si prescindes de `qwen2.5:3b`; entonces se pierden normalización y chatbot, pero la búsqueda por similitud sigue. |
| Disco | 20 GB | Imágenes, modelos de Ollama (~2.3 GB) y la base. |
| CPU | 4 núcleos | Ollama es lo que más consume. |

Sin GPU es suficiente: los modelos son pequeños y corren en CPU.

## Rendimiento de la IA local: el gobernador de energía del host

> **Esta sección se ha corregido dos veces. Merece la pena leer por qué.**
>
> La primera versión decía que leer el prompt iba a 11-13 tokens/s y que ahí se
> iba el tiempo. La segunda «corrigió» eso a 2610 tokens/s, «despreciable». La
> segunda estaba mal y la primera tenía razón; abajo están los números buenos.
>
> El error de la segunda fue medir con **el mismo prompt cinco veces**. Ollama
> cachea el prompt, así que solo la primera llamada hace el trabajo: medido
> aquí, 600 tokens tardan 30 s la primera vez y **0,04 s** las siguientes. Mil
> veces menos. Descartar la primera muestra —que es lo correcto para no pagar la
> carga del modelo— dejaba justo las cuatro que dan en la caché.
>
> En producción el texto es **siempre nuevo**: es lo que acaba de escribir una
> persona. La caché no acierta ahí. `scripts/medir-ia.py` ya varía la
> descripción en cada repetición para no volver a caer.

**Medido en esta máquina, con el gobernador en `powersave` (~2579 MHz), con una
descripción distinta en cada repetición y mediana de cinco:**

    trabajo        total          leer                 generar
    normalizar     3.37 s    2.24 s   95 tok  42 t/s   1.08 s   32 tok  30 t/s
    clasificar     2.91 s    2.30 s  113 tok  49 t/s   0.56 s   17 tok  30 t/s
    redactar       9.31 s    2.30 s   54 tok  24 t/s   6.98 s  200 tok  29 t/s

**No hay un solo cuello de botella: depende del trabajo.**

- **Normalizar y clasificar** —los dos que corren en *cada ticket*— se van en
  **leer el prompt**: 2,2 s de 3,4 y 2,3 s de 2,9. Leer está limitado por
  cómputo puro.
- **Redactar** se va en **generar**: 7,0 s de 9,3. Generar está limitado por el
  ancho de banda a la RAM, no por la frecuencia.

Dicho en la unidad que se puede usar para decidir: **un token del prompt cuesta
unos 60 ms y un token generado unos 34 ms**. Un token que entra cuesta casi el
doble que uno que sale. Por eso hay una prueba que impide que los prompts
crezcan (`test_normalizacion_y_prompts.py`): cada palabra de más se paga en
cada consulta, y solo la parte **fija** del prompt —la instrucción, que va
delante— se libra gracias a la caché. De ahí también que poner el campo
`system` fuera tan caro: rompía ese prefijo fijo.

**El gobernador se probó, y no cambia nada. Medido.**

Se puso `performance` en los dieciséis hilos. La frecuencia media en reposo
subió de ~2600 a **3958 MHz**, y durante la inferencia el procesador corre a
3500-4500 MHz a 61 °C, o sea que no hay estrangulamiento térmico: el reloj
está de verdad más alto. Con la máquina ociosa, dos pasadas del banco:

    trabajo        powersave     performance
    normalizar       3.37 s      3.40 / 3.48 s
    clasificar       2.85 s      2.91 / 2.91 s
    redactar         9.25 s      9.31 / 9.28 s

**+52 % de reloj, 0 % de mejora.** Eso descarta el cómputo como cuello de
botella —también para leer el prompt, al contrario de lo que decía aquí
antes— y apunta al ancho de banda a memoria, que no sube con la frecuencia del
núcleo. Dejarlo en `performance` o volver a `powersave` es indiferente para el
portal; lo segundo gasta menos.

> **Cuidado al medir esto.** La primera pasada dio `performance` *peor* que
> `powersave`. No era el gobernador: había dos baterías de pruebas corriendo a
> la vez, al 100 % de CPU cada una. Antes de comparar, `uptime` — con la carga
> por encima de 1 el número no vale.

**Lo que sí cambió las cosas: cuántos hilos usa el modelo.**

Ollama reparte por defecto entre los ocho núcleos físicos, y en esta máquina eso
hunde la lectura del prompt. Medido con texto nuevo en cada muestra, mediana de
tres:

    hilos     leer tok/s     generar tok/s
      3          53.6            25.9
      4          62.9            27.7
      6          45.6            28.6
      8          10.0            28.7      <- el reparto por defecto
     16           9.8            25.6

Leer va **seis veces más lento con ocho hilos que con cuatro**. Generar apenas
se mueve. Como leer es la mitad o más de cada llamada, el efecto de punta a
punta es el mayor de toda la puesta a punto:

    normalizar   3.38 s -> 1.50 s
    clasificar   2.78 s -> 0.95 s
    redactar     9.27 s -> 7.55 s

Se aplica con `OLLAMA_HILOS_TEXTO` (por defecto 4) y solo al modelo de texto:
en los embeddings el reparto por defecto gana. **Si se cambia de máquina o de
modelo hay que volver a medirlo** — el número bueno depende de las dos cosas.

El procesador, en todo caso, no está dando lo que puede:

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor    # powersave
grep MHz /proc/cpuinfo | awk '{s+=$4; n++} END {print s/n}'  # ~2600 MHz
```

El Ryzen 7 PRO 8700GE sube a más de 5 GHz y está trabajando a menos de 2,9 GHz
de media. Es un procesador de 35 W, así que parte de eso es su límite térmico
real, pero el gobernador en `powersave` deja rendimiento sobre la mesa.

**Esto no se cambia desde el proyecto**: es una configuración del sistema
operativo del host y afecta a todo lo que corra en él, no solo al portal. La
decisión es de quien administre la máquina. Para probarlo sin que quede
permanente:

```bash
sudo cpupower frequency-set -g performance
```

Y para dejarlo como estaba:

```bash
sudo cpupower frequency-set -g powersave
```

Si se prueba, conviene volver a medir antes y después con el desglose real,
que es lo único que dice si sirvió:

```bash
docker compose exec -T backend python - < scripts/medir-ia.py
```

Ese guion descarta la primera llamada y toma la mediana de cinco, que es justo
lo que le faltaba a la medición equivocada de arriba. Va por la entrada
estándar porque `scripts/` no se monta en el contenedor y el sistema de
archivos del backend es de solo lectura.

**Qué cambia si mejora.** La clasificación del chat es la que más lo nota: hoy
tarda ~9 s en leer su prompt y se pasa de su timeout de 10 s, así que el chat
cae al camino de los desplegables. Con el prefill al doble, entraría holgada.

**Qué NO depende de esto.** La normalización de descripciones ya no bloquea a
nadie —corre después de entregar el folio— y el asistente que redacta respuestas
funciona bien, porque ahí el costo está en generar y no en leer.


## Ver una pantalla sin sesión y sin datos reales

    python3 scripts/vista-previa.py            # una planta a medio documentar
    python3 scripts/vista-previa.py vacio      # el primer día, todo en cero
    python3 scripts/vista-previa.py roto       # todos los avisos disparados

Abre http://localhost:8099/conocimiento con el frontend ya construido y una API
simulada. La sesión se inyecta sola: no hay que iniciarla ni tener una cuenta.
También sirve `/conocimiento/catalogo` y las pantallas de la
reorganización del menú (`/documentos/archivos/1`, `/operacion/alertas`,
`/sistema/bitacora`, `/sistema/metricas`), y el reconocimiento por foto se dispara
escribiendo «sale borroso» en el chat o en la descripción de `/new-ticket`.

**Qué frontend sirve, que importa.** Si existe `frontend/dist` usa ése y lo dice
al arrancar; si no, saca el que está dentro de la imagen del contenedor. La
diferencia se nota cuando se acaba de tocar una pantalla: hay que compilar
primero, o se estará mirando la versión anterior. Compilar no necesita npm en el
servidor:

    docker run --rm -v "$PWD/frontend":/app -w /app \
      -u "$(id -u):$(id -g)" node:20-alpine npx vite build

**Para qué sirve.** Estas pantallas cambian de forma según los datos —el mapa
pinta distinto un hueco que un vacío, la tubería marca atascos, los avisos
aparecen y desaparecen— y producir esos estados en la base real es lento y a
veces imposible sin ensuciarla.

No es teórico: el estado `roto` encontró un fallo la primera vez que se usó. El
panel de realimentación pintaba de verde cualquier tasa de utilidad con tal de
que hubiera votos, así que «4 de 30 sirvieron (13 %)» salía con el estilo de
buena noticia.

**Lo que no hace.** No prueba el backend ni la autenticación; las respuestas son
constantes escritas en el propio script. Y si la forma que devuelve
`ConcienciaService` cambia y nadie actualiza esas constantes, la vista previa
enseñará una pantalla que ya no existe. Ante la duda, contraste con la real.
