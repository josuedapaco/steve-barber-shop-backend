# Steve Barber Shop — Backend

Repositorio independiente de la API Node.js 24 + TypeScript + Drizzle + SQLite. Incluye reservas, disponibilidad, altas de barberos, permisos por servicio, acceso del personal y resumen de manager. No contiene código de la interfaz.

## Ejecutar

```sh
npm ci
npm run build
cp .env.example .env
# Configura las claves y una ruta DATABASE_PATH escribible y persistente.
npm start
```

Para ejecutar fuera de Docker cambia `DATABASE_PATH` a una ruta local, por ejemplo `./data/barber.sqlite`. El manager necesita `STAFF_PIN` de al menos 12 caracteres; los perfiles originales usan `BARBER_PIN_MARCO`, `BARBER_PIN_JAMES` y `BARBER_PIN_ANDRE`. Para desarrollo con Vite configura `PUBLIC_ORIGIN=http://localhost:5173` según el origen exacto utilizado en el navegador. En producción usa `https://stevesbarbershopny.com`.

`npm test` comprueba reservas, concurrencia, cancelaciones, altas, privacidad y permisos usando SQLite temporal. No modifica datos de producción.

## Docker

```sh
docker build -t steve-barber-shop-backend .
```

El contenedor ejecuta como usuario sin privilegios y escucha en 3000. Requiere variables privadas y un volumen persistente en `/app/data`. No expongas el puerto al público: el proxy del frontend envía las rutas `/api`. El Compose del repositorio frontend integra ambos servicios y Caddy para HTTPS.

SQLite debe usarse con una sola instancia backend sobre un disco persistente local. Las migraciones de `drizzle/` se aplican en una transacción y se registran en `node_migrations`. Las reservas y sus franjas ocupadas se guardan en una transacción para evitar solapamientos.

## Rutas

- `GET /api/health`: salud del servicio.
- `GET /api/team`, `GET /api/availability`, `POST /api/appointments`: reservas públicas.
- `POST /api/staff/login`, `POST /api/staff/logout`: sesión mediante cookie HttpOnly, Secure y SameSite.
- `GET /api/appointments`, `POST /api/staff/status`: agenda y estados según el rol.
- `GET /api/staff/dashboard`, `GET/POST /api/staff/services`, `POST /api/staff/team`: administración de manager.

La API rechaza escrituras con un encabezado Origin distinto de PUBLIC_ORIGIN, limita el tamaño de las peticiones y mantiene las sesiones de cada petición aisladas. Los códigos de las altas se guardan como hash PBKDF2 con sal. Los códigos originales y la clave de manager se reciben exclusivamente del entorno.

Los datos locales y las claves no se incluyen en GitHub ni en las imágenes. Realiza una copia consistente de SQLite antes de actualizar y conserva el volumen. Para migrar las citas existentes, exporta/importa la base explícitamente con la aplicación detenida; no reemplaces una base de producción sin revisar su contenido.

Para importar una base anterior a un destino vacío: `DATABASE_PATH=./data/barber.sqlite node scripts/import-local-data.mjs /ruta/a/base-anterior.sqlite`. Ejecuta la importación con el backend detenido. No modifica el origen y rechaza un destino con datos.
