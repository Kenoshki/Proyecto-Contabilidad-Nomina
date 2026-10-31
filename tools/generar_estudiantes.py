"""Genera las cuentas de estudiantes para un examen/demostración.

Crea:
  - app/demo_data/estudiantes.json : usuario, correo, rol, permisos y HASH de la contraseña (esto sí se despliega).
  - tools/salida/credenciales_estudiantes.csv : usuario + contraseña en claro (SOLO para entregar a los estudiantes;
    está en .gitignore y no debe subirse ni desplegarse).

Uso:  python tools/generar_estudiantes.py [cantidad]      (por defecto 20)
Las cuentas se cargan al arrancar con SEED_ESTUDIANTES=1.
"""
import csv
import json
import os
import secrets
import sys

from werkzeug.security import generate_password_hash

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA_JSON = os.path.join(RAIZ, 'app', 'demo_data', 'estudiantes.json')
SALIDA_CSV = os.path.join(RAIZ, 'tools', 'salida', 'credenciales_estudiantes.csv')
# Sin caracteres ambiguos (0/O, 1/l/I)
ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
PERMISOS = 'dashboard,empleados,locales,extranjeros,directorio,planillas,asistencia,departamentos,reportes,ley-gt,bajas,ex-empleados'


def clave():
    while True:
        c = ''.join(secrets.choice(ALFABETO) for _ in range(12))
        if any(x.isdigit() for x in c) and any(x.isalpha() for x in c):
            return c


def main():
    cantidad = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    cuentas, filas = [], []
    for i in range(1, cantidad + 1):
        usuario, password = f"est{i:02d}", clave()
        cuentas.append({'username': usuario, 'correo': f"{usuario}@estudiantes.invalid", 'rol': 'RRHH',
                        'permisos': PERMISOS, 'password_hash': generate_password_hash(password)})
        filas.append((usuario, password))
    os.makedirs(os.path.dirname(SALIDA_JSON), exist_ok=True)
    os.makedirs(os.path.dirname(SALIDA_CSV), exist_ok=True)
    with open(SALIDA_JSON, 'w', encoding='utf-8') as f:
        json.dump(cuentas, f, indent=1)
    with open(SALIDA_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['usuario', 'contrasena'])
        w.writerows(filas)
    print(f"{cantidad} cuentas -> {SALIDA_JSON}\nCredenciales para entregar -> {SALIDA_CSV}")


if __name__ == '__main__':
    main()
