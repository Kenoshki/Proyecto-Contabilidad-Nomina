"""Genera app/demo_data/demo.json: 100 empleados FICTICIOS + ex-empleados y horas extra de ejemplo.

Determinista (semilla fija): ejecutarlo de nuevo produce el mismo archivo.
Los nombres, DPI, NIT, teléfonos y pasaportes son sintéticos; cualquier coincidencia con personas reales es casual.

Uso:  python tools/generar_datos_demo.py
"""
import json
import os
import random

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, 'app', 'demo_data', 'demo.json')
random.seed(20261031)

NOMBRES_M = ['JOSE', 'LUIS', 'CARLOS', 'JUAN', 'MARIO', 'PEDRO', 'ERICK', 'DIEGO', 'ALEJANDRO', 'FERNANDO',
             'HECTOR', 'OSCAR', 'RICARDO', 'SERGIO', 'DANIEL', 'ANDRES', 'MANUEL', 'ROBERTO', 'EDGAR', 'JORGE']
NOMBRES_F = ['MARIA', 'ANA', 'SONIA', 'CLAUDIA', 'LUCIA', 'GLORIA', 'KARLA', 'PATRICIA', 'ANDREA', 'ROSA',
             'DIANA', 'MONICA', 'SILVIA', 'BRENDA', 'WENDY', 'ISABEL', 'CARMEN', 'LETICIA', 'MIRIAM', 'VERONICA']
APELLIDOS = ['LOPEZ', 'GARCIA', 'MARTINEZ', 'PEREZ', 'GONZALEZ', 'RODRIGUEZ', 'HERNANDEZ', 'RAMIREZ', 'MORALES',
             'CASTILLO', 'FLORES', 'RIVAS', 'FIGUEROA', 'MENDOZA', 'CRUZ', 'REYES', 'ORTIZ', 'SANTOS', 'JIMENEZ',
             'ALVARADO', 'CHAVEZ', 'ESCOBAR', 'PORTILLO', 'SANDOVAL', 'MEJIA', 'VASQUEZ', 'TORRES', 'ARRIAGA',
             'BARRIOS', 'CONTRERAS', 'ESTRADA', 'GUZMAN', 'HERRERA', 'IXCOY', 'LEMUS', 'MAZARIEGOS', 'OROZCO', 'PAIZ']
EXTRANJEROS = [('Estados Unidos', 'EEUU'), ('Mexico', 'MEX'), ('Colombia', 'COL'), ('Espana', 'ESP'),
               ('Argentina', 'ARG'), ('Chile', 'CHL'), ('Costa Rica', 'CRI'), ('El Salvador', 'SLV')]
NOMBRES_X_M = ['MICHAEL', 'DAVID', 'JAVIER', 'SANTIAGO', 'MATIAS', 'ANDRE', 'THOMAS']
NOMBRES_X_F = ['SARAH', 'LAURA', 'VALENTINA', 'CAMILA', 'LUCIANA', 'EMILY', 'PAULA']

# departamento -> (cargos, rango salarial GTQ)
DEPTOS = {
    'DESARROLLO': (['PROGRAMADOR', 'INGENIERO DE SOFTWARE', 'ANALISTA QA', 'ARQUITECTO DE SOFTWARE', 'DEVOPS'], (6500, 18000)),
    'DISEÑO': (['DISEÑADOR GRAFICO', 'DISEÑADOR UX/UI', 'ILUSTRADOR DIGITAL'], (4500, 10500)),
    'VENTAS': (['EJECUTIVO DE VENTAS', 'SUPERVISOR DE VENTAS', 'GERENTE DE CUENTA', 'ASESOR COMERCIAL'], (3800, 12500)),
    'ATENCION AL CLIENTE': (['AGENTE DE SOPORTE', 'SUPERVISOR DE CALL CENTER', 'EJECUTIVO DE SERVICIO'], (3700, 7500)),
    'ADMINISTRACION': (['ASISTENTE ADMINISTRATIVO', 'RECEPCIONISTA', 'COORDINADOR DE RRHH', 'GERENTE ADMINISTRATIVO'], (3700, 15000)),
    'MERCADEO': (['ANALISTA DE MERCADEO', 'COMMUNITY MANAGER', 'JEFE DE MERCADEO'], (4200, 11500)),
    'CONTABILIDAD': (['AUXILIAR CONTABLE', 'CONTADOR GENERAL', 'ANALISTA FINANCIERO', 'TESORERO'], (4200, 14500)),
}
ZONAS = ['ZONA 1', 'ZONA 4', 'ZONA 7', 'ZONA 9', 'ZONA 10', 'ZONA 11', 'ZONA 12', 'ZONA 14', 'ZONA 15', 'ZONA 18']
MUNICIPIOS = ['CIUDAD DE GUATEMALA', 'MIXCO', 'VILLA NUEVA', 'SAN MIGUEL PETAPA', 'SANTA CATARINA PINULA']
COLORES = ['3b82f6', '10b981', '8b5cf6', 'f59e0b', 'ef4444', '14b8a6', 'ec4899']
ESTADOS = ['Soltero', 'Casado', 'Unido', 'Divorciado']
ENFERMEDADES = ['DIABETES CONTROLADA', 'HIPERTENSION', 'ASMA', 'ALERGIA A PENICILINA', 'INCAPACIDAD PARCIAL']


def telefono(prefijos):
    return f"{random.choice(prefijos)}{random.randint(100, 999)}-{random.randint(1000, 9999)}"


def nit():
    n = random.randint(100000, 9999999)
    return f"{n}-{random.choice('0123456789K')}"


def dpi_ficticio(usados):
    while True:
        # Serie sintética 9xxxxxxx + verificador + código de municipio 0101 (no corresponde a personas reales)
        d = f"9{random.randint(1000000, 9999999)}{random.randint(0, 9)}0101"
        if d not in usados:
            usados.add(d)
            return d


def foto(nombre, color):
    iniciales = '+'.join(nombre.split()[:2])
    return f"https://placehold.co/150x180/{color}/ffffff?text={iniciales}"


def fecha(anio_min=2019, anio_max=2026):
    a = random.randint(anio_min, anio_max)
    m = random.randint(1, 10 if a == 2026 else 12)
    d = random.randint(1, 28)
    return f"{a}-{m:02d}-{d:02d}"


def nacimiento():
    return f"{random.randint(1968, 2003)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def empleado(codigo, extranjero, usados):
    mujer = random.random() < 0.5
    if extranjero:
        nombre_pila = random.choice(NOMBRES_X_F if mujer else NOMBRES_X_M)
        pais, sigla = random.choice(EXTRANJEROS)
        documento = f"{sigla[0]}{random.randint(10000000, 99999999)}"
        usados.add(documento)
        visa = random.choice(['Visa V-3', 'Visa V-1', 'Residente Temporal', 'Residente Permanente'])
    else:
        nombre_pila = random.choice(NOMBRES_F if mujer else NOMBRES_M)
        pais, visa = 'Guatemala', ''
        documento = dpi_ficticio(usados)
    nombre = f"{nombre_pila} {random.choice(APELLIDOS)} {random.choice(APELLIDOS)}"
    depto = random.choice(list(DEPTOS))
    cargos, (smin, smax) = DEPTOS[depto]
    if extranjero:
        moneda, sueldo = 'USD', float(random.randrange(1200, 4600, 50))
    else:
        moneda, sueldo = 'GTQ', float(random.randrange(smin, smax + 1, 50))
    estado = random.choice(ESTADOS)
    con_pareja = estado in ('Casado', 'Unido')
    pareja = ''
    if con_pareja:
        pareja = f"{random.choice(NOMBRES_M if mujer else NOMBRES_F)} {nombre.split()[1]}"
    sueldo_gtq = sueldo * (7.8 if moneda == 'USD' else 1)
    return {
        'codigo': codigo,
        'fechaNacimiento': nacimiento(),
        'fecha': fecha(),
        'nombre': nombre,
        'direccion': f"{random.choice(ZONAS)}, {random.choice(MUNICIPIOS)}" if not extranjero else f"{random.choice(ZONAS)}, CIUDAD DE GUATEMALA",
        'telefono': telefono('2'),
        'celular': telefono('345'),
        'dpi': documento,
        'nit': nit(),
        'senales': 'NINGUNA',
        'enfermedad': random.choice(ENFERMEDADES) if random.random() < 0.08 else 'NINGUNA',
        'empresa': 'TECNIMARKET S.A. DE GUATEMALA',
        'departamento': depto,
        'cargo': random.choice(cargos),
        'tipoOrigen': 'EXTRANJERO' if extranjero else 'LOCAL',
        'pais': pais,
        'visa': visa,
        'moneda': moneda,
        'sueldo': sueldo,
        'tipoPago': 'Mensual',
        'aplicaIgss': random.random() > 0.04,
        'aplicaBono': random.random() > 0.10,
        'aplicaIsr': sueldo_gtq > 7000,
        'estadoCivil': estado,
        'hijos': random.choice([0, 0, 1, 1, 2, 2, 3, 4]) if estado != 'Soltero' else random.choice([0, 0, 0, 1]),
        'conyuge': pareja,
        'telConyuge': telefono('345') if con_pareja else '',
        'foto': foto(nombre, random.choice(COLORES)),
    }


def main():
    usados = set()
    empleados = []
    for i in range(1, 79):
        empleados.append(empleado(f"E{i:03d}", False, usados))
    for i in range(1, 23):
        empleados.append(empleado(f"P{i:03d}", True, usados))

    # Casos de borde visibles en el escenario
    empleados[4].update(sueldo=3700.0, aplicaIsr=False, aplicaBono=True, hijos=0)        # salario mínimo
    empleados[9].update(sueldo=18000.0, aplicaIsr=True, cargo='GERENTE GENERAL')          # salario alto, ISR
    empleados[14].update(aplicaIgss=False)                                                # sin IGSS
    empleados[19].update(hijos=5, estadoCivil='Casado')                                   # familia numerosa

    # Horas extra ya registradas para ~30 colaboradores
    asistencia = {}
    for e in random.sample(empleados, 30):
        horas = random.choice([2, 3, 4, 5, 6, 8, 10, 12])
        tarifa = random.choice([20.0, 25.0, 30.0, 35.0])
        aplica = random.random() > 0.15
        asistencia[e['dpi']] = {'horasExtra': float(horas), 'tarifa': tarifa, 'aplicaPago': aplica,
                                'montoTotal': float(horas * tarifa) if aplica else 0.0}

    # Ex-empleados de ejemplo (bajas históricas)
    ex = []
    causales = ['RENUNCIA', 'DESPIDO_JUSTIFICADO', 'DESPIDO_INJUSTIFICADO', 'RENUNCIA', 'RENUNCIA', 'DESPIDO_JUSTIFICADO']
    for i, causal in enumerate(causales):
        e = empleado(f"E{900 + i}", False, usados)
        monto = round(random.uniform(3500, 21000), 2)
        ex.append({
            'id': 1700000000000 + i, 'dpi': e['dpi'], 'codigo': e['codigo'], 'nombre': e['nombre'],
            'departamento': e['departamento'], 'cargo': e['cargo'], 'causalSalida': causal,
            'fechaSalida': f"2026-{random.randint(1, 9):02d}-{random.randint(1, 28):02d}",
            'montoLiquidado': f"Q {monto:,.2f}", 'foto': e['foto'],
        })

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'empleados': empleados, 'exEmpleados': ex, 'asistencia': asistencia},
                  f, ensure_ascii=False, indent=1)
    locales = sum(1 for e in empleados if e['tipoOrigen'] == 'LOCAL')
    print(f"{len(empleados)} empleados ({locales} locales, {len(empleados) - locales} extranjeros), "
          f"{len(ex)} ex-empleados, {len(asistencia)} registros de horas extra -> {SALIDA}")


if __name__ == '__main__':
    main()
