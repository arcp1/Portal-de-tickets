#!/usr/bin/env bash
#
# Certificado TLS para el portal.
#
# Sin TLS, la contraseña que teclea un operador y el código de activación que le
# entrega TI viajan en claro por la red de planta. Cualquiera con acceso al
# switch los lee. Con 300 personas cargando sus contraseñas, eso deja de ser
# teórico.
#
# ----------------------------------------------------------------------
# POR QUÉ SON DOS CERTIFICADOS Y NO UNO
# ----------------------------------------------------------------------
# La primera versión de este script generaba un solo certificado autofirmado. Se
# probó en Chrome y falló con NET::ERR_CERT_INVALID **sin ofrecer el botón de
# "continuar de todas formas"**, así que el portal quedaba inaccesible. Dos
# motivos, los dos evitables:
#
#   1. Duraba 825 días. Chrome rechaza de plano cualquier certificado de más de
#      398 días. No avisa: lo invalida.
#   2. Llevaba la extensión basicConstraints **dos veces** —CA:TRUE por omisión
#      de `req -x509`, y CA:FALSE que le agregaba el script—. Un certificado con
#      una extensión duplicada está mal formado, y ante eso Chrome no ofrece
#      excusa ni botón.
#
# La solución no es solo arreglar esos dos números. Es hacerlo como se hace en
# una empresa: **una autoridad propia (CA) y certificados de servidor firmados
# por ella.**
#
#   ca.crt      10 años.  Se instala UNA VEZ en los equipos, por GPO.
#   portal.crt  397 días. Se renueva cada año SIN tocar ningún equipo.
#
# Con un solo certificado, cada renovación obligaría a repetir el despliegue en
# las 300 máquinas. Con la CA, se renueva el del servidor y ya.
#
# ----------------------------------------------------------------------
# Uso:
#   ./scripts/generar-certificado.sh                       # localhost
#   ./scripts/generar-certificado.sh portal.cgr.local 192.168.1.50
#
# Después:
#   docker compose up -d nginx
#
# Y para que desaparezca el aviso del navegador, instalar **nginx/certs/ca.crt**
# (no el otro) como entidad de certificación raíz de confianza.

set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="$PROYECTO/nginx/certs"

# 397 días: un año y un mes de margen, dentro del tope de 398 que impone Chrome.
DIAS_SERVIDOR="${DIAS_SERVIDOR:-397}"
DIAS_CA="${DIAS_CA:-3650}"

mkdir -p "$DESTINO"

NOMBRES=("$@")
if [ ${#NOMBRES[@]} -eq 0 ]; then
  NOMBRES=(localhost)
fi

# Los nombres por los que la gente va a llegar al portal. Si no coinciden con lo
# que teclean, el navegador avisa aunque el certificado esté bien.
ALTERNATIVOS=""
i_dns=0
i_ip=0
for n in "${NOMBRES[@]}"; do
  if [[ "$n" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    i_ip=$((i_ip + 1))
    ALTERNATIVOS="${ALTERNATIVOS}IP.${i_ip} = ${n}"$'\n'
  else
    i_dns=$((i_dns + 1))
    ALTERNATIVOS="${ALTERNATIVOS}DNS.${i_dns} = ${n}"$'\n'
  fi
done
# localhost y 127.0.0.1 siempre, para poder probar desde el propio servidor.
if [[ ! " ${NOMBRES[*]} " =~ " localhost " ]]; then
  i_dns=$((i_dns + 1))
  ALTERNATIVOS="${ALTERNATIVOS}DNS.${i_dns} = localhost"$'\n'
fi
i_ip=$((i_ip + 1))
ALTERNATIVOS="${ALTERNATIVOS}IP.${i_ip} = 127.0.0.1"

decir() { echo "  $*"; }

# ---------------------------------------------------------------------
# 1. La autoridad de la planta. Se crea una sola vez.
# ---------------------------------------------------------------------
if [ -s "$DESTINO/ca.crt" ] && [ -s "$DESTINO/ca.key" ]; then
  echo "Autoridad propia: ya existe, se reutiliza."
  decir "(si se regenerara, habría que reinstalarla en todos los equipos)"
else
  echo "Creando la autoridad de certificación de la planta..."
  openssl req -x509 -nodes -newkey rsa:4096 \
    -days "$DIAS_CA" \
    -keyout "$DESTINO/ca.key" \
    -out "$DESTINO/ca.crt" \
    -subj "/C=MX/ST=Queretaro/L=Queretaro/O=CGR de Mexico/OU=Sistemas TI/CN=CGR Queretaro - Autoridad interna" \
    2>/dev/null
  chmod 600 "$DESTINO/ca.key"
  decir "ca.crt creada, válida $DIAS_CA días"
fi

# ---------------------------------------------------------------------
# 2. El certificado del servidor, firmado por la autoridad
# ---------------------------------------------------------------------
echo
echo "Generando el certificado del portal para: ${NOMBRES[*]}"

if [ -s "$DESTINO/portal.crt" ]; then
  SELLO="$(date +%Y%m%d-%H%M%S)"
  mv "$DESTINO/portal.crt" "$DESTINO/portal.crt.$SELLO.bak"
  [ -s "$DESTINO/portal.key" ] && mv "$DESTINO/portal.key" "$DESTINO/portal.key.$SELLO.bak"
  decir "(el anterior se guardó con el sello $SELLO)"
fi

# Las extensiones van en un archivo, no en -addext. Así se controla exactamente
# qué lleva el certificado y no se duplica ninguna extensión, que fue lo que lo
# invalidó la primera vez.
EXTENSIONES="$(mktemp)"
trap 'rm -f "$EXTENSIONES" "$DESTINO/portal.csr"' EXIT

cat > "$EXTENSIONES" <<EXT
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
subjectAltName = @nombres

[nombres]
$ALTERNATIVOS
EXT

openssl req -nodes -newkey rsa:2048 \
  -keyout "$DESTINO/portal.key" \
  -out "$DESTINO/portal.csr" \
  -subj "/C=MX/ST=Queretaro/L=Queretaro/O=CGR de Mexico/OU=Sistemas TI/CN=${NOMBRES[0]}" \
  2>/dev/null

openssl x509 -req \
  -in "$DESTINO/portal.csr" \
  -CA "$DESTINO/ca.crt" -CAkey "$DESTINO/ca.key" -CAcreateserial \
  -days "$DIAS_SERVIDOR" \
  -extfile "$EXTENSIONES" \
  -out "$DESTINO/portal.crt" \
  2>/dev/null

chmod 600 "$DESTINO/portal.key"
chmod 644 "$DESTINO/portal.crt" "$DESTINO/ca.crt"

# ---------------------------------------------------------------------
# 3. Comprobar antes de cantar victoria
# ---------------------------------------------------------------------
echo
echo "Comprobaciones:"

if openssl verify -CAfile "$DESTINO/ca.crt" "$DESTINO/portal.crt" >/dev/null 2>&1; then
  decir "OK  el certificado lo firma la autoridad de la planta"
else
  decir "MAL el certificado no verifica contra la CA"; exit 1
fi

REPETIDAS=$(openssl x509 -in "$DESTINO/portal.crt" -noout -text \
  | grep -c "X509v3 Basic Constraints" || true)
if [ "$REPETIDAS" -eq 1 ]; then
  decir "OK  basicConstraints aparece una sola vez"
else
  decir "MAL basicConstraints aparece $REPETIDAS veces: el certificado quedaría malformado"
  exit 1
fi

if [ "$DIAS_SERVIDOR" -le 398 ]; then
  decir "OK  $DIAS_SERVIDOR días, dentro del tope de 398 que exige Chrome"
else
  decir "MAL $DIAS_SERVIDOR días: Chrome rechaza cualquier cosa por encima de 398"
  exit 1
fi

decir "OK  nombres: $(openssl x509 -in "$DESTINO/portal.crt" -noout -ext subjectAltName \
  | tail -1 | sed 's/^ *//')"

cat <<NOTA

Para que surta efecto:
    docker compose up -d nginx

A partir de ahí, http:// redirige a https:// solo.

FALTA UN PASO, y sin él el navegador va a seguir avisando:

    Instalar  nginx/certs/ca.crt  como entidad de certificación raíz de
    confianza en los equipos. OJO: se instala **ca.crt**, no portal.crt.

    En un equipo suelto (Windows): doble clic en ca.crt > Instalar certificado
    > Equipo local > Colocar todos los certificados en el siguiente almacén >
    Entidades de certificación raíz de confianza.

    Para toda la planta: por GPO, en Configuración del equipo > Directivas >
    Configuración de Windows > Configuración de seguridad > Directivas de clave
    pública > Entidades de certificación raíz de confianza.

La gracia de haberlo hecho con CA propia: eso se hace UNA vez. El certificado
del portal se renueva cada año volviendo a correr este script, y ningún equipo
se entera.

Y actualice PORTAL_URL en el .env a https://..., que es la dirección que sale
en los correos de aviso.
NOTA
