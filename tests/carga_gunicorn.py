"""Prueba de carga: N estudiantes simultáneos contra gunicorn (socket Unix, sin red).

Uso:  python tests/carga_gunicorn.py [estudiantes] [rondas]       (por defecto 20 y 8)
Requiere haber generado las cuentas (tools/generar_estudiantes.py). Cada estudiante inicia sesión a la vez
(pico de arranque del examen) y luego repite: sesión, datos de demostración, empleados, departamentos,
asistencia y una baja.
"""
import csv
import http.client
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(RAIZ, 'tools', 'salida', 'credenciales_estudiantes.csv')


class ConexionUnix(http.client.HTTPConnection):
    def __init__(self, ruta):
        super().__init__('localhost', timeout=30)
        self.ruta = ruta

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(self.ruta)


def main():
    threading.stack_size(512 * 1024)   # 20 hilos cliente caben holgadamente en sandboxes con límite de memoria virtual
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rondas = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    with open(CSV, encoding='utf-8') as f:
        cuentas = [(r['usuario'], r['contrasena']) for r in csv.DictReader(f)][:n]

    dir_sock = tempfile.mkdtemp(prefix='gsock', dir='/tmp' if os.path.isdir('/tmp') else None)
    sock = os.path.join(dir_sock, 'g.sock')
    entorno = {'PATH': os.environ.get('PATH', ''), 'HOME': dir_sock, 'SECRET_KEY': 'k' * 40, 'ADMIN_PASSWORD': 'Admin-Carga-12345',
               'ADMIN_EMAIL': 'admin@carga.gt', 'SEED_ESTUDIANTES': '1', 'DEMO_DATA': '1', 'PROXY_HOPS': '1',
               'LOGIN_MAX_INTENTOS': '10', 'DATABASE_PATH': os.path.join(dir_sock, 'datos', 'c.db')}
    proc = subprocess.Popen([sys.executable, '-m', 'gunicorn', 'run:app', '--bind', f'unix:{sock}', '--workers', '2',
                             '--threads', '4', '--timeout', '60', '--worker-tmp-dir', dir_sock, '--log-level', 'warning'],
                            cwd=RAIZ, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    latencias, errores = [], []
    lock = threading.Lock()
    salida_barrera = threading.Barrier(n)

    def llamar(c, metodo, ruta, cuerpo=None, cookie=None, etiqueta=None):
        cab = {'X-Forwarded-For': '190.0.0.1', 'X-Forwarded-Proto': 'https'}   # todos desde la misma IP (NAT del laboratorio)
        if cookie:
            cab['Cookie'] = cookie
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo)
            cab['Content-Type'] = 'application/json'
        t0 = time.perf_counter()
        c.request(metodo, ruta, body=datos, headers=cab)
        r = c.getresponse()
        cuerpo_resp = r.read()
        dt = time.perf_counter() - t0
        with lock:
            latencias.append((etiqueta or ruta, dt))
            if r.status >= 400:
                errores.append(f"{metodo} {ruta} -> {r.status}")
        return r, cuerpo_resp

    def estudiante(i):
        usuario, clave = cuentas[i]
        try:
            salida_barrera.wait(timeout=30)
            c = ConexionUnix(sock)
            r, _ = llamar(c, 'POST', '/api/login', {'username': usuario, 'password': clave}, etiqueta='login')
            cookie = (r.getheader('Set-Cookie') or '').split(';')[0]
            _, demo = llamar(c, 'GET', '/api/demo/datos', cookie=cookie, etiqueta='demo (90 KB)')
            empleados = json.loads(demo)['empleados']
            for k in range(rondas):
                llamar(c, 'GET', '/api/sesion', cookie=cookie, etiqueta='sesion')
                llamar(c, 'GET', '/api/empleados', cookie=cookie, etiqueta='empleados')
                llamar(c, 'GET', '/api/departamentos', cookie=cookie, etiqueta='departamentos')
                llamar(c, 'GET', '/api/asistencia', cookie=cookie, etiqueta='asistencia')
                e = empleados[(i * rondas + k) % len(empleados)]
                llamar(c, 'POST', '/api/baja', {'dpi': e['dpi'], 'codigo': e['codigo'], 'nombre': e['nombre'],
                       'departamento': e['departamento'], 'cargo': e['cargo'], 'causalSalida': 'RENUNCIA',
                       'fechaSalida': '2026-10-31', 'montoLiquidado': 'Q 5,000.00', 'foto': e['foto']},
                       cookie=cookie, etiqueta='baja (escritura)')
            llamar(c, 'POST', '/api/logout', cookie=cookie, etiqueta='logout')
            c.close()
        except Exception as exc:  # noqa: BLE001
            with lock:
                errores.append(f"{usuario}: {type(exc).__name__}: {exc}")

    try:
        for _ in range(100):
            if os.path.exists(sock) or proc.poll() is not None:
                break
            time.sleep(0.1)
        time.sleep(0.5)
        t0 = time.perf_counter()
        hilos = [threading.Thread(target=estudiante, args=(i,)) for i in range(n)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=180)
        total = time.perf_counter() - t0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(dir_sock, ignore_errors=True)

    print(f"{n} estudiantes simultáneos x {rondas} rondas = {len(latencias)} peticiones en {total:.1f} s "
          f"({len(latencias) / total:.0f} peticiones/s)")
    por_tipo = {}
    for etiqueta, dt in latencias:
        por_tipo.setdefault(etiqueta, []).append(dt * 1000)
    print(f"{'operación':<22}{'n':>6}{'p50 ms':>9}{'p95 ms':>9}{'máx ms':>9}")
    for etiqueta, v in sorted(por_tipo.items()):
        v.sort()
        p95 = v[min(len(v) - 1, int(len(v) * 0.95))]
        print(f"{etiqueta:<22}{len(v):>6}{statistics.median(v):>9.0f}{p95:>9.0f}{max(v):>9.0f}")
    print(f"errores: {len(errores)}" + (" -> " + "; ".join(sorted(set(errores))[:8]) if errores else ""))
    todas = [dt * 1000 for _, dt in latencias]
    todas.sort()
    p95_global = todas[int(len(todas) * 0.95)]
    ok = not errores and p95_global < 2000
    print(f"RESULTADO: {'APROBADO' if ok else 'NO APROBADO'} (p95 global {p95_global:.0f} ms; umbral 2000 ms)")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
