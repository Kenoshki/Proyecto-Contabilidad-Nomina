import hashlib
import hmac
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from app import correo
from app.guatemala_rules import calcular_planilla_empleado
from app.db import init_db, get_db_connection

logger = logging.getLogger(__name__)

PATRON_DOCUMENTO = re.compile(r'^[A-Za-z0-9 -]{3,30}$')
PREFIJOS_FOTO = ('https://', 'data:image/png;base64,', 'data:image/jpeg;base64,',
                 'data:image/webp;base64,', 'data:image/gif;base64,')
MAX_FOTO = 2_000_000
INTENTOS_LOGIN_MAX = 5  # configurable con LOGIN_MAX_INTENTOS
VENTANA_LOGIN_SEG = 15 * 60
ROLES = ('ADMIN', 'RRHH', 'OPERADOR')
MODULOS = ('dashboard', 'empleados', 'extranjeros', 'locales', 'directorio', 'planillas', 'asistencia',
           'departamentos', 'reportes', 'ley-gt', 'bajas', 'ex-empleados')
PATRON_USUARIO = re.compile(r'^[A-Za-z0-9._-]{3,30}$')
PATRON_CORREO = re.compile(r'^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$')
VIGENCIA_CODIGO_MIN = 10
INTENTOS_CODIGO_MAX = 5
# Hash de relleno para igualar el tiempo de respuesta cuando el usuario no existe
HASH_RELLENO = generate_password_hash('relleno-sin-uso')


class ErrorValidacion(ValueError):
    """Entrada inválida del cliente: se responde 400 con el mensaje."""


def _texto(valor, campo, maximo=200, obligatorio=False, defecto=None):
    # El frontend pinta estos datos con innerHTML: se rechazan caracteres de marcado
    if valor is None or valor == '':
        if obligatorio:
            raise ErrorValidacion(f"El campo {campo} es obligatorio")
        return defecto
    if not isinstance(valor, str):
        raise ErrorValidacion(f"El campo {campo} no es válido")
    valor = valor.strip()
    if len(valor) > maximo or any(c in valor for c in '<>`'):
        raise ErrorValidacion(f"El campo {campo} no es válido")
    if obligatorio and not valor:
        raise ErrorValidacion(f"El campo {campo} es obligatorio")
    return valor


def _numero(valor, campo, minimo=0.0, maximo=10_000_000.0, defecto=0.0):
    if valor is None or valor == '':
        return defecto
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErrorValidacion(f"El campo {campo} debe ser numérico")
    if not math.isfinite(numero) or numero < minimo or numero > maximo:
        raise ErrorValidacion(f"El campo {campo} está fuera de rango")
    return numero


def _monto(valor, campo, maximo=100_000_000.0):
    """Acepta números o el texto mostrado en pantalla (p. ej. 'Q 12,345.67')."""
    if isinstance(valor, str):
        limpio = re.sub(r'[^0-9.\-]', '', valor)
        if not re.fullmatch(r'-?\d+(\.\d+)?', limpio or ''):
            raise ErrorValidacion(f"El campo {campo} debe ser un monto")
        valor = limpio
    return _numero(valor, campo, 0, maximo)


def _foto_opcional(valor):
    # En las bajas la foto es accesoria: si no es válida simplemente no se conserva
    try:
        return _foto(valor)
    except ErrorValidacion:
        return None


def _foto(valor):
    if not valor:
        return None
    if not isinstance(valor, str) or len(valor) > MAX_FOTO or not valor.startswith(PREFIJOS_FOTO):
        raise ErrorValidacion("La foto debe ser una URL https o una imagen png/jpeg/webp/gif")
    if any(c in valor for c in '"\'<> '):
        raise ErrorValidacion("La foto no es válida")
    return valor


def _validar_password(password, username=''):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise ErrorValidacion("La contraseña debe tener entre 10 y 128 caracteres")
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise ErrorValidacion("La contraseña debe combinar letras y números")
    if username and password.lower() == username.lower():
        raise ErrorValidacion("La contraseña no puede ser igual al usuario")
    return password


def _correo(valor, obligatorio=False):
    valor = _texto(valor, 'correo', 120, obligatorio=obligatorio)
    if valor and not PATRON_CORREO.match(valor):
        raise ErrorValidacion("El correo electrónico no es válido")
    return valor.lower() if valor else valor


def _permisos(valor):
    if valor is None:
        return ''
    if not isinstance(valor, list) or any(p not in MODULOS for p in valor):
        raise ErrorValidacion("Los permisos no son válidos")
    return ','.join(dict.fromkeys(valor))


def _marca_password(hash_password):
    # Cambia cuando se cambia la contraseña: invalida las sesiones abiertas
    return hashlib.sha256(hash_password.encode('utf-8')).hexdigest()[:16]


def create_app():
    app = Flask(__name__)

    modo_debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1']
    secret_key = (os.environ.get('SECRET_KEY') or '').strip()
    if not secret_key:
        if not modo_debug:
            # Diagnóstico: solo NOMBRES de variables (nunca valores) para detectar errores de escritura o de servicio
            parecidas = sorted(n for n in os.environ if 'SECRET' in n.upper() or 'KEY' in n.upper())
            esperadas = {n: (n in os.environ) for n in ('SECRET_KEY', 'ADMIN_PASSWORD', 'ADMIN_EMAIL', 'DATABASE_PATH')}
            raise RuntimeError(
                "SECRET_KEY es obligatoria fuera de modo desarrollo (FLASK_DEBUG=1). "
                f"Variables esperadas presentes: {esperadas}. Nombres con SECRET/KEY vistos: {parecidas}. "
                "Defínala en Variables del MISMO servicio y entorno que se despliega y vuelva a desplegar.")
        secret_key = secrets.token_hex(32)  # solo desarrollo: las sesiones no sobreviven a un reinicio
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=not modo_debug,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=4 * 1024 * 1024,
    )

    # Railway termina TLS en su proxy: se confía en N saltos para ver la IP y el esquema reales
    saltos_proxy = int(os.environ.get('PROXY_HOPS', '1'))
    if saltos_proxy > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=saltos_proxy, x_proto=saltos_proxy, x_host=saltos_proxy)

    # Inicializar la base de datos dentro del contexto de aplicación
    with app.app_context():
        init_db()

    # =========================================================
    # SEGURIDAD: SESIÓN, ROLES Y CABECERAS
    # =========================================================
    def usuario_en_sesion():
        """Usuario vigente de la sesión, o None si no hay sesión, fue desactivado o cambió su contraseña."""
        if 'username' not in session:
            return None
        conn = get_db_connection()
        try:
            fila = conn.execute("SELECT * FROM usuario WHERE username = ? AND activo = 1",
                                (session['username'],)).fetchone()
        finally:
            conn.close()
        if not fila or not hmac.compare_digest(session.get('pv', ''), _marca_password(fila['password'])):
            session.clear()
            return None
        return fila

    def requiere_sesion(*roles):
        def decorador(vista):
            @wraps(vista)
            def envoltura(*args, **kwargs):
                usuario = usuario_en_sesion()
                if usuario is None:
                    return jsonify({"status": "error", "message": "Sesión requerida"}), 401
                if roles and usuario['rol'] not in roles:
                    return jsonify({"status": "error", "message": "No tiene permiso para esta operación"}), 403
                return vista(*args, **kwargs)
            return envoltura
        return decorador

    intentos_login = {}

    def login_bloqueado(clave):
        ahora = time.time()
        recientes = [t for t in intentos_login.get(clave, []) if ahora - t < VENTANA_LOGIN_SEG]
        intentos_login[clave] = recientes
        return len(recientes) >= int(os.environ.get('LOGIN_MAX_INTENTOS', INTENTOS_LOGIN_MAX))

    eventos_limitados = {}

    def excede_limite(clave, maximo, ventana_seg):
        """Cuenta el evento y devuelve True si ya se superó el máximo en la ventana."""
        ahora = time.time()
        recientes = [t for t in eventos_limitados.get(clave, []) if ahora - t < ventana_seg]
        excedido = len(recientes) >= maximo
        recientes.append(ahora)
        eventos_limitados[clave] = recientes
        return excedido

    @app.after_request
    def cabeceras_seguridad(resp):
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        if request.path.startswith('/api/'):
            resp.headers['Cache-Control'] = 'no-store'
        return resp

    # --- SALUD (Railway healthcheck, sin datos) ---
    @app.route('/healthz')
    def salud():
        return jsonify({"status": "ok"}), 200

    # --- RUTA PRINCIPAL ---
    @app.route('/', methods=['GET', 'POST'])
    def inicio():
        resultado = None
        if request.method == 'POST':
            try:
                nombre = _texto(request.form.get('nombre'), 'nombre', 100, defecto='')
                departamento = _texto(request.form.get('departamento'), 'departamento', 100, defecto='')
                sueldo = _numero(request.form.get('sueldo'), 'sueldo')
                dias = int(_numero(request.form.get('dias'), 'dias', 0, 31, 30))
                moneda = request.form.get('moneda')
                tipo_cambio = _numero(request.form.get('tipo_cambio'), 'tipo_cambio', 0.01, 1000, 7.80)
            except ErrorValidacion as e:
                return jsonify({"status": "error", "message": str(e)}), 400

            es_dolares = (moneda == 'USD')
            calculos = calcular_planilla_empleado(sueldo, dias, es_dolares, tipo_cambio)

            resultado = {
                'nombre': nombre,
                'departamento': departamento,
                'moneda': moneda,
                'calculos': calculos
            }

        return render_template('index.html', resultado=resultado)

    # =========================================================
    # 1. API EMPLEADOS (OBTENER Y GUARDAR)
    # =========================================================
    @app.route('/api/empleados', methods=['GET'])
    @requiere_sesion()
    def obtener_empleados():
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.*, d.nombre as departamento
                FROM empleado e
                LEFT JOIN departamento d ON e.departamento_id = d.id
                WHERE e.estado = 'ACTIVO'
            """)
            empleados = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
        return jsonify(empleados), 200

    def formatear_telefono(numero):
        if not numero:
            return ""
        digitos = ''.join(filter(str.isdigit, str(numero)))[:8]
        if len(digitos) > 4:
            return f"{digitos[:4]}-{digitos[4:]}"
        return digitos

    @app.route('/api/empleados', methods=['POST'])
    @requiere_sesion('ADMIN', 'RRHH')
    def guardar_empleado():
        data = request.get_json(silent=True) or {}
        dpi = data.get('dpi')
        if not dpi:
            return jsonify({"status": "error", "message": "El DPI es obligatorio"}), 400
        if not isinstance(dpi, str) or not PATRON_DOCUMENTO.match(dpi):
            raise ErrorValidacion("El DPI/Pasaporte no es válido")

        valores = (
            dpi,
            _texto(data.get('fecha'), 'fecha', 20, obligatorio=True),
            _texto(data.get('nombre'), 'nombre', 120, obligatorio=True),
            _texto(data.get('direccion'), 'direccion', 250),
            formatear_telefono(data.get('telefono')),
            formatear_telefono(data.get('celular')),
            _texto(data.get('nit'), 'nit', 20),
            _texto(data.get('senales'), 'senales', 200),
            _texto(data.get('enfermedad'), 'enfermedad', 200),
            _texto(data.get('empresa'), 'empresa', 120, defecto='TECNIMARKET S.A. DE GUATEMALA'),
        )
        resto = (
            _texto(data.get('cargo'), 'cargo', 120, obligatorio=True),
            _texto(data.get('tipoOrigen'), 'tipoOrigen', 20, defecto='LOCAL'),
            _texto(data.get('pais'), 'pais', 60, defecto='Guatemala'),
            _texto(data.get('visa'), 'visa', 60),
            _texto(data.get('moneda'), 'moneda', 3, defecto='GTQ'),
            _numero(data.get('sueldo'), 'sueldo'),
            _texto(data.get('tipoPago'), 'tipoPago', 30, defecto='Mensual'),
            1 if data.get('aplicaIgss') else 0,
            1 if data.get('aplicaBono') else 0,
            1 if data.get('aplicaIsr') else 0,
            _texto(data.get('estadoCivil'), 'estadoCivil', 30),
            int(_numero(data.get('hijos'), 'hijos', 0, 30, 0)),
            _texto(data.get('conyuge'), 'conyuge', 120),
            formatear_telefono(data.get('telConyuge')),
            _foto(data.get('foto')),
        )

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Buscar ID del departamento por su nombre
            cursor.execute("SELECT id FROM departamento WHERE nombre = ?", (data.get('departamento'),))
            depto_row = cursor.fetchone()
            depto_id = depto_row['id'] if depto_row else None

            cursor.execute("""
                INSERT INTO empleado (
                    dpi, fecha_ingreso, nombre, direccion,
                    telefono, celular, nit, senales, enfermedad, empresa,
                    departamento_id, cargo, tipo_origen, pais, visa, moneda,
                    sueldo_base, tipo_pago, aplica_igss, aplica_bono, aplica_isr,
                    estado_civil, hijos, conyuge, tel_conyuge, foto, estado
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVO')
                ON CONFLICT(dpi) DO UPDATE SET
                    fecha_ingreso=excluded.fecha_ingreso,
                    nombre=excluded.nombre,
                    direccion=excluded.direccion,
                    telefono=excluded.telefono,
                    celular=excluded.celular,
                    nit=excluded.nit,
                    senales=excluded.senales,
                    enfermedad=excluded.enfermedad,
                    departamento_id=excluded.departamento_id,
                    cargo=excluded.cargo,
                    tipo_origen=excluded.tipo_origen,
                    pais=excluded.pais,
                    visa=excluded.visa,
                    moneda=excluded.moneda,
                    sueldo_base=excluded.sueldo_base,
                    tipo_pago=excluded.tipo_pago,
                    aplica_igss=excluded.aplica_igss,
                    aplica_bono=excluded.aplica_bono,
                    aplica_isr=excluded.aplica_isr,
                    estado_civil=excluded.estado_civil,
                    hijos=excluded.hijos,
                    conyuge=excluded.conyuge,
                    tel_conyuge=excluded.tel_conyuge,
                    foto=excluded.foto
            """, valores + (depto_id,) + resto)
            conn.commit()
            return jsonify({"status": "success", "message": "Empleado guardado en Base de Datos"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================
    # 2. API DEPARTAMENTOS
    # =========================================================
    @app.route('/api/departamentos', methods=['GET'])
    @requiere_sesion()
    def obtener_departamentos():
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM departamento")
            deptos = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
        return jsonify(deptos), 200

    @app.route('/api/departamentos', methods=['POST'])
    @requiere_sesion('ADMIN', 'RRHH')
    def agregar_departamento():
        data = request.get_json(silent=True) or {}
        codigo = _texto(data.get('codigo'), 'codigo', 20, obligatorio=True)
        nombre = _texto(data.get('nombre'), 'nombre', 80, obligatorio=True)
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO departamento (codigo, nombre) VALUES (?, ?)", (codigo, nombre))
            conn.commit()
            return jsonify({"status": "success"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.route('/api/departamentos/<int:id>', methods=['DELETE'])
    @requiere_sesion('ADMIN', 'RRHH')
    def eliminar_departamento(id):
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM departamento WHERE id = ?", (id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"status": "success"}), 200

    # =========================================================
    # 1. API EMPLEADOS (BUSCAR)
    # =========================================================
    @app.route('/api/empleados/buscar', methods=['GET'])
    @requiere_sesion()
    def api_buscar_empleado():
        q = request.args.get('q', '').strip()[:100]
        if not q:
            return jsonify([]), 200

        termino_limpio = re.sub(r'[\s-]', '', q)
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # Si tiene 9 caracteres -> Búsqueda por Pasaporte / Extranjero
            if len(termino_limpio) == 9:
                cursor.execute("""
                    SELECT e.*, d.nombre as departamento
                    FROM empleado e
                    LEFT JOIN departamento d ON e.departamento_id = d.id
                    WHERE REPLACE(REPLACE(e.dpi, '-', ''), ' ', '') = ?
                      AND (UPPER(e.tipo_origen) = 'EXTRANJERO' OR e.pais != 'Guatemala')
                      AND e.estado = 'ACTIVO'
                """, (termino_limpio,))
                resultados = cursor.fetchall()
                if resultados:
                    return jsonify([dict(row) for row in resultados]), 200

            # Si tiene 13 dígitos -> Búsqueda por DPI / Local
            elif len(termino_limpio) == 13 and termino_limpio.isdigit():
                cursor.execute("""
                    SELECT e.*, d.nombre as departamento
                    FROM empleado e
                    LEFT JOIN departamento d ON e.departamento_id = d.id
                    WHERE REPLACE(REPLACE(e.dpi, '-', ''), ' ', '') = ?
                      AND (UPPER(e.tipo_origen) = 'LOCAL' OR e.pais = 'Guatemala')
                      AND e.estado = 'ACTIVO'
                """, (termino_limpio,))
                resultados = cursor.fetchall()
                if resultados:
                    return jsonify([dict(row) for row in resultados]), 200

            # Búsqueda general (por coincidencia parcial en nombre, DPI/Pasaporte o NIT)
            param = f"%{termino_limpio.lower()}%"
            cursor.execute("""
                SELECT e.*, d.nombre as departamento
                FROM empleado e
                LEFT JOIN departamento d ON e.departamento_id = d.id
                WHERE (
                    LOWER(REPLACE(REPLACE(e.dpi, '-', ''), ' ', '')) LIKE ? OR
                    LOWER(e.nombre) LIKE ? OR
                    LOWER(REPLACE(REPLACE(e.nit, '-', ''), ' ', '')) LIKE ?
                )
                AND e.estado = 'ACTIVO'
            """, (param, f"%{q.lower()}%", param))
            resultados = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
        return jsonify(resultados), 200

    # =========================================================
    # 3. API ASISTENCIA
    # =========================================================
    @app.route('/api/asistencia', methods=['GET'])
    @requiere_sesion()
    def obtener_asistencia():
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM asistencia")
            registros = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
        return jsonify(registros), 200

    @app.route('/api/asistencia', methods=['POST'])
    @requiere_sesion()
    def guardar_asistencia():
        data = request.get_json(silent=True)
        if not isinstance(data, list) or len(data) > 1000:
            raise ErrorValidacion("Se espera una lista de registros de asistencia (máximo 1000)")

        filas = []
        for item in data:
            if not isinstance(item, dict):
                raise ErrorValidacion("Registro de asistencia no válido")
            dpi = item.get('dpi')
            if not isinstance(dpi, str) or not PATRON_DOCUMENTO.match(dpi):
                raise ErrorValidacion("DPI de asistencia no válido")
            filas.append((
                dpi,
                _texto(item.get('fecha'), 'fecha', 20, obligatorio=True),
                _numero(item.get('horasExtra'), 'horasExtra', 0, 24),
                _numero(item.get('tarifa'), 'tarifa', 0, 100000),
                1 if item.get('aplicaPago') else 0,
                _numero(item.get('montoTotal'), 'montoTotal', 0, 1_000_000),
            ))

        conn = get_db_connection()
        try:
            conn.executemany("""
                INSERT INTO asistencia (
                    empleado_dpi, fecha, horas_extra, tarifa_extra, aplica_pago, total_extra
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, filas)
            conn.commit()
            return jsonify({"status": "success"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================
    # 4. API BAJAS Y EX-EMPLEADOS
    # =========================================================
    @app.route('/api/baja', methods=['POST'])
    @requiere_sesion('ADMIN', 'RRHH')
    def procesar_baja_empleado():
        data = request.get_json(silent=True) or {}
        raw_dpi = data.get('dpi', '')
        if not isinstance(raw_dpi, str):
            raise ErrorValidacion("El DPI no es válido")
        dpi = raw_dpi.replace(' ', '').replace('-', '')

        if not dpi:
            return jsonify({"status": "error", "message": "El DPI es requerido"}), 400
        if not PATRON_DOCUMENTO.match(dpi):
            raise ErrorValidacion("El DPI no es válido")

        valores = (
            dpi,
            _texto(data.get('codigo'), 'codigo', 40),
            _texto(data.get('nombre'), 'nombre', 120, obligatorio=True),
            _texto(data.get('departamento'), 'departamento', 80),
            _texto(data.get('cargo'), 'cargo', 120),
            _texto(data.get('causalSalida'), 'causalSalida', 120, obligatorio=True),
            _texto(data.get('fechaSalida'), 'fechaSalida', 20, obligatorio=True),
            _monto(data.get('montoLiquidado'), 'montoLiquidado'),
            _foto_opcional(data.get('foto')),
        )

        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO ex_empleado (
                    dpi, codigo, nombre, departamento, cargo,
                    causal_salida, fecha_salida, monto_liquidado, foto
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, valores)
            # El DPI puede estar guardado con guiones o espacios: se compara normalizado
            conn.execute(
                "DELETE FROM empleado WHERE REPLACE(REPLACE(dpi, '-', ''), ' ', '') = ?", (dpi,))
            conn.commit()
            return jsonify({"status": "success", "message": "Empleado trasladado a ex_empleado exitosamente"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.route('/api/ex-empleados', methods=['GET'])
    @requiere_sesion('ADMIN', 'RRHH')
    def obtener_ex_empleados():
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ex_empleado ORDER BY fecha_registro DESC")
            ex_empleados = [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
        return jsonify(ex_empleados), 200

    # API: ELIMINAR PERMANENTEMENTE UN EX-EMPLEADO DE LA BASE DE DATOS
    @app.route('/api/ex-empleados/<dpi>', methods=['DELETE'])
    @requiere_sesion('ADMIN')
    def eliminar_ex_empleado_db(dpi):
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM ex_empleado WHERE dpi = ?", (dpi,))
            conn.commit()
            return jsonify({"status": "success", "message": "Ex-empleado eliminado permanentemente de la BD"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================
    # 5. API USUARIOS Y AUTENTICACIÓN
    # =========================================================
    def _usuario_publico(fila):
        datos = dict(fila)
        datos.pop('password', None)
        datos.pop('pass_admin_auth', None)
        datos['permisos'] = [p for p in (datos.get('permisos') or '').split(',') if p]
        return datos

    @app.route('/api/sesion', methods=['GET'])
    def sesion_actual():
        usuario = usuario_en_sesion()
        if usuario is None:
            return jsonify({"status": "error", "message": "Sesión requerida"}), 401
        return jsonify({"status": "success", "usuario": _usuario_publico(usuario)}), 200

    @app.route('/api/login', methods=['POST'])
    def login_backend():
        data = request.get_json(silent=True) or {}
        username = data.get('username', '')
        password = data.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str):
            return jsonify({"status": "error", "message": "Credenciales incompletas"}), 400
        username = username.strip()
        password = password.strip()

        if not username or not password:
            return jsonify({"status": "error", "message": "Credenciales incompletas"}), 400

        clave = f"{request.remote_addr}|{username.lower()}"
        if login_bloqueado(clave):
            return jsonify({"status": "error", "message": "Demasiados intentos. Intente más tarde"}), 429

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuario WHERE username = ? AND activo = 1", (username,))
            user = cursor.fetchone()
        finally:
            conn.close()

        hash_guardado = user['password'] if user else HASH_RELLENO
        if check_password_hash(hash_guardado, password) and user:
            intentos_login.pop(clave, None)
            session.clear()
            session.permanent = True
            session['username'] = user['username']
            session['pv'] = _marca_password(user['password'])
            return jsonify({"status": "success", "usuario": _usuario_publico(user)}), 200

        intentos_login.setdefault(clave, []).append(time.time())
        return jsonify({"status": "error", "message": "Usuario o contraseña incorrectos"}), 401

    @app.route('/api/logout', methods=['POST'])
    def logout_backend():
        session.clear()
        return jsonify({"status": "success"}), 200

    @app.route('/api/perfil/actualizar', methods=['POST'])
    @requiere_sesion('ADMIN')
    def actualizar_perfil_admin():
        data = request.get_json(silent=True) or {}
        password_actual = data.get('password_actual')
        password = data.get('password') or None
        pass_admin_auth = data.get('pass_admin_auth') or None

        if not password_actual or not isinstance(password_actual, str):
            return jsonify({"status": "error", "message": "Debe indicar su contraseña actual"}), 400
        correo_nuevo = _correo(data.get('correo'), obligatorio=True)
        telefono = _texto(data.get('telefono'), 'telefono', 30)
        if password:
            _validar_password(password, session['username'])
        if pass_admin_auth:
            _validar_password(pass_admin_auth)

        # Solo se puede modificar el perfil del propio administrador autenticado
        username = session['username']
        conn = get_db_connection()
        try:
            fila = conn.execute("SELECT * FROM usuario WHERE username = ?", (username,)).fetchone()
            if not check_password_hash(fila['password'], password_actual):
                return jsonify({"status": "error", "message": "Contraseña actual incorrecta"}), 403
            if conn.execute("SELECT 1 FROM usuario WHERE LOWER(correo) = ? AND username != ?",
                            (correo_nuevo, username)).fetchone():
                raise ErrorValidacion("Ese correo ya está en uso")

            nuevo_hash = generate_password_hash(password) if password else fila['password']
            nuevo_auth = generate_password_hash(pass_admin_auth) if pass_admin_auth else fila['pass_admin_auth']
            conn.execute("""
                UPDATE usuario SET correo = ?, telefono = ?, password = ?, pass_admin_auth = ?
                WHERE username = ?
            """, (correo_nuevo, telefono, nuevo_hash, nuevo_auth, username))
            conn.commit()
            session['pv'] = _marca_password(nuevo_hash)
            return jsonify({"status": "success", "message": "Perfil actualizado de forma segura"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Verificación de administrador para desbloquear ediciones/bajas (reemplaza la clave fija del cliente)
    @app.route('/api/autorizar', methods=['POST'])
    @requiere_sesion()
    def autorizar_operacion():
        data = request.get_json(silent=True) or {}
        password = data.get('password')
        if not isinstance(password, str) or not password:
            return jsonify({"status": "error", "message": "Clave requerida"}), 400
        clave = f"auth|{request.remote_addr}|{session['username']}"
        if login_bloqueado(clave):
            return jsonify({"status": "error", "message": "Demasiados intentos. Intente más tarde"}), 429
        conn = get_db_connection()
        try:
            admins = conn.execute(
                "SELECT password, pass_admin_auth FROM usuario WHERE rol = 'ADMIN' AND activo = 1").fetchall()
            propio = conn.execute("SELECT password, rol FROM usuario WHERE username = ?",
                                  (session['username'],)).fetchone()
        finally:
            conn.close()
        candidatos = list(admins)
        if propio and propio['rol'] in ('ADMIN', 'RRHH'):
            # Reautenticación: quien opera confirma con su propia contraseña
            candidatos.append({'password': propio['password'], 'pass_admin_auth': None})
        for admin in candidatos:
            for hash_guardado in (admin['pass_admin_auth'], admin['password']):
                if hash_guardado and check_password_hash(hash_guardado, password):
                    intentos_login.pop(clave, None)
                    return jsonify({"status": "success"}), 200
        intentos_login.setdefault(clave, []).append(time.time())
        return jsonify({"status": "error", "message": "Contraseña incorrecta"}), 403

    # Conjunto de datos ficticios para demostraciones/exámenes; no existe salvo que DEMO_DATA=1
    @app.route('/api/demo/datos', methods=['GET'])
    @requiere_sesion()
    def datos_demostracion():
        if os.environ.get('DEMO_DATA', '').lower() not in ('1', 'true'):
            return jsonify({"status": "error", "message": "Recurso no encontrado"}), 404
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo_data', 'demo.json')
        with open(ruta, encoding='utf-8') as f:
            return app.response_class(f.read(), mimetype='application/json')

    # =========================================================
    # 6. GESTIÓN DE USUARIOS (SOLO ADMIN)
    # =========================================================
    @app.route('/api/usuarios', methods=['GET'])
    @requiere_sesion('ADMIN')
    def listar_usuarios():
        conn = get_db_connection()
        try:
            filas = conn.execute("SELECT * FROM usuario ORDER BY username").fetchall()
        finally:
            conn.close()
        return jsonify([_usuario_publico(f) for f in filas]), 200

    @app.route('/api/usuarios', methods=['POST'])
    @requiere_sesion('ADMIN')
    def crear_usuario():
        data = request.get_json(silent=True) or {}
        username = data.get('username')
        if not isinstance(username, str) or not PATRON_USUARIO.match(username):
            raise ErrorValidacion("El usuario debe tener 3-30 caracteres (letras, números, . _ -)")
        rol = data.get('rol')
        if rol not in ROLES:
            raise ErrorValidacion("El rol no es válido")
        correo_nuevo = _correo(data.get('correo'), obligatorio=True)
        _validar_password(data.get('password'), username)
        permisos = 'ALL' if rol == 'ADMIN' else _permisos(data.get('permisos'))

        conn = get_db_connection()
        try:
            if conn.execute("SELECT 1 FROM usuario WHERE LOWER(username) = ? OR LOWER(correo) = ?",
                            (username.lower(), correo_nuevo)).fetchone():
                raise ErrorValidacion("El usuario o el correo ya existen en el sistema")
            hash_nuevo = generate_password_hash(data['password'])
            conn.execute("""
                INSERT INTO usuario (username, password, pass_admin_auth, rol, correo, telefono, permisos, activo)
                VALUES (?, ?, ?, ?, ?, '', ?, 1)
            """, (username, hash_nuevo, hash_nuevo if rol == 'ADMIN' else '', rol, correo_nuevo, permisos))
            conn.commit()
            return jsonify({"status": "success"}), 201
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.route('/api/usuarios/<username>', methods=['PUT'])
    @requiere_sesion('ADMIN')
    def modificar_usuario(username):
        data = request.get_json(silent=True) or {}
        conn = get_db_connection()
        try:
            fila = conn.execute("SELECT * FROM usuario WHERE username = ?", (username,)).fetchone()
            if not fila:
                return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

            correo_nuevo = _correo(data['correo'], obligatorio=True) if 'correo' in data else fila['correo']
            if conn.execute("SELECT 1 FROM usuario WHERE LOWER(correo) = ? AND username != ?",
                            (correo_nuevo, username)).fetchone():
                raise ErrorValidacion("Ese correo ya está en uso")
            hash_nuevo = fila['password']
            if data.get('password'):
                _validar_password(data['password'], username)
                hash_nuevo = generate_password_hash(data['password'])
            permisos = fila['permisos']
            if fila['rol'] != 'ADMIN' and 'permisos' in data:
                permisos = _permisos(data['permisos'])
            activo = fila['activo']
            if 'activo' in data:
                activo = 1 if data['activo'] else 0
                if not activo and username == session['username']:
                    raise ErrorValidacion("No puede desactivar su propia cuenta")

            conn.execute("UPDATE usuario SET correo = ?, password = ?, permisos = ?, activo = ? WHERE username = ?",
                         (correo_nuevo, hash_nuevo, permisos, activo, username))
            conn.commit()
            if username == session['username']:
                session['pv'] = _marca_password(hash_nuevo)
            return jsonify({"status": "success"}), 200
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @app.route('/api/usuarios/<username>', methods=['DELETE'])
    @requiere_sesion('ADMIN')
    def eliminar_usuario(username):
        if username == session['username']:
            raise ErrorValidacion("No puede eliminar su propia cuenta")
        conn = get_db_connection()
        try:
            fila = conn.execute("SELECT rol FROM usuario WHERE username = ?", (username,)).fetchone()
            if not fila:
                return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
            if fila['rol'] == 'ADMIN':
                raise ErrorValidacion("Un administrador no puede eliminarse desde el sistema")
            conn.execute("DELETE FROM usuario WHERE username = ?", (username,))
            conn.commit()
            return jsonify({"status": "success"}), 200
        finally:
            conn.close()

    # =========================================================
    # 7. RECUPERACIÓN DE CONTRASEÑA POR CÓDIGO (OTP) AL CORREO REGISTRADO
    # =========================================================
    def _hmac_codigo(usuario_id, codigo):
        return hmac.new(app.config['SECRET_KEY'].encode('utf-8'), f"{usuario_id}:{codigo}".encode('utf-8'),
                        hashlib.sha256).hexdigest()

    def _enviar_codigo(destino, codigo):
        def tarea():
            try:
                if not correo.enviar_codigo_recuperacion(destino, codigo, VIGENCIA_CODIGO_MIN):
                    logger.error("No se pudo enviar el código de recuperación")
            except Exception:
                logger.exception("Fallo inesperado al enviar el código de recuperación")
        if app.config.get('TESTING'):
            tarea()
        else:
            # En segundo plano para que el tiempo de respuesta no revele si el correo existe
            threading.Thread(target=tarea, daemon=True).start()

    mensaje_solicitud = (f"Si el correo está registrado, recibirá un código de verificación "
                         f"válido por {VIGENCIA_CODIGO_MIN} minutos.")

    @app.route('/api/recuperar/solicitar', methods=['POST'])
    def solicitar_recuperacion():
        data = request.get_json(silent=True) or {}
        correo_solicitado = _correo(data.get('correo'), obligatorio=True)

        if excede_limite(f"rec-ip|{request.remote_addr}", 10, 3600) or \
                excede_limite(f"rec-correo|{correo_solicitado}", 3, 3600):
            return jsonify({"status": "error", "message": "Demasiadas solicitudes. Intente más tarde"}), 429

        conn = get_db_connection()
        try:
            filas = conn.execute("SELECT id FROM usuario WHERE LOWER(correo) = ? AND activo = 1",
                                 (correo_solicitado,)).fetchall()
            if len(filas) == 1:
                usuario_id = filas[0]['id']
                codigo = f"{secrets.randbelow(1_000_000):06d}"
                conn.execute("DELETE FROM reset_password WHERE usuario_id = ?", (usuario_id,))
                conn.execute("INSERT INTO reset_password (usuario_id, codigo_hash, expira) VALUES (?, ?, ?)",
                             (usuario_id, _hmac_codigo(usuario_id, codigo), time.time() + VIGENCIA_CODIGO_MIN * 60))
                conn.commit()
                _enviar_codigo(correo_solicitado, codigo)
        finally:
            conn.close()
        # Misma respuesta exista o no el correo (evita enumeración de cuentas)
        return jsonify({"status": "success", "message": mensaje_solicitud}), 200

    @app.route('/api/recuperar/confirmar', methods=['POST'])
    def confirmar_recuperacion():
        data = request.get_json(silent=True) or {}
        correo_solicitado = _correo(data.get('correo'), obligatorio=True)
        codigo = data.get('codigo')
        nueva = data.get('nueva_password')
        if not isinstance(codigo, str) or not re.fullmatch(r'\d{6}', codigo.strip()):
            raise ErrorValidacion("El código debe tener 6 dígitos")
        codigo = codigo.strip()
        if excede_limite(f"conf-ip|{request.remote_addr}", 20, 3600):
            return jsonify({"status": "error", "message": "Demasiados intentos. Intente más tarde"}), 429
        invalido = (jsonify({"status": "error", "message": "Código inválido o vencido"}), 400)

        conn = get_db_connection()
        try:
            usuario = conn.execute("SELECT id, username FROM usuario WHERE LOWER(correo) = ? AND activo = 1",
                                   (correo_solicitado,)).fetchone()
            if not usuario:
                return invalido
            registro = conn.execute("SELECT * FROM reset_password WHERE usuario_id = ?", (usuario['id'],)).fetchone()
            if not registro or registro['expira'] < time.time() or registro['intentos'] >= INTENTOS_CODIGO_MAX:
                conn.execute("DELETE FROM reset_password WHERE usuario_id = ?", (usuario['id'],))
                conn.commit()
                return invalido
            if not hmac.compare_digest(registro['codigo_hash'], _hmac_codigo(usuario['id'], codigo)):
                conn.execute("UPDATE reset_password SET intentos = intentos + 1 WHERE id = ?", (registro['id'],))
                conn.commit()
                return invalido

            # Código correcto: la contraseña se valida después para no gastar el código por un error de formato
            _validar_password(nueva, usuario['username'])
            conn.execute("UPDATE usuario SET password = ? WHERE id = ?",
                         (generate_password_hash(nueva), usuario['id']))
            conn.execute("DELETE FROM reset_password WHERE usuario_id = ?", (usuario['id'],))
            conn.commit()
            logger.info("Contraseña restablecida para el usuario %s", usuario['username'])
            return jsonify({"status": "success", "message": "Contraseña actualizada. Ya puede iniciar sesión"}), 200
        finally:
            conn.close()

    # MANEJADORES DE ERROR HTTP
    @app.errorhandler(ErrorValidacion)
    def entrada_invalida(e):
        return jsonify({"status": "error", "message": str(e)}), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def conflicto_datos(e):
        logger.warning("Violación de integridad: %s", e)
        return jsonify({"status": "error", "message": "Datos inválidos o duplicados"}), 400

    @app.errorhandler(404)
    def recurso_no_encontrado(e):
        return jsonify({"status": "error", "message": "Recurso no encontrado"}), 404

    @app.errorhandler(413)
    def cuerpo_demasiado_grande(e):
        return jsonify({"status": "error", "message": "La solicitud es demasiado grande"}), 413

    @app.errorhandler(Exception)
    def error_interno_servidor(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify({"status": "error", "message": e.description}), e.code
        logger.exception("Error no controlado")
        return jsonify({"status": "error", "message": "Error interno del servidor"}), 500

    return app
