# Steve Barber Shop — FastAPI Backend

API independiente en **Python 3.13 y FastAPI**, con SQLite persistente. Sirve las reservas, disponibilidad, altas de barberos, permisos, sesiones y resumen del manager. El frontend Vue está en el repositorio `steve-barber-shop-frontend`.

## Desarrollo

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# Define la ruta de SQLite y el origen público,
# DATABASE_PATH=./data/barber.sqlite y PUBLIC_ORIGIN=http://localhost:5173
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 3000 --env-file .env --reload
```

Utiliza el origen exacto que muestra Vite, incluido puerto y esquema. En producción es `https://stevesbarbershopny.com`. La sesión usa cookies HttpOnly, Secure y SameSite=Lax; el dominio público debe tener HTTPS. Las credenciales se guardan en SQLite como hashes PBKDF2 con sal; las variables STAFF_PIN y BARBER_PIN ya no intervienen en el inicio de sesión.

Documentación de API: `/docs`. Salud del servicio: `GET /api/health`.

## Docker y Hostinger VPS

```sh
docker build -t steve-barber-shop-backend .
```

El Dockerfile usa Python 3.13 y Uvicorn, escucha en 83 y ejecuta como usuario sin privilegios. Conecta un volumen persistente a `/app/data` y configura las variables de `.env.example`. El Compose del repositorio frontend levanta Vue/Nginx, este backend y Caddy con HTTPS.

En EasyPanel configura el puerto interno del backend en **83**. Para desarrollo local, el comando anterior mantiene el puerto 3000.

No expongas la API directamente al público: Nginx envía `/api` al backend por la red interna. Utiliza una sola instancia sobre SQLite local; no despliegues réplicas con archivos de datos independientes.

## Compatibilidad y datos

Se conservan las tablas, IDs, permisos y hashes PBKDF2 con sal de la versión anterior. La migración de credenciales requiere iniciar sesión de nuevo. Se conserva el registro de migraciones `node_migrations`, evitando volver a aplicar migraciones sobre volúmenes existentes. El contenedor mantiene UID 1000 para poder usar el volumen de la versión anterior.

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

## Carta actualizada

`app/catalog.json` contiene los 12 servicios y precios de la carta. Sus duraciones son provisionales: cortes de 30 minutos, retoques de 15 y paquetes de 45–60. Se conservan los IDs `signature`, `beard` y `complete` para mantener las referencias existentes. Las citas anteriores conservan su duración almacenada. Los barberos originales sin configuración específica pueden realizar la carta completa; si el manager ya guardó permisos por persona, se respetan y los nuevos servicios se habilitan desde Equipo y servicios.

## Equipo

El equipo público es David, Steve, Joey y Mike. Los tres primeros conservan sus IDs internos anteriores para no alterar reservas ni permisos. Las imágenes son avatares de ejemplo hasta contar con fotografías propias.

## Accesos solicitados por el propietario

La primera migración a `staff_credentials` guarda las claves solicitadas: manager `steveadmin`, David `stevedavid`, Steve `stevesteve`, Joey `stevejosey` y Mike `stevemike`. Se importan las credenciales de barberos agregados anteriormente. Solo se inicializan cuentas que todavía no tienen credenciales; reiniciar o desplegar no restablece contraseñas. Las variables antiguas de EasyPanel no sobrescriben SQLite.

En `/staff`, el manager abre **Equipo y servicios**, escribe una nueva contraseña (8–64 caracteres) en la tarjeta del barbero y pulsa **Cambiar contraseña**. Solo el manager puede hacerlo. El cambio guarda un hash nuevo y revoca las sesiones de ese barbero. La clave anterior deja de funcionar de inmediato. La API nunca devuelve hashes ni contraseñas.

En EasyPanel configura un montaje persistente para `/app/data`, donde está `barber.sqlite`; conservar ese volumen es necesario para mantener claves, reservas y permisos entre despliegues.

## Horarios de reserva

Lunes a sábado: 08:30–19:00. Domingo: 09:00–17:00. Todos en hora de Nueva York. Los turnos se ofrecen cada 30 minutos desde la apertura y el último inicio es el turno de esa secuencia que permite completar la duración del servicio antes del cierre. La API de disponibilidad y el guardado aplican la misma regla. Se excluyen horarios pasados, ocupados y cualquier turno que termine después del cierre.

## Clientes persistentes

Cada reserva confirmada crea o actualiza una fila en `customers` por correo normalizado (sin espacios exteriores y en minúsculas), con nombre, teléfono y fechas de creación y actualización. `appointments.customer_id` vincula las citas a esa ficha; los datos originales de cada cita se conservan. El guardado es una sola transacción: una reserva rechazada no crea clientes. La migración importa los contactos de citas existentes y el manager consulta estas fichas en Clientes. Una visita anónima a la web no registra datos de contacto; el registro ocurre al reservar.

## Concurrencia manual del local

`GET /api/busyness` devuelve el porcentaje público y la fecha de actualización. `POST /api/staff/busyness` permite al manager o cualquier barbero autenticado guardar un entero de 0 a 100. El medidor es compartido: el último guardado prevalece. SQLite conserva el porcentaje y quién lo actualizó; la respuesta pública no expone la identidad. 0–33% es poco ocupado, 34–66% moderado y 67–100% muy ocupado. Hasta el primer guardado se muestra sin actualizar. El frontend lee el valor una vez al abrir la página, sin consultas periódicas ni al volver a la ventana. Mover el control prepara un borrador; solo Aceptar guarda y actualiza el medidor. Los visitantes ven el valor vigente al abrir o recargar la web. Se muestra la fecha y hora del reporte en Nueva York. Es un reporte manual del equipo; no se calcula con Google ni con reservas.
