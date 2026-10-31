"""Pruebas del escenario de examen: 20 estudiantes, 100 empleados ficticios, bajas con el formato de la pantalla."""
import csv
import json
import os
import re

import pytest

from tests.conftest import CLAVE_ADMIN, login

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(RAIZ, 'app', 'demo_data', 'demo.json')
CSV_ESTUDIANTES = os.path.join(RAIZ, 'tools', 'salida', 'credenciales_estudiantes.csv')
DEPARTAMENTOS = {'DESARROLLO', 'DISEÑO', 'VENTAS', 'ATENCION AL CLIENTE', 'ADMINISTRACION', 'MERCADEO', 'CONTABILIDAD'}


def cargar_demo():
    with open(DEMO, encoding='utf-8') as f:
        return json.load(f)


# ----------------------------------------------------------------- calidad de los datos ficticios
def test_demo_tiene_100_empleados_consistentes():
    d = cargar_demo()
    emps = d['empleados']
    assert len(emps) == 100
    assert len({e['dpi'] for e in emps}) == 100 and len({e['codigo'] for e in emps}) == 100
    for e in emps:
        assert e['departamento'] in DEPARTAMENTOS, e['codigo']
        assert e['sueldo'] > 0 and e['moneda'] in ('GTQ', 'USD')
        assert not re.search(r'[<>`]', json.dumps(e, ensure_ascii=False))
        assert e['foto'].startswith('https://')
        if e['tipoOrigen'] == 'LOCAL':
            assert re.fullmatch(r'\d{13}', e['dpi']) and e['moneda'] == 'GTQ' and e['pais'] == 'Guatemala'
        else:
            assert re.fullmatch(r'[A-Z0-9]{9}', e['dpi']) and e['moneda'] == 'USD' and e['pais'] != 'Guatemala'
    assert sum(e['tipoOrigen'] == 'EXTRANJERO' for e in emps) >= 15
    assert {e['departamento'] for e in emps} == DEPARTAMENTOS
    assert len(d['exEmpleados']) >= 5 and set(d['asistencia']) <= {e['dpi'] for e in emps}


# ----------------------------------------------------------------- endpoint de demostración
def test_demo_datos_requiere_sesion_y_bandera(cliente, monkeypatch):
    monkeypatch.delenv('DEMO_DATA', raising=False)
    assert cliente.get('/api/demo/datos').status_code == 401
    login(cliente)
    assert cliente.get('/api/demo/datos').status_code == 404
    monkeypatch.setenv('DEMO_DATA', '1')
    r = cliente.get('/api/demo/datos')
    assert r.status_code == 200 and len(r.get_json()['empleados']) == 100


# ----------------------------------------------------------------- baja con el formato real de la pantalla
def test_baja_acepta_total_con_formato_y_foto_cualquiera(cliente):
    login(cliente)
    e = cargar_demo()['empleados'][0]
    cuerpo = {'dpi': e['dpi'], 'codigo': e['codigo'], 'nombre': e['nombre'], 'departamento': e['departamento'],
              'cargo': e['cargo'], 'causalSalida': 'DESPIDO_JUSTIFICADO', 'fechaSalida': '2026-10-31',
              'montoLiquidado': 'Q 12,345.67', 'foto': 'blob:http://localhost/xyz'}
    assert cliente.post('/api/baja', json=cuerpo).status_code == 200
    assert cliente.post('/api/baja', json={**cuerpo, 'montoLiquidado': 'Q 0.00'}).status_code == 200
    assert cliente.post('/api/baja', json={**cuerpo, 'montoLiquidado': 'abc'}).status_code == 400
    assert cliente.post('/api/baja', json={**cuerpo, 'montoLiquidado': 'Q -5'}).status_code == 400


def test_baja_de_los_100_empleados_demo(cliente):
    login(cliente)
    for e in cargar_demo()['empleados']:
        r = cliente.post('/api/baja', json={
            'dpi': e['dpi'], 'codigo': e['codigo'], 'nombre': e['nombre'], 'departamento': e['departamento'],
            'cargo': e['cargo'], 'causalSalida': 'RENUNCIA', 'fechaSalida': '2026-10-31',
            'montoLiquidado': 'Q 1,000.00', 'foto': e['foto']})
        assert r.status_code == 200, (e['codigo'], r.get_data(as_text=True))
    assert len(cliente.get('/api/ex-empleados').get_json()) == 100


# ----------------------------------------------------------------- cuentas de estudiantes
@pytest.fixture()
def cliente_estudiantes(monkeypatch, app_flask_factory):
    monkeypatch.setenv('SEED_ESTUDIANTES', '1')
    return app_flask_factory().test_client()


@pytest.fixture()
def app_flask_factory(monkeypatch, correos):
    import tempfile

    def crear():
        tmp = tempfile.mkdtemp()
        monkeypatch.setenv('DATABASE_PATH', os.path.join(tmp, 't.db'))
        monkeypatch.setenv('SECRET_KEY', 'x' * 32)
        monkeypatch.setenv('ADMIN_PASSWORD', CLAVE_ADMIN)
        monkeypatch.setenv('PROXY_HOPS', '0')
        from app import create_app
        app = create_app()
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        return app
    return crear


def test_semilla_de_20_estudiantes(cliente_estudiantes):
    c = cliente_estudiantes
    login(c)
    usuarios = c.get('/api/usuarios').get_json()
    est = [u for u in usuarios if u['username'].startswith('est')]
    assert len(est) == 20 and all(u['rol'] == 'RRHH' and u['activo'] for u in est)
    assert all('password' not in u for u in usuarios)


@pytest.mark.skipif(not os.path.exists(CSV_ESTUDIANTES), reason='credenciales no generadas en este equipo')
def test_credenciales_entregadas_funcionan(cliente_estudiantes, app_flask_factory):
    app = app_flask_factory()
    with open(CSV_ESTUDIANTES, encoding='utf-8') as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 20 and len({f['contrasena'] for f in filas}) == 20
    for fila in filas:
        c = app.test_client()
        assert login(c, fila['usuario'], fila['contrasena']).status_code == 200, fila['usuario']
        assert c.post('/api/empleados', json={}).status_code != 403          # RRHH puede operar empleados
        assert c.get('/api/usuarios').status_code == 403                      # y no administrar usuarios


def test_estudiante_puede_reautenticar_con_su_propia_clave(app_flask_factory, monkeypatch):
    from werkzeug.security import generate_password_hash
    app = app_flask_factory()
    from app.db import get_db_connection
    conn = get_db_connection()
    conn.execute("INSERT INTO usuario (username,password,rol,correo) VALUES ('rh1',?,'RRHH','rh1@x.gt')",
                 (generate_password_hash('Rrhh-Clave-123'),))
    conn.execute("INSERT INTO usuario (username,password,rol,correo) VALUES ('op1',?,'OPERADOR','op1@x.gt')",
                 (generate_password_hash('Oper-Clave-123'),))
    conn.commit(); conn.close()
    rh, op = app.test_client(), app.test_client()
    login(rh, 'rh1', 'Rrhh-Clave-123'); login(op, 'op1', 'Oper-Clave-123')
    assert rh.post('/api/autorizar', json={'password': 'Rrhh-Clave-123'}).status_code == 200
    assert rh.post('/api/autorizar', json={'password': 'mala'}).status_code == 403
    assert op.post('/api/autorizar', json={'password': 'Oper-Clave-123'}).status_code == 403   # operador no desbloquea


def test_limite_de_intentos_configurable(cliente, monkeypatch):
    monkeypatch.setenv('LOGIN_MAX_INTENTOS', '8')
    for _ in range(8):
        assert login(cliente, pwd='mala').status_code == 401
    assert login(cliente, pwd=CLAVE_ADMIN).status_code == 429


def test_intentos_fallidos_de_un_usuario_no_bloquean_a_otro_en_la_misma_ip(app_flask_factory):
    app = app_flask_factory()
    a, b = app.test_client(), app.test_client()
    for _ in range(6):
        login(a, 'admin', 'mala')
    assert login(a, pwd=CLAVE_ADMIN).status_code == 429
    # misma IP (127.0.0.1), otra cuenta: no se ve afectada
    assert login(b, 'otro', 'x').status_code == 401
