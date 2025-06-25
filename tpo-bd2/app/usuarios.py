from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo.errors import ConnectionFailure
from typing import Annotated
import bcrypt
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
from os import environ
import redis
import bson
from cassandra.cluster import Cluster
from .utilities import mongo, redis_client, cassandra, mongo_client, user_activity_log, chek_user_id
from dotenv import load_dotenv
from enum import Enum

load_dotenv()

usuario = APIRouter(tags=["usuario"], prefix="/usuario")

class TokenData(BaseModel):
    username: str | None = None


class IVACondition(str, Enum):
    RESPONSABLE_INSCRIPTO = "Responsable Inscripto"
    MONOTRIBUTISTA        = "Monotributista"
    CONSUMIDOR_FINAL      = "Consumidor Final"
    EXENTO                = "Exento"

class User(BaseModel):
    name: str
    last_name: Optional[str] = Field(default=None)
    user_name: str
    email: Optional[str] = Field(default=None)
    dni: Optional[str] = Field(min_length=8, max_length=16, default=None)
    address: Optional[str] = Field(default=None)
    iva_condition: Optional[IVACondition] = Field(default=IVACondition.CONSUMIDOR_FINAL)


class UserInDb(User):
    password: str

def get_next_user_id():
    counters = mongo.counters
    ret = counters.find_one_and_update({"_id": "userId"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return ret["seq"]

def obtener_ultimo_carrito(user_id):
    try:
        query = """
            SELECT carrito FROM usuarios.user_activity_log
            WHERE user_id = %s AND event_type = 'LOGOUT'
            ORDER BY event_time DESC LIMIT 1 ALLOW FILTERING;
        """
        result = cassandra.connect().execute(query, (user_id,))
        row = result.one()
        return row[0] if row else "[]"
    except Exception:
        return "[]"

def authenticate_user(username: str, password: str):
    try:
        data = get_user(username)
        if not data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
        hashed_password = data["password"]
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode("utf-8")
        elif hasattr(hashed_password, 'decode'):
            hashed_password = bytes(hashed_password)
        if not bcrypt.checkpw(password.encode("utf-8"), hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
        return User(**data), str(data.get("_id"))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})

refresh_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido", headers={"WWW-Authenticate": "Bearer"})

def get_user(username):
    collection = mongo.users
    try:
        data = collection.find_one({"user_name": username})
        return data
    except Exception:
        raise credentials_exception

def chek_user_id(user_id):
    user = mongo.users.find_one({"_id": int(user_id)})
    session_redis = redis_client.hget(f"user:{str(user_id)}", "user")
    if not user:
        raise HTTPException(status_code=404, detail="Usuario inexistente")
    if not session_redis:
        raise HTTPException(status_code=404, detail="Usuario no logeado")
    return user

@usuario.post("/register")
async def post_new_user(user: UserInDb):
    collection = mongo.users
    try:
        user.password = bcrypt.hashpw(user.password.encode("utf-8"), bcrypt.gensalt())
        user_dict = user.dict()
        user_dict["date"] = datetime.today()
        user_dict["active"] = True
        user_dict["Categorizacion"] = "LOW"
        user_dict["_id"] = get_next_user_id()
        data = collection.find_one({"user_name": user.user_name})
        if data:
            raise HTTPException(status_code=409, detail="username ya existente")
        post_id = collection.insert_one(user_dict).inserted_id
        user_activity_log(str(post_id), "REGISTER", [])
        carrito = []
        user_activity_log(str(post_id), "LOGIN", carrito)
        redis_client.hset(f"user:{str(post_id)}", mapping={"user": user.user_name, "id_user": str(post_id), "carrito": str(carrito)})
        user_data = collection.find_one({"_id": post_id})
        result = {
            "name": user_data.get("name"),
            "last_name": user_data.get("last_name"),
            "user_name": user_data.get("user_name"),
            "email": user_data.get("email"),
            "dni": user_data.get("dni"),
            "address": user_data.get("address"),
            "iva_condition": user_data.get("iva_condition"),
            "Categorizacion": user_data.get("Categorizacion"),
            "idUser": str(user_data.get("_id")),
        }
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@usuario.post("/login")
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user, id = authenticate_user(form_data.username, form_data.password)
    data = redis_client.hget(f"user:{str(id)}", "user")
    if data:
        raise HTTPException(status_code=400, detail="Usuario ya logeado")
    carrito = eval(obtener_ultimo_carrito(id))
    if not carrito:
        carrito = []
    user_activity_log(id, "LOGIN", carrito)
    redis_client.hset(f"user:{id}", mapping={"user": form_data.username, "id_user": id, "carrito": str(carrito)})
    user_dict = user.dict()
    user_dict["idUser"] = id
    return user_dict

def actualizar_categorizacion_por_tiempo(user_id: str):
    try:
        now = datetime.now()
        inicio_dia = datetime(now.year, now.month, now.day)
        fin_dia = inicio_dia + timedelta(days=1)
        query = """
            SELECT event_type, event_time FROM usuarios.user_activity_log
            WHERE user_id = %s AND event_time >= %s AND event_time < %s
            ORDER BY event_time ASC ALLOW FILTERING;
        """
        rows = cassandra.connect().execute(query, (user_id, inicio_dia, fin_dia))
        eventos = [(row.event_type, row.event_time) for row in rows]
        tiempo_conectado_segundos = 0
        login_time = None
        for evento, tiempo in eventos:
            if evento == "LOGIN":
                login_time = tiempo
            elif evento == "LOGOUT" and login_time:
                delta = (tiempo - login_time).total_seconds()
                if delta > 0:
                    tiempo_conectado_segundos += delta
                login_time = None
        minutos_conectado = tiempo_conectado_segundos / 60
        if minutos_conectado > 240:
            categoria = "TOP"
        elif minutos_conectado >= 120:
            categoria = "MEDIUM"
        else:
            categoria = "LOW"
        mongo.users.update_one({"_id": int(user_id)}, {"$set": {"Categorizacion": categoria}})
        return categoria
    except Exception:
        return None

@usuario.delete("/logout/user_id/{user_id}")
async def logout(user_id):
    user = chek_user_id(user_id)
    carrito = redis_client.hget(f"user:{str(user_id)}", "carrito")
    if not carrito:
        raise HTTPException(status_code=400, detail="usuario no logeado")
    user_activity_log(str(user_id), "LOGOUT", carrito)
    categoria_actualizada = actualizar_categorizacion_por_tiempo(user_id)
    redis_client.delete(f"user:{str(user_id)}")
    return {"logout": True, "categorizacion": categoria_actualizada}

@usuario.get("/tarjetas/user_id/{user_id}")
async def get_tarjetas(user_id=None):
    user = chek_user_id(user_id)
    tarjetas = mongo.users.find_one({"_id": int(user_id)}, {"TarjetasGuardadas": 1, "_id": 0})
    if not tarjetas or not tarjetas.get("TarjetasGuardadas"):
        raise HTTPException(status_code=404, detail="No hay tarjetas guardadas")
    tarjetas_protegidas = [
        {
            "nombre": t.get("nombre"),
            "ultimos4": t.get("ultimos4"),
            "fecha_vencimiento": t.get("fecha_vencimiento"),
            "operador": t.get("operador")
        }
        for t in tarjetas["TarjetasGuardadas"]
    ]
    return {"TarjetasGuardadas": tarjetas_protegidas}