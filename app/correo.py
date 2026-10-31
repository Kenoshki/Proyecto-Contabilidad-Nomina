"""Envío del código de recuperación por la API HTTP de EmailJS (llamada desde el servidor).

Railway restringe SMTP saliente en planes Free/Hobby, por eso se usa HTTPS. Requiere en EmailJS
(Account → Security) activar "Allow EmailJS API for non-browser applications" y usar la Private Key.
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

URL_EMAILJS = 'https://api.emailjs.com/api/v1.0/email/send'
VARIABLES = ('EMAILJS_SERVICE_ID', 'EMAILJS_TEMPLATE_OTP', 'EMAILJS_PUBLIC_KEY', 'EMAILJS_PRIVATE_KEY')


def correo_configurado():
    return all(os.environ.get(v) for v in VARIABLES)


def enviar_codigo_recuperacion(destino, codigo, minutos):
    """Devuelve True si el correo fue entregado al proveedor."""
    if not correo_configurado():
        if os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true'):
            # Solo desarrollo local: sin proveedor configurado el código se muestra en la consola
            logger.warning("[DESARROLLO] Código de recuperación para %s: %s", destino, codigo)
            return True
        logger.error("Recuperación de contraseña sin proveedor de correo: defina %s", ', '.join(VARIABLES))
        return False

    carga = {
        'service_id': os.environ['EMAILJS_SERVICE_ID'],
        'template_id': os.environ['EMAILJS_TEMPLATE_OTP'],
        'user_id': os.environ['EMAILJS_PUBLIC_KEY'],
        'accessToken': os.environ['EMAILJS_PRIVATE_KEY'],
        'template_params': {
            'to_email': destino,
            'otp_code': codigo,
            'tiempo_limite': f'{minutos} minutos',
        },
    }
    peticion = urllib.request.Request(
        URL_EMAILJS, data=json.dumps(carga).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        # URL constante con esquema https (no controlada por el usuario)
        with urllib.request.urlopen(peticion, timeout=10) as resp:  # nosec B310
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        logger.error("EmailJS rechazó el envío (HTTP %s): %s", e.code, e.read(300))
    except (urllib.error.URLError, TimeoutError) as e:
        logger.error("No se pudo contactar a EmailJS: %s", e)
    return False
