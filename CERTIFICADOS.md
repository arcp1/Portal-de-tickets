# HTTPS sin que nadie instale nada

Respuesta a una pregunta razonable: *"¿voy a tener que hacerlo manual en 300
máquinas?"*

**No.** Instalar la CA a mano en cada equipo es la peor de tres opciones, y solo
sirve para probar en su propia computadora hoy. Aquí están las tres, de mejor a
peor para el caso de CGR.

---

## Resumen

| | Quién instala qué | Renovación | Necesita |
|---|---|---|---|
| **A · CA de Windows del dominio** | **Nadie.** Ya es de confianza en todo equipo del dominio | Automática | Que exista Active Directory |
| **B · Certificado público (Let's Encrypt)** | **Nadie.** Lo reconoce cualquier navegador del mundo | Automática, cada 60 días | Un subdominio real y control del DNS |
| **C · CA propia + GPO** | Sistemas, **una vez**, por directiva | Solo el del servidor, sin tocar equipos | Nada |
| ~~D · A mano en cada equipo~~ | Usted, 300 veces | 300 veces otra vez | Paciencia |

La D no es una opción. Está aquí para nombrarla y descartarla.

---

## A · Si CGR tiene dominio de Windows

**Es la mejor y probablemente ya está disponible.** Si los equipos se unen a un
dominio y la gente entra con su usuario de red, hay Active Directory; y donde hay
AD casi siempre hay una CA interna (*Servicios de certificados de Active
Directory*).

Lo bueno: **esa CA ya es de confianza en todos los equipos del dominio.** Windows
la distribuye solo. No hay que instalar nada, ni por GPO ni a mano.

Lo que hay que pedirle a Sistemas corporativo:

> Necesito un certificado de servidor web para `portal.cgr.local` (y la IP
> `192.168.x.x`), emitido por la CA interna, con la llave privada exportable en
> formato PEM.

Le van a entregar dos archivos. Se ponen así:

```bash
cp el-que-les-dieron.crt nginx/certs/portal.crt
cp la-llave.key          nginx/certs/portal.key
docker compose up -d nginx
```

Y ya. Cero avisos, cero instalaciones, y la renovación la maneja el dominio.

**Antes de nada, pregunte esto.** Si la respuesta es que sí hay CA interna, las
otras dos opciones sobran.

---

## B · Certificado público, sin instalar nada en ningún lado

Si no hay CA interna, ésta es la siguiente. Un certificado de **Let's Encrypt**
lo reconoce cualquier navegador del planeta sin instalar nada, y se renueva solo.

Lo que hace falta: **un nombre de verdad**, por ejemplo `portal.cgr.mx`, y que
Sistemas pueda tocar el DNS de `cgr.mx`. Como el portal es interno, el nombre
apunta a la IP privada del servidor.

### Si el servidor sale a internet

El camino fácil. Se valida por HTTP y ya está automatizado:

```bash
./scripts/certificado-publico.sh portal.cgr.mx sistemas@cgr.mx
```

### Si el servidor NO sale a internet

Que es lo normal en planta. Entonces se valida por DNS: Let's Encrypt pide poner
un registro TXT en `cgr.mx` y comprueba eso, sin necesidad de alcanzar el
servidor.

```bash
./scripts/certificado-publico.sh portal.cgr.mx sistemas@cgr.mx --dns
```

El script se detiene y le dice exactamente qué registro TXT pedirle a quien
maneja el DNS. Se renueva cada 60 días repitiendo el paso, o automático si el
proveedor de DNS tiene complemento.

> **Ojo con el nombre.** Tiene que ser un subdominio real de un dominio que la
> empresa controle. Con `portal.cgr.local` esto no funciona: `.local` no existe
> en internet y ninguna autoridad pública lo va a certificar.

---

## C · CA propia + GPO

Es lo que está configurado hoy, y sirve perfectamente si las dos anteriores no se
pueden. La instalación es **una sola vez para toda la planta**, por directiva de
grupo — no equipo por equipo.

Lo que se le pide a quien administre el dominio:

> Distribuir `ca.crt` por GPO en: Configuración del equipo → Directivas →
> Configuración de Windows → Configuración de seguridad → Directivas de clave
> pública → **Entidades de certificación raíz de confianza**.

Se arrastra el archivo ahí y listo. Los equipos lo recogen en el siguiente
reinicio o `gpupdate /force`.

**Lo que NO hay que volver a hacer nunca:** cuando el certificado del portal
venza al año, se vuelve a correr `./scripts/generar-certificado.sh` en el
servidor y ya. La CA sigue siendo la misma y los equipos siguen confiando. Ésa
era la razón de partirlo en dos.

### Instalarlo a mano (solo para su equipo, hoy)

Para poder trabajar mientras se resuelve lo de arriba:

1. Doble clic en `nginx/certs/ca.crt`
2. **Instalar certificado** → **Equipo local**
3. **Colocar todos los certificados en el siguiente almacén** → **Examinar…**
4. Elegir **Entidades de certificación raíz de confianza** → Aceptar
5. Siguiente → Finalizar
6. **Cerrar Chrome por completo** y volver a abrirlo

El paso 4 es el que se salta todo el mundo: si se deja el "Almacén de
certificados" vacío, el asistente no lo pone donde tiene que ir.

---

## Y mientras tanto

El portal funciona por HTTP sin problema:

```bash
TLS_ACTIVO=off docker compose up -d --force-recreate nginx
```

Es aceptable para probar en su equipo. **No lo es para el día que entren las 300
personas**, porque ahí sí empiezan a viajar contraseñas reales por la red de
planta.
