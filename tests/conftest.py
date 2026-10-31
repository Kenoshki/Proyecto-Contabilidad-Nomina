import os
import tempfile

import pytest

CLAVE_ADMIN = 'Clave-Admin-Segura-1'
CORREO_ADMIN = 'admin@ejemplo.gt'


@pytest.fixture()
def correos(monkeypatch):
    """Captura los códigos de recuperación en lugar de enviarlos."""
    enviados = []
    from app import correo
    monkeypatch.setattr(correo, 'enviar_codigo_recuperacion',
                        lambda destino, codigo, minutos: enviados.append((destino, codigo)) or True)
    return enviados


@pytest.fixture()
def app_flask(monkeypatch, correos):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv('DATABASE_PATH', os.path.join(tmp, 'test.db'))
        monkeypatch.setenv('SECRET_KEY', 'x' * 32)
        monkeypatch.setenv('ADMIN_PASSWORD', CLAVE_ADMIN)
        monkeypatch.setenv('ADMIN_EMAIL', CORREO_ADMIN)
        monkeypatch.setenv('PROXY_HOPS', '0')
        monkeypatch.delenv('SEED_DEMO_DATA', raising=False)
        from app import create_app
        app = create_app()
        app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        yield app


@pytest.fixture()
def cliente(app_flask):
    return app_flask.test_client()


def login(c, user='admin', pwd=CLAVE_ADMIN):
    return c.post('/api/login', json={'username': user, 'password': pwd})
