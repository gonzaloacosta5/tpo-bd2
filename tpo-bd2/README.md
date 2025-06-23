
# TPO-BD2

Crear un entorno virtual:
python -m venv venv
#env es el nombre del entorno

Activar el entorno virtual:
source venv/bin/activate #Mac/Linux
venv\Scripts\activate #Windows

Instalar librerías:
pip install -r requirements.txt

Configurar variables de entorno según .env.template

Inicializar bases de datos (MongoDB, Redis, Cassandra)

Ejecutar:
uvicorn app.main:app --reload
