import os
import sys
import tempfile

PROYECTO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROYECTO)
tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_PATH=os.path.join(tmp, 'e2e.db'), SECRET_KEY='k' * 40, ADMIN_PASSWORD='Admin-Clave-E2E-1',
    ADMIN_EMAIL='admin@e2e.gt', SEED_ESTUDIANTES='1', DEMO_DATA='1', PROXY_HOPS='0', LOGIN_MAX_INTENTOS='10',
    PYTHONDONTWRITEBYTECODE='1')
from app import create_app  # noqa: E402

app = create_app()
app.config['SESSION_COOKIE_SECURE'] = False   # el navegador de prueba usa http://localhost
app.run(port=5055, threaded=True, use_reloader=False)
