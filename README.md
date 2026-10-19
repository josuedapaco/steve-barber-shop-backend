# Steve Barber Shop — FastAPI Backend

API independiente en **Python 3.13 y FastAPI**, con SQLite persistente. Sirve las reservas, disponibilidad, altas de barberos, permisos, sesiones y resumen del manager. El frontend Vue está en el repositorio `steve-barber-shop-frontend`.

## Desarrollo

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# Define STAFF_PIN (mínimo 12 caracteres), los códigos de los barberos,
# DATABASE_PATH=./data/barber.sqlite y PUBLIC_ORIGIN=http://localhost:5173
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 3000 --env-file .env --reload
```

Utiliza el origen exacto que muestra Vite, incluido puerto y esquema. En producción es `https://stevesbarbershopny.com`. La sesión usa cookies HttpOnly, Secure y SameSite=Lax; el dominio público debe tener HTTPS. No hay claves reales en este repositorio.

Documentación de API: `/docs`. Salud del servicio: `GET /api/health`.

## Docker y Hostinger VPS

```sh
docker build -t steve-barber-shop-backend .
```

El Dockerfile usa Python 3.13 y Uvicorn, escucha en 3000 y ejecuta como usuario sin privilegios. Conecta un volumen persistente a `/app/data` y configura las variables de `.env.example`. El Compose del repositorio frontend levanta Vue/Nginx, este backend y Caddy con HTTPS.

No expongas la API directamente al público: Nginx envía `/api` al backend por la red interna. Utiliza una sola instancia sobre SQLite local; no despliegues réplicas con archivos de datos independientes.

## Compatibilidad y datos

Las tablas, IDs, permisos, hashes PBKDF2 con sal y el formato de las cookies son compatibles con la versión anterior de Node.js. Se conserva el registro de migraciones `node_migrations`, evitando volver a aplicar migraciones sobre volúmenes existentes. El contenedor mantiene UID 1000 para poder usar el volumen de la versión anterior.

Antes de actualizar, detén las escrituras y realiza una copia consistente de SQLite. Conserva el volumen `barber_data`; no uses `docker compose down -v`. No se incluyen citas ni claves en GitHub.

Para importar datos a un destino vacío con el backend detenido:

```sh
DATABASE_PATH=./data/barber.sqlite .venv/bin/python scripts/import_data.py /ruta/a/base-anterior.sqlite
```

## Pruebas

```sh
.venv/bin/python -m pytest -q
```

Usan bases temporales y verifican reservas, concurrencia, cancelaciones, validación, sesiones, privacidad, permisos, historial y compatibilidad con la versión anterior.
