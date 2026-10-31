import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    # SEGURIDAD ISO 25010: El depurador solo se activa mediante variable de entorno explícita
    modo_debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1']
    puerto = int(os.environ.get('PORT', 5000))
    
    # Solo desarrollo local. En producción se sirve con gunicorn (ver Procfile)
    app.run(host=os.environ.get('HOST', '127.0.0.1'), debug=modo_debug, port=puerto)