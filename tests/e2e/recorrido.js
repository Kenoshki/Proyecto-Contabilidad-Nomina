const puppeteer = require('puppeteer-core');
const fs = require('fs');

const BASE = 'http://localhost:5055/';
// Recorrido completo en navegador real (Edge/Chrome).
// Requisitos: `npm install` en esta carpeta y `python tests/e2e/servidor.py` en marcha.
// Uso: node tests/e2e/recorrido.js   (NAVEGADOR=<ruta a chrome/edge> para otro ejecutable)
const path = require('path');
const CSV = path.join(__dirname, '..', '..', 'tools', 'salida', 'credenciales_estudiantes.csv');
const EDGE = process.env.NAVEGADOR || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const ADMIN = ['admin', 'Admin-Clave-E2E-1'];
const cuentas = fs.readFileSync(CSV, 'utf8').trim().split(/\r?\n/).slice(1).map(l => l.split(','));

const resultados = [];
const erroresPagina = [];
const respuestasMalas = [];
function check(nombre, ok, detalle) {
  resultados.push([nombre, !!ok]);
  console.log((ok ? 'OK   ' : 'FALLA') + ' ' + nombre + (detalle !== undefined ? '  -> ' + detalle : ''));
}
const esperar = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({ executablePath: EDGE, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 900 });
  page.on('pageerror', e => erroresPagina.push(String(e.message || e)));
  page.on('dialog', d => d.accept());
  page.on('response', r => {
    const u = r.url();
    if (u.startsWith(BASE + 'api/') && r.status() >= 400) respuestasMalas.push(`${r.request().method()} ${u.replace(BASE, '/')} ${r.status()}`);
  });
  const visible = sel => page.$eval(sel, el => !el.classList.contains('hidden'));
  const notif = () => page.$eval('#notif-title', el => el.innerText).catch(() => '');
  async function esperarNotif(titulo, ms = 8000) {
    await page.waitForFunction(t => document.getElementById('notif-title').innerText === t &&
      !document.getElementById('modal-notificacion').classList.contains('hidden'), { timeout: ms }, titulo);
  }
  async function cerrarNotif() { await page.evaluate(() => cerrarNotificacion()); }
  async function login(u, p) {
    await page.$eval('#login-user', el => (el.value = ''));
    await page.$eval('#login-pass', el => (el.value = ''));
    await page.type('#login-user', u);
    await page.type('#login-pass', p);
    await page.click('#modal-login button[type=submit]');
  }
  async function esperarSesion(nombre) {
    await page.waitForFunction(n => document.getElementById('current-user-display').innerText === n &&
      document.getElementById('modal-login').classList.contains('hidden'), { timeout: 15000 }, nombre);
  }

  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: 'domcontentloaded' });
  await esperar(500);
  check('1. al abrir se exige iniciar sesión', await page.$eval('#modal-login', el => !el.classList.contains('hidden')));

  // ---- credenciales incorrectas
  await login('est01', 'incorrecta-123');
  await page.waitForSelector('#login-error-msg:not(.hidden)', { timeout: 8000 });
  check('2. credencial incorrecta muestra el error', await visible('#login-error-msg'));

  // ---- olvidé mi contraseña (interfaz)
  await page.evaluate(() => abrirModalRecuperacion());
  check('3a. modal de recuperación se abre', await page.$eval('#modal-recuperar', el => el.classList.contains('flex') && !el.classList.contains('hidden')));
  await page.type('#email-recuperacion', 'est01@estudiantes.invalid');
  await page.click('#btn-enviar-recuperacion');
  await page.waitForSelector('#paso-codigo-admin:not(.hidden)', { timeout: 8000 });
  check('3b. paso 2 (código + nueva contraseña) aparece', await visible('#paso-codigo-admin') && !(await visible('#paso-correo')));
  await page.type('#input-codigo-otp', '000000');
  await page.type('#input-nueva-pass', 'Nueva-Clave-9876');
  await page.type('#input-repetir-pass', 'Nueva-Clave-9876');
  await page.click('#btn-confirmar-recuperacion');
  await esperarNotif('No se pudo restablecer');
  check('3c. código incorrecto muestra mensaje claro y visible sobre el modal', (await notif()) === 'No se pudo restablecer');
  await cerrarNotif();
  await page.evaluate(() => cerrarModalRecuperacion());

  // ---- estudiante 1
  await login(cuentas[0][0], cuentas[0][1]);
  await esperarSesion('EST01');
  check('4. login de estudiante', true);
  check('4b. rol RRHH visible', (await page.$eval('#current-role-badge', el => el.innerText)) === 'RRHH');
  const n = await page.evaluate(() => dbEmpleados.length);
  check('5. se cargaron 100 empleados ficticios', n === 100, n);
  check('5b. hay ex-empleados y horas extra de ejemplo', await page.evaluate(() => dbExEmpleados.length >= 5 && Object.keys(dbAsistencia).length >= 20));
  check('5c. el menú de usuarios está oculto para RRHH', !(await page.$eval('#btn-nav-usuarios', el => !el.classList.contains('hidden'))));

  // ---- recorrer todas las pantallas
  const vistas = ['dashboard', 'empleados', 'extranjeros', 'locales', 'directorio', 'planillas', 'asistencia', 'departamentos', 'reportes', 'ley-gt', 'bajas', 'ex-empleados'];
  const antes = erroresPagina.length;
  for (const v of vistas) {
    await page.evaluate(x => navegarA(x), v);
    await esperar(150);
    const ok = await page.$eval('#view-' + v, el => !el.classList.contains('hidden')).catch(() => false);
    check('6. pantalla "' + v + '" se muestra', ok);
  }
  check('6b. ninguna pantalla produjo errores de JavaScript', erroresPagina.length === antes, erroresPagina.slice(antes).join(' | '));

  const filas = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('tbody[id]')].map(t => [t.id, t.children.length])));
  console.log('     filas por tabla:', JSON.stringify(filas));
  check('7. tablas de locales y extranjeros reflejan los 100 empleados',
    (filas['tbody-locales'] || 0) === 78 && (filas['tbody-extranjeros'] || 0) === 22, `${filas['tbody-locales']}/${filas['tbody-extranjeros']}`);

  // ---- planilla y asistencia
  await page.evaluate(() => { navegarA('planillas'); procesarCalculoPlanilla(); });
  await esperar(300);
  const totalPlanilla = await page.evaluate(() => document.body.innerText.match(/Q\s?[\d,]+\.\d{2}/g)?.length || 0);
  check('8. la planilla calcula montos para el grupo', totalPlanilla > 50, totalPlanilla + ' montos');
  await page.evaluate(() => { navegarA('asistencia'); generarTablaAsistencia(); });
  await esperar(300);
  await page.evaluate(() => guardarAsistencia());
  await esperarNotif('Asistencia Guardada');
  check('9. guardar asistencia / horas extra', true);
  await cerrarNotif();

  // ---- baja de punta a punta (llama a /api/baja con el formato real de la pantalla)
  const dpiBaja = await page.evaluate(() => dbEmpleados[3].dpi);
  await page.evaluate(d => { navegarA('bajas'); seleccionarEmpleadoBaja(d); }, dpiBaja);
  await esperar(300);
  const totalTxt = await page.$eval('#doc-tbl-total', el => el.innerText);
  console.log('     total liquidado en pantalla:', JSON.stringify(totalTxt));
  await page.evaluate(() => ejecutarDarDeBaja());
  await esperarNotif('Baja Procesada').catch(() => {});
  const titulo = await notif();
  check('10. dar de baja un empleado termina bien en el servidor', titulo === 'Baja Procesada', titulo);
  const conteos = await page.evaluate(() => [dbEmpleados.length, dbExEmpleados.length]);
  check('10b. el empleado pasa de activos a ex-empleados', conteos[0] === 99 && conteos[1] === 7, conteos.join('/'));
  const enServidor = await page.evaluate(async () => (await (await fetch('/api/ex-empleados')).json()).length);
  check('10c. la baja quedó registrada en la base de datos', enServidor === 1, enServidor);
  await cerrarNotif();

  // ---- la sesión y los cambios sobreviven a recargar
  await page.reload({ waitUntil: 'domcontentloaded' });
  await esperarSesion('EST01');
  const trasRecargar = await page.evaluate(() => dbEmpleados.length);
  check('11. al recargar se conserva la sesión y los cambios del estudiante', trasRecargar === 99, trasRecargar);

  // ---- otro estudiante en el mismo navegador recibe datos limpios
  await page.evaluate(() => cerrarSesion());
  await esperar(500);
  check('12a. cerrar sesión vuelve a pedir credenciales', await page.$eval('#modal-login', el => !el.classList.contains('hidden')));
  const sinSesion = await page.evaluate(async () => (await fetch('/api/empleados')).status);
  check('12b. tras cerrar sesión la API responde 401', sinSesion === 401, sinSesion);
  await login(cuentas[1][0], cuentas[1][1]);
  await esperarSesion('EST02');
  const n2 = await page.evaluate(() => [dbEmpleados.length, dbExEmpleados.length]);
  check('12c. el estudiante 2 en el mismo equipo recibe un conjunto limpio de 100', n2[0] === 100 && n2[1] === 6, n2.join('/'));

  // ---- administrador: usuarios
  await page.evaluate(() => cerrarSesion());
  await esperar(300);
  await login(ADMIN[0], ADMIN[1]);
  await esperarSesion('ADMIN');
  check('13a. el administrador ve el menú de usuarios', await page.$eval('#btn-nav-usuarios', el => !el.classList.contains('hidden')));
  await page.evaluate(() => navegarA('usuarios'));
  await esperar(300);
  const filasUsr = await page.$$eval('#tbody-usuarios tr', t => t.length);
  check('13b. la tabla lista admin + 20 estudiantes', filasUsr === 21, filasUsr);
  const camposPass = await page.$$eval('#tbody-usuarios input[type=password]', t => t.length);
  check('13c. la tabla no muestra campos de contraseña', camposPass === 0, camposPass);
  await page.type('#usr-username', 'profesor1');
  await page.type('#usr-email', 'profesor1@ejemplo.gt');
  await page.type('#usr-password', 'Profesor-Clave-2026');
  await page.$eval('#view-usuarios form', f => f.requestSubmit());
  await esperarNotif('Usuario Creado');
  check('13d. crear usuario desde la pantalla', true);
  await cerrarNotif();
  const filasUsr2 = await page.$$eval('#tbody-usuarios tr', t => t.length);
  check('13e. el usuario nuevo aparece en la tabla', filasUsr2 === 22, filasUsr2);
  await page.evaluate(() => eliminarUsuario(dbUsuarios.findIndex(u => u.username === 'profesor1')));
  await esperar(800);
  check('13f. eliminar usuario', (await page.$$eval('#tbody-usuarios tr', t => t.length)) === 21);

  // ---- Mi perfil (admin) y reautenticación
  await page.evaluate(() => abrirModalMiPerfil());
  await page.type('#perfil-pass-actual', ADMIN[1]);
  await page.$eval('#modal-mi-perfil form', f => f.requestSubmit());
  await esperarNotif('Perfil Actualizado');
  check('14. Mi Perfil guarda con la contraseña actual', true);
  await cerrarNotif();

  console.log('\n     respuestas de API >= 400 (esperadas: 401 sin sesión, 400 del código falso):');
  respuestasMalas.forEach(r => console.log('       ' + r));
  console.log('     errores de JavaScript en la página:', erroresPagina.length ? erroresPagina.join(' | ') : 'ninguno');
  check('15. sin errores de JavaScript durante todo el recorrido', erroresPagina.length === 0);

  await browser.close();
  const fallos = resultados.filter(r => !r[1]);
  console.log(`\nRESULTADO: ${resultados.length - fallos.length}/${resultados.length} comprobaciones` + (fallos.length ? ' | FALLAN: ' + fallos.map(f => f[0]).join('; ') : ''));
  process.exit(fallos.length ? 1 : 0);
})().catch(e => { console.error('ERROR DEL SCRIPT:', e); process.exit(2); });
