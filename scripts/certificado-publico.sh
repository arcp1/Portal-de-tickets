#!/usr/bin/env bash
#
# Certificado público de Let's Encrypt: HTTPS sin instalar nada en ningún equipo.
#
# Es la salida al problema de "¿voy a tener que instalar la CA en 300 máquinas?".
# Un certificado público lo reconoce cualquier navegador del mundo sin que nadie
# toque nada, y se renueva solo.
#
# Lo único que hace falta es un **nombre de verdad**: un subdominio de un dominio
# que la empresa controle, por ejemplo portal.cgr.mx. Como el portal es interno,
# ese nombre apunta a la IP privada del servidor; eso es perfectamente válido y
# muy común.
#
#   ./scripts/certificado-publico.sh portal.cgr.mx sistemas@cgr.mx
#   ./scripts/certificado-publico.sh portal.cgr.mx sistemas@cgr.mx --dns
#
# Sin --dns se valida por HTTP: hace falta que Let's Encrypt alcance el puerto 80
# del servidor desde internet. Con --dns se valida poniendo un registro TXT en el
# DNS, que es lo que sirve cuando el servidor **no** sale a internet —el caso
# normal en planta—.

set -uo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="$PROYECTO/nginx/certs"

DOMINIO="${1:-}"
CORREO="${2:-}"
MODO="${3:-http}"

if [ -z "$DOMINIO" ] || [ -z "$CORREO" ]; then
  cat <<'AYUDA'
Uso:
  ./scripts/certificado-publico.sh DOMINIO CORREO [--dns]

  DOMINIO   Un subdominio real que la empresa controle: portal.cgr.mx
            NO sirve portal.cgr.local: .local no existe en internet y ninguna
            autoridad pública lo va a certificar.
  CORREO    Adonde avisa Let's Encrypt si el certificado va a vencer.
  --dns     Validar por DNS en vez de por HTTP. Use esto si el servidor no
            sale a internet, que es lo normal en planta.
AYUDA
  exit 1
fi

if [[ "$DOMINIO" == *.local ]] || [[ "$DOMINIO" != *.*.* && "$DOMINIO" != *.* ]]; then
  echo "ERROR: '$DOMINIO' no sirve para un certificado público."
  echo
  echo "Tiene que ser un subdominio real de un dominio de la empresa, como"
  echo "portal.cgr.mx. Los nombres .local no existen en internet."
  echo
  echo "Si no hay un dominio disponible, use la CA propia:"
  echo "    ./scripts/generar-certificado.sh $DOMINIO"
  echo "y distribuya nginx/certs/ca.crt por GPO. Ver CERTIFICADOS.md."
  exit 1
fi

if docker info >/dev/null 2>&1; then DOCKER=(docker); else DOCKER=(sudo -n docker); fi
COMPOSE=("${DOCKER[@]}" compose -f "$PROYECTO/docker-compose.yml")

mkdir -p "$DESTINO" "$PROYECTO/nginx/acme"

decir() { echo "  $*"; }

# ---------------------------------------------------------------------
if [ "$MODO" = "--dns" ]; then
  echo "Validación por DNS para $DOMINIO"
  echo
  echo "Certbot va a pedirle que ponga un registro TXT en el DNS de la empresa."
  echo "Ese registro se lo tiene que dar de alta quien maneje el dominio."
  echo "Cuando esté puesto, presione Enter y continúa solo."
  echo
  echo "  IMPORTANTE: el registro tarda en propagarse. Espere unos minutos y"
  echo "  compruebe con:  nslookup -type=TXT _acme-challenge.$DOMINIO"
  echo

  "${DOCKER[@]}" run -it --rm \
    -v "$PROYECTO/nginx/acme:/etc/letsencrypt" \
    certbot/certbot certonly \
    --manual --preferred-challenges dns \
    --agree-tos --no-eff-email \
    -m "$CORREO" -d "$DOMINIO"
  RESULTADO=$?
else
  echo "Validación por HTTP para $DOMINIO"
  echo
  echo "Hace falta que Let's Encrypt alcance el puerto 80 de este servidor desde"
  echo "internet. Si no sale a internet, cancele y use --dns."
  echo

  # NGINX ya tiene la ruta /.well-known/acme-challenge/ apuntando aquí.
  "${DOCKER[@]}" run --rm \
    -v "$PROYECTO/nginx/acme:/etc/letsencrypt" \
    -v "$PROYECTO/nginx/certbot:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot -w /var/www/certbot \
    --agree-tos --no-eff-email \
    -m "$CORREO" -d "$DOMINIO"
  RESULTADO=$?
fi

if [ "$RESULTADO" -ne 0 ]; then
  echo
  echo "No se emitió el certificado. El portal sigue como estaba."
  exit 1
fi

# ---------------------------------------------------------------------
EMITIDO="$PROYECTO/nginx/acme/live/$DOMINIO"
if [ ! -s "$EMITIDO/fullchain.pem" ]; then
  echo "ERROR: certbot dijo que sí pero no encuentro $EMITIDO/fullchain.pem"
  exit 1
fi

echo
echo "Instalando el certificado en el portal..."
if [ -s "$DESTINO/portal.crt" ]; then
  SELLO="$(date +%Y%m%d-%H%M%S)"
  mv "$DESTINO/portal.crt" "$DESTINO/portal.crt.$SELLO.bak"
  mv "$DESTINO/portal.key" "$DESTINO/portal.key.$SELLO.bak" 2>/dev/null || true
  decir "(el anterior se guardó con el sello $SELLO)"
fi

cp "$EMITIDO/fullchain.pem" "$DESTINO/portal.crt"
cp "$EMITIDO/privkey.pem"   "$DESTINO/portal.key"
chmod 600 "$DESTINO/portal.key"
chmod 644 "$DESTINO/portal.crt"

echo
echo "Comprobaciones:"
openssl x509 -in "$DESTINO/portal.crt" -noout -subject -issuer -dates \
  | sed 's/^/  /'
decir "OK  emitido por una autoridad pública: ningún equipo tiene que instalar nada"

"${COMPOSE[@]}" up -d nginx >/dev/null 2>&1
echo
decir "NGINX recargado. El portal ya responde en https://$DOMINIO"

cat <<NOTA

Falta una cosa: la renovación.

Let's Encrypt dura 90 días. Para que se renueve solo, en el servidor:

    0 3 * * 1  cd $PROYECTO && ./scripts/certificado-publico.sh $DOMINIO $CORREO >> /var/log/portal-certificado.log 2>&1

Con validación por DNS eso no se puede automatizar sin complemento del proveedor,
así que en ese caso póngase un recordatorio cada dos meses. El portal avisa en la
pantalla de Estado cuando al certificado le quedan menos de 20 días.

Y actualice PORTAL_URL en el .env a https://$DOMINIO
NOTA
