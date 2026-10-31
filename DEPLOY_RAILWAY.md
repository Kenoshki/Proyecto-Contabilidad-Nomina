# Despliegue en Railway

1. **Raíz del servicio**: este directorio (`sistema_planillas`) debe ser la raíz. El repositorio git
   está en `Proyectos/` y contiene otros proyectos; usa `railway up` desde esta carpeta o define
   *Root Directory* = `sistema_planillas` si conectas el repositorio.
2. **Volume** (obligatorio, SQLite se borra en cada despliegue sin él): Service → Volumes → montar en `/data`.
3. **Variables** del servicio:
   | Variable | Valor |
   |---|---|
   | `SECRET_KEY` | cadena aleatoria de 64 hex (`python -c "import secrets; print(secrets.token_hex(32))"`) |
   | `ADMIN_USERNAME` | `admin` (o el que prefieras) |
   | `ADMIN_PASSWORD` | contraseña fuerte, ≥ 12 caracteres |
   | `ADMIN_EMAIL` | correo real del administrador (recibe el código de recuperación) |
   | `DATABASE_PATH` | `/data/sistema_planillas.db` |
   | `PROXY_HOPS` | `1` |
   | `EMAILJS_SERVICE_ID`, `EMAILJS_TEMPLATE_OTP`, `EMAILJS_PUBLIC_KEY`, `EMAILJS_PRIVATE_KEY` | de tu cuenta de EmailJS (ver abajo) |
   No definas `SEED_DEMO_DATA` ni `FLASK_DEBUG` en producción.
4. Despliega; Railway usa `Procfile`/`railway.json` (gunicorn) y comprueba `/healthz`. Python 3.14 (`.python-version`);
   si el constructor de Railway no lo ofreciera, usa 3.13.
5. **Después del primer arranque**: entra con el administrador, crea los demás usuarios en *Usuarios*, y comprueba que
   `GET /api/empleados` sin sesión devuelve 401.
6. No subas `instance/sistema_planillas.db` local: contiene hashes de las credenciales de demostración.

## Modo examen / demostración (20 estudiantes, 100 empleados ficticios)

1. Generar (una vez, en tu equipo): `python tools/generar_estudiantes.py 20`
   - Crea `app/demo_data/estudiantes.json` (solo **hashes**, se despliega) y
     `tools/salida/credenciales_estudiantes.csv` (**contraseñas en claro**: entrégalas a los estudiantes y **no lo subas**;
     está en `.gitignore`, `railway up` lo respeta).
   - Los 100 empleados ya están en `app/demo_data/demo.json` (`python tools/generar_datos_demo.py` los regenera igual).
2. Variables adicionales en Railway:
   | Variable | Valor |
   |---|---|
   | `SEED_ESTUDIANTES` | `1` (crea `est01`…`est20`, rol RRHH, al arrancar) |
   | `DEMO_DATA` | `1` (el servidor ofrece los 100 empleados, 6 ex-empleados y horas extra) |
   | `LOGIN_MAX_INTENTOS` | `10` (margen para errores de digitación) |
   No definas `SEED_DEMO_DATA` (usuarios con contraseñas conocidas).
3. Cómo se comporta: cada estudiante, al iniciar sesión, recibe su propio conjunto limpio en su navegador; sus cambios
   (altas, asistencia, bajas) se conservan al recargar y **no** los ven los demás. Si otro estudiante entra desde el mismo
   equipo, recibe un conjunto limpio. Las bajas sí quedan registradas en la base del servidor.
4. Reautenticación de ediciones/bajas: los estudiantes (RRHH) confirman con **su propia contraseña**; no necesitan la del admin.
5. Antes del examen: `node tests/e2e/recorrido.js` (requiere `npm install` y `python tests/e2e/servidor.py`) y
   `python tests/carga_gunicorn.py 20 8` (en Linux/WSL) para repetir las verificaciones.
6. Al terminar: borra el servicio y rota la contraseña del admin y las claves de EmailJS.

## "¿Olvidaste tu contraseña?" (código por correo)

Flujo: el usuario escribe el correo de su cuenta → el servidor genera un código de 6 dígitos (vigente 10 min, 5 intentos,
un solo uso, guardado solo como HMAC) y lo envía → el usuario ingresa código + nueva contraseña. Al cambiar la contraseña se
cierran todas sus sesiones abiertas. La respuesta es la misma exista o no el correo.

Configuración de EmailJS (el envío ahora lo hace el servidor, no el navegador):
1. Account → Security → activar **Allow EmailJS API for non-browser applications**.
2. Copia *Service ID*, *Public Key* y *Private Key* a las variables de arriba.
3. La plantilla (`EMAILJS_TEMPLATE_OTP`) debe tener destinatario `{{to_email}}` y mostrar `{{otp_code}}` y `{{tiempo_limite}}`.
4. Las claves que estaban escritas en el HTML anterior (Public Key y Service ID) quedaron expuestas en el repositorio y en
   cualquier navegador que cargó la página: **genera una Public/Private Key nueva** en EmailJS y úsala solo en Railway.

Sin proveedor configurado el servidor lo registra en el log y no envía nada (la solicitud sigue respondiendo 200).

Notas: el servicio usa 2 workers con SQLite (válido para esta carga). Los limitadores de intentos son por proceso, así que
el límite efectivo es ×2. Para escalar a más réplicas migrar a PostgreSQL de Railway y mover los limitadores a la base.
