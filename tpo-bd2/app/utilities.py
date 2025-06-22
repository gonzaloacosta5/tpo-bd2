from pymongo import MongoClient
from os import environ
import redis
from cassandra.cluster import Cluster
from datetime import datetime
from dotenv import load_dotenv
from fastapi import HTTPException
import re

load_dotenv()

MONGO_URI = "mongodb://localhost:27017"
mongo_client = MongoClient(MONGO_URI)
mongo = mongo_client["mi_basedatos"]

REDIS_HOST = "localhost"
REDIS_PORT = 6379
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

cassandra_host = environ.get("CASSANDRA_HOST", "127.0.0.1")
cassandra = Cluster([cassandra_host], port=9042)
session = cassandra.connect()

session.execute("""
    CREATE KEYSPACE IF NOT EXISTS usuarios
    WITH replication = {'class': 'SimpleStrategy', 'replication_factor': '1'}
""")
session.set_keyspace('usuarios')
session.execute("""
    CREATE TABLE IF NOT EXISTS user_activity_log (
        user_id TEXT,
        event_time TIMESTAMP,
        event_type TEXT,
        carrito TEXT,
        PRIMARY KEY (user_id, event_time)
    ) WITH CLUSTERING ORDER BY (event_time DESC)
""")

def user_activity_log(user_id, evento, carrito):
    try:
        query = """
            INSERT INTO user_activity_log (user_id, event_time, event_type, carrito)
            VALUES (%s, %s, %s, %s)
        """
        session.execute(query, (str(user_id), datetime.now(), evento, str(carrito)))
        return True
    except Exception as e:
        print(f"Error logeo de usuario: {e}")
        return False

def chek_user_id(user_id):
    user = mongo.users.find_one({"_id": int(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario inexistente")
    session_redis = redis_client.hget(f"user:{str(user_id)}", "user")
    if not session_redis:
        raise HTTPException(status_code=404, detail="Usuario no logeado")
    return user

def get_next_user_id():
    counters = mongo.counters
    ret = counters.find_one_and_update(
        {"_id": "userId"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True
    )
    return ret["seq"]

async def obtener_stock_producto(idProducto: str) -> int:
    collection = mongo.products
    try:
        producto = collection.find_one(
            {"_id": int(idProducto), "disable_date": None},
            {"stock": 1, "_id": 0}
        )
        if not producto:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return producto.get("stock", 0)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def obtener_ultimo_carrito(user_id):
    try:
        query = """
            SELECT carrito FROM user_activity_log
            WHERE user_id = %s AND event_type = 'LOGOUT'
            ORDER BY event_time DESC
            LIMIT 1 ALLOW FILTERING;
        """
        result = session.execute(query, (str(user_id),))
        row = result.one()
        return row[0] if row else None
    except Exception as e:
        print(f"Error al obtener carrito: {e}")
        return None

def obtener_historial_carrito(user_id: str, limit: int = 20):
    try:
        query = """
            SELECT event_time, event_type, carrito FROM user_activity_log
            WHERE user_id = %s
            ORDER BY event_time DESC
            LIMIT %s ALLOW FILTERING;
        """
        rows = session.execute(query, (str(user_id), limit))
        return [
            {
                "event_time": row.event_time.isoformat(),
                "event_type": row.event_type,
                "carrito": row.carrito,
            }
            for row in rows
        ]
    except Exception as e:
        print(f"Error al obtener historial: {e}")
        return []

def obtener_estado_carrito(user_id: str, event_time: str):
    try:
        dt = datetime.fromisoformat(event_time)
        query = """
            SELECT carrito FROM user_activity_log
            WHERE user_id = %s AND event_time = %s LIMIT 1;
        """
        row = session.execute(query, (str(user_id), dt)).one()
        return row.carrito if row else None
    except Exception as e:
        print(f"Error al obtener estado carrito: {e}")
        return None

IVA_MAPPING = {
    "responsable inscripto": 0.21,
    "consumidor final": 0.21,
    "monotributista": 0.05,
    "exento": 0.0,
}

def obtener_porcentaje_iva(condicion: str) -> float:
    if not condicion:
        return 0.21

    clave = condicion.strip().lower()
    if clave in IVA_MAPPING:
        return IVA_MAPPING[clave]

    match = re.search(r"(\d+[\.,]?\d*)", clave)
    if match:
        try:
            return float(match.group(1).replace(",", ".")) / 100
        except ValueError:
            pass

    return 0.21
