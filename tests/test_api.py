import pytest

from tests.conftest import CLAVE_ADMIN, login

EMP = {'dpi': '2540123450101', 'fecha': '2024-01-01', 'nombre': 'ANA LOPEZ', 'cargo': 'CONTADORA',
       'sueldo': 4000, 'departamento': 'VENTAS', 'foto': 'https://ex.com/a.png'}


def test_api_exige_sesion(cliente):
    for metodo, ruta in [('get', '/api/empleados'), ('get', '/api/departamentos'), ('get', '/api/asistencia'),
                         ('get', '/api/ex-empleados'), ('post', '/api/empleados'), ('post', '/api/baja'),
                         ('post', '/api/perfil/actualizar'), ('delete', '/api/ex-empleados/1'),
                         ('delete', '/api/departamentos/1'), ('get', '/api/empleados/buscar?q=a'),
                         ('get', '/api/usuarios'), ('post', '/api/usuarios'), ('post', '/api/autorizar')]:
        assert getattr(cliente, metodo)(ruta).status_code == 401, ruta
    assert cliente.get('/healthz').status_code == 200


def test_sin_usuarios_por_defecto(cliente):
    assert login(cliente, 'admin', 'admin123').status_code == 401
    assert login(cliente, 'rrhh', 'rrhh123').status_code == 401
    r = login(cliente)
    assert r.status_code == 200 and 'password' not in r.get_json()['usuario']


def test_flujo_empleado_y_baja(cliente):
    login(cliente)
    assert cliente.post('/api/empleados', json=EMP).status_code == 200
    lista = cliente.get('/api/empleados').get_json()
    assert lista[0]['departamento'] == 'VENTAS'
    assert cliente.post('/api/baja', json={'dpi': '2540-1234-50101', 'nombre': 'ANA', 'causalSalida': 'RENUNCIA',
                                           'fechaSalida': '2026-01-01', 'montoLiquidado': 10}).status_code == 200
    assert cliente.get('/api/empleados').get_json() == []
    assert cliente.delete('/api/ex-empleados/2540123450101').status_code == 200


def test_validacion_y_xss(cliente):
    login(cliente)
    assert cliente.post('/api/empleados', json={**EMP, 'nombre': '<img src=x onerror=alert(1)>'}).status_code == 400
    assert cliente.post('/api/empleados', json={**EMP, 'dpi': "1'); alert(1);//"}).status_code == 400
    assert cliente.post('/api/empleados', json={**EMP, 'foto': 'javascript:alert(1)'}).status_code == 400
    assert cliente.post('/api/empleados', json={**EMP, 'sueldo': 'abc'}).status_code == 400
    assert cliente.post('/api/empleados', json={**EMP, 'sueldo': 'nan'}).status_code == 400
    assert cliente.post('/api/empleados', json={**EMP, 'tipoOrigen': 'OTRO'}).status_code == 400
    assert cliente.post('/api/asistencia', json=[{'dpi': 'x'}]).status_code == 400
    assert cliente.post('/api/asistencia', json={'a': 1}).status_code == 400


def test_roles(cliente):
    login(cliente)
    from app.db import get_db_connection
    from werkzeug.security import generate_password_hash
    conn = get_db_connection()
    conn.execute("INSERT INTO usuario (username,password,rol) VALUES ('op',?,'OPERADOR')", (generate_password_hash('op-clave-123'),))
    conn.commit(); conn.close()
    cliente.post('/api/logout')
    assert cliente.get('/api/empleados').status_code == 401
    assert login(cliente, 'op', 'op-clave-123').status_code == 200
    assert cliente.get('/api/empleados').status_code == 200
    assert cliente.post('/api/empleados', json=EMP).status_code == 403
    assert cliente.delete('/api/ex-empleados/1').status_code == 403
    assert cliente.post('/api/perfil/actualizar', json={}).status_code == 403


def test_perfil_requiere_clave_actual(cliente):
    login(cliente)
    base = {'password': 'Nueva-Clave-Larga-9', 'correo': 'a@b.cc'}
    assert cliente.post('/api/perfil/actualizar', json={**base, 'password_actual': 'mala'}).status_code == 403
    assert cliente.post('/api/perfil/actualizar', json={'password_actual': CLAVE_ADMIN, 'correo': 'a@b.cc', 'password': 'corta'}).status_code == 400
    assert cliente.post('/api/perfil/actualizar', json={**base, 'password_actual': CLAVE_ADMIN}).status_code == 200
    # la sesión actual sigue vigente tras cambiar la propia contraseña
    assert cliente.get('/api/sesion').status_code == 200
    cliente.post('/api/logout')
    assert login(cliente, pwd=CLAVE_ADMIN).status_code == 401
    assert login(cliente, pwd='Nueva-Clave-Larga-9').status_code == 200


def test_perfil_sin_cambiar_contrasena(cliente):
    login(cliente)
    r = cliente.post('/api/perfil/actualizar', json={'password_actual': CLAVE_ADMIN, 'correo': 'nuevo@ejemplo.gt', 'telefono': '2222-3333'})
    assert r.status_code == 200
    assert cliente.get('/api/sesion').get_json()['usuario']['correo'] == 'nuevo@ejemplo.gt'


def test_limitador_login(cliente):
    for _ in range(5):
        assert login(cliente, pwd='mala').status_code == 401
    assert login(cliente, pwd=CLAVE_ADMIN).status_code == 429


def test_errores_no_filtran_detalle(cliente):
    login(cliente)
    assert cliente.post('/api/departamentos', json={'codigo': 'DEP-99', 'nombre': 'NUEVO'}).status_code == 200
    r = cliente.post('/api/departamentos', json={'codigo': 'DEP-99', 'nombre': 'NUEVO'})
    assert r.status_code == 400 and 'UNIQUE' not in r.get_data(as_text=True)
    assert cliente.get('/no-existe').status_code == 404


def test_calculadora_publica_valida_entrada(cliente):
    assert cliente.post('/', data={'sueldo': 'abc'}).status_code == 400
    assert cliente.post('/', data={'sueldo': '5000', 'dias': '30', 'moneda': 'GTQ'}).status_code == 200
    assert cliente.get('/').headers['X-Frame-Options'] == 'DENY'


def test_secret_key_obligatoria(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('FLASK_DEBUG', raising=False)
    from app import create_app
    with pytest.raises(RuntimeError):
        create_app()


def test_html_sin_credenciales_ni_terceros_de_correo(cliente):
    html = cliente.get('/').get_data(as_text=True)
    for prohibido in ('admin123', 'rrhh123', 'op123', 'emailjs', 'gt_usuarios'.replace('gt_usuarios', 'passAdminAuth')):
        assert prohibido not in html, prohibido
