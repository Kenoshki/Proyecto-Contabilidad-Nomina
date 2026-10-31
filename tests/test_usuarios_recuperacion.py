import json
import time
import urllib.error

from tests.conftest import CLAVE_ADMIN, CORREO_ADMIN, login

NUEVA = 'Otra-Clave-Larga-7'


def solicitar(c, correo=CORREO_ADMIN):
    return c.post('/api/recuperar/solicitar', json={'correo': correo})


def confirmar(c, codigo, nueva=NUEVA, correo=CORREO_ADMIN):
    return c.post('/api/recuperar/confirmar', json={'correo': correo, 'codigo': codigo, 'nueva_password': nueva})


# ----------------------------------------------------------------- recuperación
def test_recuperacion_completa(cliente, correos):
    assert solicitar(cliente).status_code == 200
    destino, codigo = correos[0]
    assert destino == CORREO_ADMIN and len(codigo) == 6

    assert confirmar(cliente, '000000' if codigo != '000000' else '111111').status_code == 400
    # una contraseña débil no consume el código
    assert confirmar(cliente, codigo, 'corta').status_code == 400
    assert confirmar(cliente, codigo).status_code == 200

    assert login(cliente, pwd=CLAVE_ADMIN).status_code == 401
    assert login(cliente, pwd=NUEVA).status_code == 200
    # el código es de un solo uso
    assert confirmar(cliente, codigo, 'Tercera-Clave-Larga-3').status_code == 400


def test_no_enumera_cuentas(cliente, correos):
    a = solicitar(cliente)
    b = solicitar(cliente, 'nadie@ejemplo.gt')
    assert a.status_code == b.status_code == 200 and a.get_json() == b.get_json()
    assert len(correos) == 1 and correos[0][0] == CORREO_ADMIN


def test_codigo_expira(cliente, correos):
    solicitar(cliente)
    from app.db import get_db_connection
    conn = get_db_connection()
    conn.execute("UPDATE reset_password SET expira = ?", (time.time() - 1,))
    conn.commit(); conn.close()
    assert confirmar(cliente, correos[0][1]).status_code == 400


def test_codigo_se_bloquea_tras_cinco_fallos(cliente, correos):
    solicitar(cliente)
    real = correos[0][1]
    falso = '000000' if real != '000000' else '111111'
    for _ in range(5):
        assert confirmar(cliente, falso).status_code == 400
    assert confirmar(cliente, real).status_code == 400
    assert login(cliente, pwd=CLAVE_ADMIN).status_code == 200


def test_limite_de_solicitudes_por_correo(cliente):
    assert [solicitar(cliente).status_code for _ in range(4)] == [200, 200, 200, 429]


def test_solicitud_sin_proveedor_de_correo_no_rompe(cliente, monkeypatch):
    from app import correo
    monkeypatch.setattr(correo, 'enviar_codigo_recuperacion', lambda *a: False)
    assert solicitar(cliente).status_code == 200


def test_reset_invalida_sesion_existente(app_flask, correos):
    a, b = app_flask.test_client(), app_flask.test_client()
    login(a)
    assert a.get('/api/empleados').status_code == 200
    solicitar(b)
    assert confirmar(b, correos[0][1]).status_code == 200
    assert a.get('/api/empleados').status_code == 401
    assert a.get('/api/sesion').status_code == 401


# ----------------------------------------------------------------- usuarios
def nuevo(c, **kw):
    cuerpo = {'username': 'maria', 'correo': 'maria@ejemplo.gt', 'password': 'Maria-Clave-2026', 'rol': 'RRHH',
              'permisos': ['dashboard', 'empleados']}
    cuerpo.update(kw)
    return c.post('/api/usuarios', json=cuerpo)


def test_crud_usuarios(cliente):
    login(cliente)
    assert nuevo(cliente).status_code == 201
    assert nuevo(cliente).status_code == 400                      # duplicado
    assert nuevo(cliente, username='otro').status_code == 400     # correo duplicado
    assert nuevo(cliente, username='x1', correo='a@b.gt', password='corta').status_code == 400
    assert nuevo(cliente, username='x2', correo='c@d.gt', rol='ROOT').status_code == 400
    assert nuevo(cliente, username='x3', correo='e@f.gt', permisos=['usuarios']).status_code == 400

    lista = cliente.get('/api/usuarios').get_json()
    assert all('password' not in u and 'pass_admin_auth' not in u for u in lista)
    maria = next(u for u in lista if u['username'] == 'maria')
    assert maria['permisos'] == ['dashboard', 'empleados']

    r = cliente.put('/api/usuarios/maria', json={'permisos': ['dashboard'], 'correo': 'm2@ejemplo.gt'})
    assert r.status_code == 200
    assert cliente.put('/api/usuarios/nadie', json={}).status_code == 404
    assert cliente.delete('/api/usuarios/admin').status_code == 400
    assert cliente.delete('/api/usuarios/maria').status_code == 200
    assert cliente.delete('/api/usuarios/maria').status_code == 404


def test_usuario_desactivado_pierde_acceso(app_flask):
    admin, maria = app_flask.test_client(), app_flask.test_client()
    login(admin)
    nuevo(admin)
    assert login(maria, 'maria', 'Maria-Clave-2026').status_code == 200
    assert maria.get('/api/empleados').status_code == 200
    admin.put('/api/usuarios/maria', json={'activo': False})
    assert maria.get('/api/empleados').status_code == 401
    assert login(maria, 'maria', 'Maria-Clave-2026').status_code == 401
    assert admin.put('/api/usuarios/admin', json={'activo': False}).status_code == 400


def test_solo_admin_gestiona_usuarios(app_flask):
    admin, maria = app_flask.test_client(), app_flask.test_client()
    login(admin)
    nuevo(admin)
    login(maria, 'maria', 'Maria-Clave-2026')
    assert maria.get('/api/usuarios').status_code == 403
    assert nuevo(maria, username='z9', correo='z@z.gt').status_code == 403
    assert maria.delete('/api/usuarios/admin').status_code == 403


def test_cambio_de_rol_se_aplica_de_inmediato(app_flask):
    admin, maria = app_flask.test_client(), app_flask.test_client()
    login(admin)
    nuevo(admin)
    login(maria, 'maria', 'Maria-Clave-2026')
    assert maria.post('/api/departamentos', json={'codigo': 'D-9', 'nombre': 'NUEVO'}).status_code == 200
    from app.db import get_db_connection
    conn = get_db_connection()
    conn.execute("UPDATE usuario SET rol = 'OPERADOR' WHERE username = 'maria'")
    conn.commit(); conn.close()
    assert maria.post('/api/departamentos', json={'codigo': 'D-10', 'nombre': 'OTRO'}).status_code == 403


def test_sesion_y_autorizar(cliente):
    assert cliente.get('/api/sesion').status_code == 401
    assert cliente.post('/api/autorizar', json={'password': CLAVE_ADMIN}).status_code == 401
    login(cliente)
    r = cliente.get('/api/sesion').get_json()['usuario']
    assert r['username'] == 'admin' and 'password' not in r and r['permisos'] == ['ALL']
    assert cliente.post('/api/autorizar', json={'password': 'incorrecta'}).status_code == 403
    assert cliente.post('/api/autorizar', json={'password': CLAVE_ADMIN}).status_code == 200
    for _ in range(5):
        cliente.post('/api/autorizar', json={'password': 'incorrecta'})
    assert cliente.post('/api/autorizar', json={'password': CLAVE_ADMIN}).status_code == 429


# ----------------------------------------------------------------- módulo de correo
def test_correo_sin_configurar_en_produccion(monkeypatch):
    from app import correo
    for v in correo.VARIABLES:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv('FLASK_DEBUG', raising=False)
    assert correo.enviar_codigo_recuperacion('a@b.gt', '123456', 10) is False


def test_correo_envia_a_emailjs(monkeypatch):
    from app import correo
    for v in correo.VARIABLES:
        monkeypatch.setenv(v, 'valor-' + v)
    capturado = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def falso_urlopen(peticion, timeout):
        capturado['url'] = peticion.full_url
        capturado['cuerpo'] = json.loads(peticion.data)
        capturado['timeout'] = timeout
        return Resp()

    monkeypatch.setattr(correo.urllib.request, 'urlopen', falso_urlopen)
    assert correo.enviar_codigo_recuperacion('a@b.gt', '123456', 10) is True
    assert capturado['url'] == correo.URL_EMAILJS and capturado['timeout'] == 10
    assert capturado['cuerpo']['template_params'] == {
        'to_email': 'a@b.gt', 'otp_code': '123456', 'tiempo_limite': '10 minutos'}
    assert capturado['cuerpo']['accessToken'] == 'valor-EMAILJS_PRIVATE_KEY'


def test_correo_falla_de_red_devuelve_false(monkeypatch):
    from app import correo
    for v in correo.VARIABLES:
        monkeypatch.setenv(v, 'x')

    def falla(*a, **k):
        raise urllib.error.URLError('sin red')

    monkeypatch.setattr(correo.urllib.request, 'urlopen', falla)
    assert correo.enviar_codigo_recuperacion('a@b.gt', '123456', 10) is False
