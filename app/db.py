import json
import os
import sqlite3
from werkzeug.security import generate_password_hash

def get_db_path():
    # En producción (Railway) apuntar DATABASE_PATH a un Volume, p. ej. /data/sistema_planillas.db
    ruta_env = os.environ.get('DATABASE_PATH')
    if ruta_env:
        os.makedirs(os.path.dirname(os.path.abspath(ruta_env)), exist_ok=True)
        return ruta_env
    # Construye la ruta absoluta basada en la ubicación del archivo
    base_dir = os.path.abspath(os.path.dirname(__file__))
    instance_path = os.path.abspath(os.path.join(base_dir, '..', 'instance'))
    os.makedirs(instance_path, exist_ok=True)
    return os.path.join(instance_path, 'sistema_planillas.db')

def get_db_connection():
    # Función centralizada que activa Foreign Keys en SQLite
    conn = sqlite3.connect(get_db_path(), timeout=30)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. TABLA: DEPARTAMENTOS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS departamento (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        nombre TEXT UNIQUE NOT NULL
    );
    """)

    # 2. TABLA: USUARIOS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        pass_admin_auth TEXT DEFAULT '',
        rol TEXT NOT NULL CHECK(rol IN ('ADMIN', 'RRHH', 'OPERADOR')),
        correo TEXT,
        telefono TEXT,
        permisos TEXT DEFAULT 'ALL',
        activo INTEGER DEFAULT 1
    );
    """)

    # 3. TABLA: EMPLEADOS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS empleado (
        dpi TEXT PRIMARY KEY,
        fecha_ingreso TEXT NOT NULL,
        nombre TEXT NOT NULL,
        direccion TEXT,
        telefono TEXT,
        celular TEXT,
        nit TEXT,
        senales TEXT DEFAULT 'NINGUNA',
        enfermedad TEXT DEFAULT 'NINGUNA',
        empresa TEXT DEFAULT 'TECNIMARKET S.A. DE GUATEMALA',
        departamento_id INTEGER,
        cargo TEXT NOT NULL,
        tipo_origen TEXT NOT NULL CHECK(tipo_origen IN ('LOCAL', 'EXTRANJERO')),
        pais TEXT DEFAULT 'Guatemala',
        visa TEXT,
        moneda TEXT NOT NULL CHECK(moneda IN ('GTQ', 'USD')),
        sueldo_base REAL NOT NULL,
        tipo_pago TEXT DEFAULT 'Mensual',
        aplica_igss INTEGER DEFAULT 1,
        aplica_bono INTEGER DEFAULT 1,
        aplica_isr INTEGER DEFAULT 1,
        estado_civil TEXT,
        hijos INTEGER DEFAULT 0,
        conyuge TEXT,
        tel_conyuge TEXT,
        foto TEXT,
        estado TEXT DEFAULT 'ACTIVO' CHECK(estado IN ('ACTIVO', 'INACTIVO')),
        FOREIGN KEY (departamento_id) REFERENCES departamento(id) ON DELETE SET NULL
    );
    """)

    # 4. TABLA: ASISTENCIA DIARIA
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS asistencia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empleado_dpi TEXT NOT NULL,
        fecha TEXT NOT NULL,
        hora_entrada TEXT DEFAULT '08:00 AM',
        novedad TEXT DEFAULT 'NORMAL' CHECK(novedad IN ('NORMAL', 'IGSS', 'PERMISO', 'VACACIONES')),
        entrada_diferencial REAL DEFAULT 0.0,
        hora_salida TEXT DEFAULT '05:00 PM',
        horas_extra REAL DEFAULT 0.0,
        tarifa_extra REAL DEFAULT 20.0,
        aplica_pago INTEGER DEFAULT 1,
        total_extra REAL DEFAULT 0.0,
        FOREIGN KEY (empleado_dpi) REFERENCES empleado(dpi) ON DELETE CASCADE
    );
    """)

    # 5. TABLA: BAJAS Y FINIQUITOS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS baja_finiquito (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empleado_dpi TEXT NOT NULL,
        tipo_baja TEXT NOT NULL CHECK(tipo_baja IN ('DESPIDO', 'RENUNCIA')),
        fecha_baja TEXT NOT NULL,
        dias_mes_laborados INTEGER NOT NULL,
        dias_vacaciones_pendientes REAL NOT NULL,
        observaciones TEXT,
        salario_pendiente REAL NOT NULL,
        bono_incentivo_prop REAL NOT NULL,
        aguinaldo_prop REAL NOT NULL,
        bono14_prop REAL NOT NULL,
        vacaciones_prop REAL NOT NULL,
        indemnizacion REAL DEFAULT 0.0,
        total_liquidado REAL NOT NULL,
        fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (empleado_dpi) REFERENCES empleado(dpi) ON DELETE CASCADE
    );
    """)

    # 6. TABLA: EX_EMPLEADOS
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ex_empleado (
        dpi TEXT PRIMARY KEY,
        codigo TEXT,
        nombre TEXT NOT NULL,
        departamento TEXT,
        cargo TEXT,
        causal_salida TEXT NOT NULL,
        fecha_salida TEXT NOT NULL,
        monto_liquidado REAL NOT NULL,
        foto TEXT,
        fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 7. TABLA: CÓDIGOS DE RECUPERACIÓN DE CONTRASEÑA (solo se guarda el HMAC del código)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reset_password (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        codigo_hash TEXT NOT NULL,
        expira REAL NOT NULL,
        intentos INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (usuario_id) REFERENCES usuario(id) ON DELETE CASCADE
    );
    """)

    # Índices para consultas por DPI
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_empleado_dpi ON empleado(dpi);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ex_empleado_dpi ON ex_empleado(dpi);")

    # DATOS INICIALES (SEEDING)
    deptos = [
        ('DEP-01', 'DESARROLLO'),
        ('DEP-02', 'DISEÑO'),
        ('DEP-03', 'VENTAS'),
        ('DEP-04', 'ATENCION AL CLIENTE'),
        ('DEP-05', 'ADMINISTRACION'),
        ('DEP-06', 'MERCADEO'),
        ('DEP-07', 'CONTABILIDAD')
    ]
    cursor.executemany("INSERT OR IGNORE INTO departamento (codigo, nombre) VALUES (?, ?);", deptos)

    # USUARIOS: nunca se siembran contraseñas conocidas en producción.
    # - Con ADMIN_PASSWORD definida se crea el administrador inicial (solo si no existe).
    # - Con SEED_DEMO_DATA=1 (solo desarrollo) se cargan usuarios y empleados de demostración.
    admin_password = os.environ.get('ADMIN_PASSWORD')
    if admin_password:
        if len(admin_password) < 12:
            raise RuntimeError("ADMIN_PASSWORD debe tener al menos 12 caracteres")
        cursor.execute("""
        INSERT OR IGNORE INTO usuario (username, password, pass_admin_auth, rol, correo, telefono, permisos, activo)
        VALUES (?, ?, ?, 'ADMIN', ?, '', 'ALL', 1);
        """, (
            os.environ.get('ADMIN_USERNAME', 'admin'),
            generate_password_hash(admin_password),
            generate_password_hash(admin_password),
            os.environ.get('ADMIN_EMAIL', '').strip().lower(),
        ))

    # Cuentas de estudiantes para exámenes/demostraciones (solo hashes; ver tools/generar_estudiantes.py)
    if os.environ.get('SEED_ESTUDIANTES', '').lower() in ('1', 'true'):
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo_data', 'estudiantes.json')
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                cuentas = json.load(f)
            cursor.executemany("""
            INSERT OR IGNORE INTO usuario (username, password, pass_admin_auth, rol, correo, telefono, permisos, activo)
            VALUES (?, ?, '', ?, ?, '', ?, 1);
            """, [(c['username'], c['password_hash'], c['rol'], c['correo'], c['permisos']) for c in cuentas])

    if os.environ.get('SEED_DEMO_DATA', '').lower() in ('1', 'true'):
        usuarios = [
            ('admin', generate_password_hash('admin123'), generate_password_hash('admin123'), 'ADMIN', 'admin@tecnimarket.gt', '2222-3333', 'ALL', 1),
            ('rrhh', generate_password_hash('rrhh123'), '', 'RRHH', 'rrhh@tecnimarket.gt', '5555-4444', 'dashboard,empleados,locales,extranjeros,directorio,planillas,asistencia,bajas,ex-empleados', 1),
            ('operador', generate_password_hash('op123'), '', 'OPERADOR', 'operador@tecnimarket.gt', '4444-1111', 'dashboard,asistencia', 1)
        ]
        cursor.executemany("""
        INSERT OR IGNORE INTO usuario (username, password, pass_admin_auth, rol, correo, telefono, permisos, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, usuarios)

        empleados = [
            (
                '2024-01-15', 'JOSE FLORES GUZMÁN', 'ZONA 10, CIUDAD DE GUATEMALA',
                '2222-2222', '5555-5555', '2540123450101', '1010123-K', 'NINGUNA', 'NINGUNA',
                'TECNIMARKET S.A. DE GUATEMALA', 7, 'CONTADOR GENERAL', 'LOCAL', 'Guatemala',
                '', 'GTQ', 4500.00, 'Mensual', 1, 1, 1, 'Casado', 2, 'CELINA FLORES', '2525-3030',
                'https://placehold.co/150x180/3b82f6/ffffff?text=JOSE+FLORES', 'ACTIVO'
            ),
            (
                '2024-03-01', 'MARIO RIVAS', 'ZONA 11, MIXCO, GUATEMALA',
                '2333-4444', '4444-1111', '1890987650101', '882312-4', 'NINGUNA', 'NINGUNA',
                'TECNIMARKET S.A. DE GUATEMALA', 3, 'EJECUTIVO DE VENTAS', 'LOCAL', 'Guatemala',
                '', 'GTQ', 3800.00, 'Mensual', 1, 1, 0, 'Soltero', 0, '', '',
                'https://placehold.co/150x180/10b981/ffffff?text=MARIO+RIVAS', 'ACTIVO'
            ),
            (
                '2023-11-10', 'SONIA FIGUEROA', 'CARRETERA A EL SALVADOR, KM 14',
                '2444-5555', '3333-2222', '3001456780101', '991204-1', 'NINGUNA', 'INCAPACIDAD PARCIAL',
                'TECNIMARKET S.A. DE GUATEMALA', 1, 'INGENIERA DE SOFTWARE EXPATRIADA', 'EXTRANJERO', 'Estados Unidos',
                'Visa V-3', 'USD', 1200.00, 'Mensual', 1, 1, 1, 'Casado', 1, 'CARLOS FIGUEROA', '2444-9999',
                'https://placehold.co/150x180/8b5cf6/ffffff?text=SONIA+F', 'ACTIVO'
            )
        ]

        cursor.executemany("""
        INSERT OR IGNORE INTO empleado (
            fecha_ingreso, nombre, direccion, telefono, celular, dpi, nit,
            senales, enfermedad, empresa, departamento_id, cargo, tipo_origen, pais,
            visa, moneda, sueldo_base, tipo_pago, aplica_igss, aplica_bono, aplica_isr,
            estado_civil, hijos, conyuge, tel_conyuge, foto, estado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, empleados)
    

    conn.commit()
    conn.close()
