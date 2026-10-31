"""Prueba de humo del servidor de producción (gunicorn) por socket Unix.

Uso:  python tests/smoke_gunicorn.py
Arranca gunicorn con una BD temporal, recorre login -> datos -> recuperación -> logout por HTTP real y
comprueba cabeceras y cookies de producción. No usa red (socket Unix), por lo que corre dentro del sandbox.
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAVE = 'Clave-Humo-Segura-1'
fallos = []


class ConexionUnix(http.client.HTTPConnection):
    def __init__(self, ruta):
        super().__init__('localhost')
        self.ruta = ruta

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self.ruta)


def peticion(sock, metodo, ruta, cuerpo=None, cookie=None):
    cabeceras = {'X-Forwarded-For': '203.0.113.7', 'X-Forwarded-Proto': 'https'}
    if cookie:
        cabeceras['Cookie'] = cookie
    datos = None
    if cuerpo is not None:
        datos = json.dumps(cuerpo)
        cabeceras['Content-Type'] = 'application/json'
    c = ConexionUnix(sock)
    c.request(metodo, ruta, body=datos, headers=cabeceras)
    r = c.getresponse()
    texto = r.read().decode('utf-8')
    c.close()
    return r, texto


def comprobar(nombre, condicion):
    print(('OK   ' if condicion else 'FALLA') + ' ' + nombre)
    if not condicion:
        fallos.append(nombre)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # Algunos sistemas de archivos (p. ej. /mnt/c en WSL) no admiten sockets Unix: se usa /tmp
        dir_sock = tempfile.mkdtemp(prefix='gsock', dir='/tmp' if os.path.isdir('/tmp') else None)
        sock = os.path.join(dir_sock, 'g.sock')
        entorno = {
            'PATH': os.environ.get('PATH', ''), 'HOME': tmp,
            'SECRET_KEY': 'k' * 40, 'ADMIN_PASSWORD': CLAVE, 'ADMIN_EMAIL': 'admin@ejemplo.gt',
            'DATABASE_PATH': os.path.join(tmp, 'datos', 'planillas.db'), 'PROXY_HOPS': '1',
        }
        proc = subprocess.Popen(
            [sys.executable, '-m', 'gunicorn', 'run:app', '--bind', f'unix:{sock}', '--workers', '2',
             '--threads', '2', '--worker-tmp-dir', dir_sock, '--log-level', 'warning'],
            cwd=RAIZ, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(100):
                if os.path.exists(sock) or proc.poll() is not None:
                    break
                time.sleep(0.1)
            time.sleep(0.5)
            comprobar('gunicorn arrancó', proc.poll() is None)

            r, t = peticion(sock, 'GET', '/healthz')
            comprobar('/healthz responde 200', r.status == 200 and json.loads(t)['status'] == 'ok')

            r, t = peticion(sock, 'GET', '/')
            comprobar('/ sirve la aplicación', r.status == 200 and 'Tecnimarket' in t)
            comprobar('cabeceras de seguridad', r.getheader('X-Frame-Options') == 'DENY'
                      and r.getheader('X-Content-Type-Options') == 'nosniff')
            comprobar('HTML sin credenciales de demostración', 'admin123' not in t and 'emailjs' not in t.lower())

            r, _ = peticion(sock, 'GET', '/api/empleados')
            comprobar('API sin sesión => 401', r.status == 401)
            r, _ = peticion(sock, 'POST', '/api/login', {'username': 'admin', 'password': 'admin123'})
            comprobar('credencial por defecto rechazada', r.status == 401)

            r, t = peticion(sock, 'POST', '/api/login', {'username': 'admin', 'password': CLAVE})
            cookie_cruda = r.getheader('Set-Cookie') or ''
            comprobar('login correcto', r.status == 200)
            comprobar('cookie HttpOnly + Secure + SameSite=Lax',
                      all(x in cookie_cruda for x in ('HttpOnly', 'Secure', 'SameSite=Lax')))
            cookie = cookie_cruda.split(';')[0]

            r, t = peticion(sock, 'GET', '/api/sesion', cookie=cookie)
            comprobar('sesión vigente entre peticiones y workers', r.status == 200 and json.loads(t)['usuario']['rol'] == 'ADMIN')
            r, _ = peticion(sock, 'GET', '/api/empleados', cookie=cookie)
            comprobar('API con sesión => 200', r.status == 200)
            r, _ = peticion(sock, 'POST', '/api/empleados', {
                'dpi': '2540123450101', 'fecha': '2026-01-01', 'nombre': 'ANA PRUEBA', 'cargo': 'ANALISTA',
                'sueldo': 5000}, cookie=cookie)
            comprobar('guardar empleado persiste en la BD', r.status == 200)
            r, t = peticion(sock, 'GET', '/api/empleados', cookie=cookie)
            comprobar('empleado visible desde cualquier worker', any(e['nombre'] == 'ANA PRUEBA' for e in json.loads(t)))
            r, t = peticion(sock, 'POST', '/api/empleados', {'dpi': '1', 'nombre': '<script>'}, cookie=cookie)
            comprobar('entrada maliciosa => 400 sin detalle interno', r.status == 400 and 'Traceback' not in t)

            r, t = peticion(sock, 'POST', '/api/recuperar/solicitar', {'correo': 'nadie@ejemplo.gt'})
            comprobar('recuperación: respuesta uniforme', r.status == 200)
            r, t = peticion(sock, 'POST', '/api/recuperar/confirmar',
                            {'correo': 'admin@ejemplo.gt', 'codigo': '000000', 'nueva_password': 'Nueva-Clave-123'})
            comprobar('recuperación: código inválido => 400', r.status == 400)

            r, _ = peticion(sock, 'POST', '/api/logout', cookie=cookie)
            comprobar('logout', r.status == 200)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            shutil.rmtree(dir_sock, ignore_errors=True)
            salida = proc.stdout.read() if proc.stdout else ''
            if salida.strip():
                print('--- salida de gunicorn ---')
                print(salida[-1500:])

    print('\nRESULTADO:', 'FALLOS: ' + ', '.join(fallos) if fallos else 'todas las comprobaciones pasaron')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
