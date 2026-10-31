# Auditoría de sistema_planillas (2026-10-31, 2.ª pasada)

Alcance: `app/` (backend), `index.html` (6.400 líneas; revisado por sondeo en autenticación, red y `innerHTML`), `run.py`, despliegue.
Método: lectura de fuente + ejecución **dentro del sandbox WSL2/bubblewrap** (sin red, objetivo de solo lectura, entorno vacío; toolchain `/opt/sbx-toolchains/planillas`): pytest, servidor gunicorn real por socket Unix y bandit. `pip-audit` fuera del sandbox (necesita red; solo consulta `requirements.txt`).

## Resultado de la verificación

| Prueba | Resultado |
|---|---|
| `pytest` (27 pruebas: sesión, roles, validación/XSS, usuarios, recuperación, correo) | 27 pasan |
| `tests/smoke_gunicorn.py` (gunicorn 2 workers, HTTP real) | 17/17 |
| bandit (app + run.py) | 0 hallazgos (3 corregidos) |
| pip-audit | sin vulnerabilidades conocidas |
| Cobertura de rutas | las 25 rutas exigen sesión, salvo `/`, `/healthz`, login, logout, sesión y recuperación (por diseño) |
| `node --check` del JavaScript | válido |

No probado: navegador real (flujo visual de modales), Railway, y el envío real con EmailJS (probado con la API simulada).

## Escenario de examen (20 estudiantes, 100 empleados ficticios) — verificación adicional

| Prueba | Resultado |
|---|---|
| pytest (36) en sandbox WSL | 36 pasan |
| Recorrido en **Edge real** (`tests/e2e/recorrido.js`): login, 12 pantallas, 100 empleados (78 locales/22 extranjeros), planilla, asistencia, baja de punta a punta, recarga, cambio de estudiante en el mismo equipo, usuarios, Mi Perfil, recuperación | 41/41, 0 errores de JavaScript |
| Carga: 20 estudiantes simultáneos desde la misma IP × 8 rondas contra gunicorn (sandbox) | 860 peticiones, 0 errores, p95 38 ms (login p95 333 ms en el pico) |
| bandit app + run.py | 0 hallazgos (tools/: solo `random` intencional para datos ficticios) |

Defectos hallados y corregidos al probar con la interfaz real: (1) la baja enviaba el total como texto (`Q 12,345.67`) y la validación numérica nueva lo rechazaba con 400; (2) tras cambiar de estudiante en el mismo equipo se veía un instante el estado del anterior (la pantalla se destapaba antes de cargar los datos); (3) los estudiantes no podían desbloquear la edición de bajas porque la clave exigida era la del administrador: ahora confirman con su propia contraseña.

## Hallazgos (esta pasada y la anterior) y corrección

| Sev. | Hallazgo | Corrección |
|---|---|---|
| Crítica | API sin autenticación; reseteo de contraseña del admin sin sesión | Sesión firmada + roles por ruta; verificación del usuario en BD en cada petición |
| Crítica | **Login de respaldo en el navegador** (`admin123` en el HTML y `localStorage`) | Eliminado; sin servidor no hay acceso. `gt_usuarios` se borra del navegador al cargar |
| Alta | **"Olvidé contraseña" no funcionaba**: OTP generado y validado en el cliente, correo del admin fijo, sin cambiar ninguna contraseña, notificación tapada por el modal | Flujo en servidor: código de 6 dígitos (CSPRNG, 10 min, 5 intentos, un solo uso, solo HMAC en BD), envío por la API de EmailJS desde el servidor, nueva contraseña con política, respuesta uniforme (sin enumerar cuentas), límites por IP y por correo |
| Alta | Usuarios creados/editados/borrados solo en `localStorage` (no podían iniciar sesión en el servidor) | CRUD de usuarios en la API (solo ADMIN); sin columna de contraseñas en pantalla |
| Alta | Clave de "ediciones/bajas" (`admin123`) comprobada en el cliente | `/api/autorizar` verifica en el servidor, con límite de intentos |
| Alta | Credenciales sembradas; `SECRET_KEY` fija; XSS almacenado | Sin usuarios por defecto, `SECRET_KEY` obligatoria, validación servidor + `esc()` en 48 interpolaciones del cliente |
| Media | Sesiones sobrevivían a cambio de contraseña, desactivación o cambio de rol | Marca de contraseña en la sesión + rol/estado leídos de la BD |
| Media | Public Key y Service ID de EmailJS en el HTML | Eliminados del frontend y del script de terceros; **rotar las claves** (ver DEPLOY_RAILWAY.md) |
| Baja | bandit: bind `0.0.0.0` en desarrollo, clave de desarrollo fija, `urlopen` | `HOST` por defecto 127.0.0.1, clave aleatoria en desarrollo, URL constante https |
| Baja | Dependencias transitivas sin fijar | `requirements.txt` completo con versiones fijas |

## Mapa ISO/IEC 25010

| Característica | Qué se hizo |
|---|---|
| Seguridad (confidencialidad, integridad, autenticidad, no repudio) | Autenticación y autorización en servidor, hash de contraseñas, OTP con HMAC, cookies HttpOnly/Secure/SameSite, cabeceras, validación, rate limiting, errores sin detalle, bitácora de restablecimientos en el log |
| Fiabilidad (tolerancia a fallos, recuperabilidad) | Volume para SQLite, `timeout` de BD, healthcheck, reinicio ON_FAILURE, correo asíncrono que no bloquea ni rompe la solicitud |
| Compatibilidad / Portabilidad | Dependencias fijadas, variables de entorno, sin rutas absolutas, Procfile + railway.json, Python fijado |
| Mantenibilidad (modularidad, analizabilidad, capacidad de prueba) | `correo.py` aislado, 27 pruebas automáticas, sin código duplicado de rutas, pruebas de humo |
| Usabilidad (protección frente a errores, accesibilidad) | Mensajes claros de login/recuperación, autocompletado correcto (`one-time-code`, `new-password`), botones deshabilitados durante la petición, sesión que se restaura al recargar |
| Eficiencia de desempeño | 2 workers × 2 hilos; las consultas de sesión son de una fila indexada |
| Adecuación funcional | Corregidos el departamento mostrado, la baja con DPI con guiones y el cierre de sesión en servidor |

## Riesgos residuales (decisión o rediseño pendiente)

1. **Datos de empleados, departamentos y asistencia aún se cachean en `localStorage`** y varias pantallas leen de ahí (la asistencia solo se guarda ahí). Quedan en el navegador tras cerrar sesión; no se limpian para no perder datos que nunca llegaron al servidor. Siguiente paso: llevar todo el modelo a la API y entonces vaciar `localStorage` al cerrar sesión.
2. **`innerHTML` con otros campos sin escapar** (se escaparon los de texto de empleados, usuarios y departamentos; no se auditó cada uno de los 47 usos) y sin CSP: Tailwind CDN, Font Awesome y Google Fonts obligan a `unsafe-inline`; sin SRI en las etiquetas de CDN.
3. **Limitadores en memoria por proceso** (límite efectivo ×2 con 2 workers) y CSRF cubierto solo por SameSite=Lax + JSON.
4. **SQLite** en un Volume: válido para una réplica; para varias, PostgreSQL.
5. El correo de recuperación depende de que EmailJS permita su API desde servidor (opción de la cuenta) y de que cada usuario tenga un correo único registrado.
6. Reglas de planilla (IGSS 4,83 %, bono Q250, ISR 5 %/7 %, deducción Q48.000): sin verificar contra la normativa vigente; `aplica_igss`, `aplica_bono` y `tipo_pago` se guardan pero no intervienen en el cálculo.
7. El repositorio git está en `Proyectos/` (varios proyectos, sin commits): no hagas `git add .` desde la raíz. `instance/sistema_planillas.db` local contiene hashes de las credenciales de demostración y sigue sin subirse (`.gitignore`).
