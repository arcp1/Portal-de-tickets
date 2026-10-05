#!/bin/bash
#
# El rol con el que la aplicación entra a Postgres: dueño de las tablas del
# portal y nada más. Sin superusuario (auditoría de seguridad 2026-10-05, M-2).
#
# **Un archivo, dos usos:**
#
#   * Base nueva: la imagen oficial lo corre sola la primera vez que arranca con
#     el volumen vacío (este directorio está montado en
#     /docker-entrypoint-initdb.d). Las migraciones ya crean las tablas a nombre
#     del rol.
#   * Base que ya existe: se corre una vez a mano, y traspasa las tablas:
#         docker compose exec db bash /docker-entrypoint-initdb.d/10-rol-aplicacion.sh
#
# Es idempotente: correrlo otra vez solo reafirma la contraseña y los permisos.
# Ninguna de estas órdenes toca datos; cambian dueños y permisos.
#
# Lo que hace:
#   - crea o actualiza el rol POSTGRES_APP_USER (portal_app) con la contraseña
#     POSTGRES_APP_PASSWORD: entra a la base y ya, sin superusuario, sin crear
#     bases ni roles, sin replicación y sin saltarse RLS;
#   - crea la extensión `vector` como superusuario, para que las migraciones la
#     encuentren hecha y no necesiten privilegios para eso;
#   - solo él (y el superusuario) se conecta a la base del portal; a `postgres`
#     y `template1` solo el superusuario;
#   - le da las tablas del esquema public (con ellas cambian de dueño sus
#     secuencias e índices): las migraciones de Alembic corren al arrancar el
#     backend y necesitan alterarlas.
#
# Lo que pierde quien se haga con las credenciales de la aplicación: ejecutar
# programas en el contenedor de la base (COPY ... PROGRAM), leer o escribir sus
# archivos, crear roles o bases, saltarse RLS y entrar a otras bases. El
# superusuario (POSTGRES_USER) sigue existiendo para administrar y respaldar, y
# su contraseña ya solo la tiene el contenedor de la base.
set -euo pipefail

: "${POSTGRES_USER:?}"
: "${POSTGRES_DB:?}"
PORTAL_ROL="${POSTGRES_APP_USER:-portal_app}"

if [ -z "${POSTGRES_APP_PASSWORD:-}" ]; then
    echo "[rol-aplicacion] Falta POSTGRES_APP_PASSWORD en el .env: no se crea el rol de la aplicación." >&2
    exit 1
fi
case "$PORTAL_ROL" in
    ''|*[!a-z0-9_]*)
        echo "[rol-aplicacion] POSTGRES_APP_USER no válido: '$PORTAL_ROL' (minúsculas, números y _)." >&2
        exit 1 ;;
esac
if [ "$PORTAL_ROL" = "$POSTGRES_USER" ]; then
    echo "[rol-aplicacion] POSTGRES_APP_USER no puede ser el superusuario ($POSTGRES_USER)." >&2
    exit 1
fi
export PORTAL_ROL

# La contraseña entra por `\getenv`, no por la línea de órdenes: así no aparece
# en la lista de procesos.
psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv rol PORTAL_ROL
\getenv clave POSTGRES_APP_PASSWORD
SELECT set_config('portal.rol', :'rol', false) \g /dev/null

-- El rol: entra, y nada más.
SELECT format('CREATE ROLE %I', :'rol')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'rol') \gexec
ALTER ROLE :"rol" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD :'clave';

-- La extensión la crea el superusuario: las migraciones solo la encuentran.
CREATE EXTENSION IF NOT EXISTS vector;

-- Solo la base del portal.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', current_database(), :'rol') \gexec
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;

-- El esquema: usarlo y crear tablas nuevas (las migraciones futuras).
GRANT USAGE, CREATE ON SCHEMA public TO :"rol";

-- Las tablas del portal pasan a ser suyas. Sus secuencias (las de las columnas
-- autonuméricas) y sus índices cambian de dueño con ellas; una secuencia suelta,
-- si alguna vez la hay, se traspasa aparte. Lo que pertenece a una extensión
-- (vector) no se toca.
DO $$
DECLARE
    rol text := current_setting('portal.rol');
    objeto record;
    n integer := 0;
BEGIN
    FOR objeto IN
        SELECT c.oid::regclass AS nombre, c.relkind
          FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
         WHERE s.nspname = 'public'
           AND c.relkind IN ('r', 'p', 'S')
           AND pg_get_userbyid(c.relowner) <> rol
           AND NOT EXISTS (SELECT 1 FROM pg_depend d
                            WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                              AND d.deptype IN ('e', 'a'))
         ORDER BY c.relkind DESC
    LOOP
        EXECUTE format('ALTER %s %s OWNER TO %I',
                       CASE objeto.relkind WHEN 'S' THEN 'SEQUENCE' ELSE 'TABLE' END,
                       objeto.nombre, rol);
        n := n + 1;
    END LOOP;
    RAISE NOTICE 'Objetos traspasados a %: %', rol, n;
END $$;

-- Lo que quedó, para que quien lo corra lo vea.
\pset tuples_only on
\pset format unaligned
SELECT format('[rol-aplicacion] %s: superusuario=%s, crea bases=%s, crea roles=%s; tablas suyas %s de %s',
              r.rolname, r.rolsuper, r.rolcreatedb, r.rolcreaterole,
              (SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = r.rolname),
              (SELECT count(*) FROM pg_tables WHERE schemaname = 'public'))
  FROM pg_roles r WHERE r.rolname = :'rol' \g
SQL
