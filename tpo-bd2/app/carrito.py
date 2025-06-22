from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from bson import ObjectId
from typing import Annotated, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from os import environ
import copy
from cassandra.cluster import Cluster
import uuid
from .productos import obtener_precio_producto, obtener_stock_producto
from .utilities import (
    mongo,
    redis_client,
    cassandra,
    mongo_client,
    user_activity_log,
    obtener_stock_producto as get_stock,
    chek_user_id,
    obtener_historial_carrito,
    obtener_estado_carrito,
    obtener_porcentaje_iva,
)
from dotenv import load_dotenv

load_dotenv()

carrito = APIRouter(tags=["carrito"], prefix="/carrito")


class Carrito(BaseModel):
    product_id: str
    amount: int


class CaritoDef(Carrito):
    discount: int


class Pedido(BaseModel):
    idUser: str
    Fecha: Optional[datetime] = Field(default=datetime.today())
    Carrito: List[CaritoDef]
    TotalDeVenta: float
    IVA: float = 21.0
    nombre: Optional[str] = None
    apellido: Optional[str] = None
    direccion: Optional[str] = None
    condicion_iva: Optional[str] = None
    MetodoPago: str = None
    PagoCompleto: bool = False


@carrito.get("/user_id/{user_id}")
async def obtener_carrito(user_id):
    user = chek_user_id(user_id)
    carrito = eval(redis_client.hget(f"user:{user_id}", "carrito"))
    resultado = []
    for item in carrito:
        prod_id = item.get("product_id")
        try:
            prod_id_int = int(prod_id)
        except:
            prod_id_int = prod_id
        prod = mongo.products.find_one({"_id": prod_id_int}) or mongo.products.find_one({"_id": str(prod_id)})
        resultado.append({
            "product_id": prod_id,
            "amount": item.get("amount"),
            "name": prod["name"] if prod else f"Producto {prod_id}",
            "image": prod.get("image", "") if prod else "",
        })
    return resultado


@carrito.post("/agregar/user_id/{user_id}")
async def agregar_carrito(user_id, carrito: Carrito):
    user = chek_user_id(user_id)
    carrito_viejo = redis_client.hget(f"user:{user_id}", "carrito")
    carrito_viejo = [] if carrito_viejo is None else eval(carrito_viejo)
    carrito_nuevo = copy.deepcopy(carrito_viejo)
    stock = await get_stock(carrito.product_id)
    if stock < carrito.amount:
        raise HTTPException(status_code=400, detail="No hay mas productos en el stock")
    amount = None
    for producto in carrito_nuevo:
        if carrito.product_id == producto.get("product_id"):
            amount = producto.get("amount") + carrito.amount
            if stock < amount:
                raise HTTPException(status_code=400, detail="No hay mas productos en el stock")
            producto["amount"] = amount
            break
    if not amount:
        carrito_nuevo.append(carrito.dict())
    redis_client.hset(f"user:{user_id}", "carrito", str(carrito_nuevo))
    prod = mongo.products.find_one({"_id": int(carrito.product_id)})
    user_activity_log(user_id, "ADD_CART", {
        "product_id": carrito.product_id,
        "name": prod["name"] if prod else "",
        "amount": carrito.amount
    })
    return carrito_nuevo


@carrito.delete("/borrar/user_id/{user_id}")
async def borar_carrito(user_id, carrito: Carrito):
    user = chek_user_id(user_id)
    carrito_viejo = eval(redis_client.hget(f"user:{user_id}", "carrito"))
    carrito_nuevo = copy.deepcopy(carrito_viejo)
    if not carrito_nuevo:
        HTTPException(status_code=404, detail="No hay datos en el carrito")
    for producto in carrito_nuevo[:]:
        if producto.get("product_id") == carrito.product_id:
            if carrito.amount == 0:
                carrito_nuevo.remove(producto)
            else:
                nuevo_amount = producto.get("amount") - carrito.amount
                if nuevo_amount < 0:
                    raise HTTPException(status_code=400, detail="No hay suficientes productos en el carrito")
                elif nuevo_amount == 0:
                    carrito_nuevo.remove(producto)
                else:
                    producto["amount"] = nuevo_amount
            break
    redis_client.hset(f"user:{user_id}", "carrito", str(carrito_nuevo))
    prod = mongo.products.find_one({"_id": int(carrito.product_id)})
    user_activity_log(user_id, "REDUCE_CART", {
        "product_id": carrito.product_id,
        "name": prod["name"] if prod else "",
        "amount": carrito.amount
    })
    return carrito_nuevo


@carrito.post("/confirmar/user_id/{user_id}")
async def confirmar_carrito(user_id):
    user = chek_user_id(user_id)
    carrito_raw = redis_client.hget(f"user:{user_id}", "carrito")
    if not carrito_raw:
        raise HTTPException(status_code=400, detail="No hay carrito cargado")
    carrito = eval(carrito_raw)
    if not carrito:
        raise HTTPException(status_code=400, detail="No hay carrito cargado")
    if verificar_otro_pedido(user_id):
        raise HTTPException(status_code=400, detail="Ya existe un pedido pendiente")
    sub_total_venta = 0
    for producto in carrito:
        try:
            pid = int(producto.get("product_id"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"ID de producto inválido: {producto.get('product_id')}")
        stock = await get_stock(pid)
        if stock < producto.get("amount"):
            raise HTTPException(status_code=400, detail=f"No hay stock suficiente para el producto {pid}")
        price, descuento = obtener_precio_producto(pid)
        subtotal = price * producto.get("amount")
        descuento_aplicado = subtotal * (descuento / 100)
        subtotal_con_descuento = subtotal - descuento_aplicado
        sub_total_venta += subtotal_con_descuento
        producto["discount"] = descuento
    user_data = mongo.users.find_one({"_id": int(user_id)})
    iva_rate = obtener_porcentaje_iva(user_data.get("iva_condition"))
    total_venta = round(sub_total_venta * (1 + iva_rate), 2)
    pedido = Pedido(
        idUser=user_id,
        Carrito=carrito,
        TotalDeVenta=total_venta,
        IVA=round(iva_rate * 100, 2),
        nombre=user_data.get("name"),
        apellido=user_data.get("last_name"),
        direccion=user_data.get("address"),
        condicion_iva=user_data.get("iva_condition"),
    )
    id_venta = crear_venta(pedido.dict())
    user_activity_log(user_id, "ORDER_CREATED", carrito)
    return {
        "idVenta": id_venta,
        "Fecha": pedido.Fecha,
        "TotalDeVenta": total_venta,
        "IVA": round(iva_rate * 100, 2),
    }


@carrito.get("/pedido/user_id/{user_id}")
async def get_pedido(user_id):
    user = chek_user_id(user_id)
    if not verificar_otro_pedido(user_id):
        raise HTTPException(status_code=404, detail="No existe pedido pendiente")
    data = mongo.ventas.find_one({"idUser": user_id, "PagoCompleto": False})
    data["idVenta"] = str(data.get("_id"))
    data.pop("_id")
    data["IVA"] = data.get("IVA", 21)
    return data


@carrito.delete("/pedido/user_id/{user_id}")
async def delete_pedido(user_id):
    user = chek_user_id(user_id)
    return eliminar_pedido(user_id)


def crear_venta(pedido):
    collection = mongo.ventas
    try:
        last = collection.find_one({"_id": {"$type": "int"}}, sort=[("_id", -1)])
        next_id = last["_id"] + 1 if last else 1
        pedido["_id"] = next_id
        collection.insert_one(pedido)
        return next_id
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def verificar_otro_pedido(user_id):
    collection = mongo.ventas
    try:
        return bool(collection.find_one({"idUser": user_id, "PagoCompleto": False}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def eliminar_pedido(user_id):
    collection = mongo.ventas
    try:
        if not verificar_otro_pedido(user_id):
            raise HTTPException(status_code=400, detail="No hay ningun pedido pendiente")
        venta = collection.find_one({"idUser": user_id, "PagoCompleto": False})
        venta["idVenta"] = str(venta.get("_id"))
        venta.pop("_id")
        collection.delete_one({"idUser": user_id, "PagoCompleto": False})
        user_activity_log(user_id, "ORDER_DELETED", str(venta.get("Carrito")))
        return {"message": "Pedido eliminado con éxito", "venta": venta}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


EVENTO_CARRITO_DESCRIPCION = {
    "ADD_CART": "Agregó un producto al carrito",
    "REDUCE_CART": "Quitó producto(s) del carrito",
    "ORDER_CREATED": "Confirmó el pedido",
    "ORDER_DELETED": "Canceló el pedido",
}


@carrito.get("/historial/user_id/{user_id}")
async def historial_carrito(user_id, limit: int = 20):
    user = chek_user_id(user_id)
    logs = obtener_historial_carrito(user_id, limit)
    eventos_relevantes = []
    for log in logs:
        tipo = log["event_type"]
        if tipo in EVENTO_CARRITO_DESCRIPCION:
            detalles = ""
            if tipo in ("ADD_CART", "REDUCE_CART"):
                info = log.get("producto")
                try:
                    if isinstance(info, str):
                        import json
                        info = json.loads(info)
                    if not info:
                        info = {}
                except:
                    info = {}
                nombre = info.get("name", "")
                cantidad = info.get("amount", "")
                detalles = f"{nombre} (x{cantidad})" if nombre and cantidad else ""
            eventos_relevantes.append({
                "fecha": log["event_time"],
                "tipo": tipo,
                "descripcion": EVENTO_CARRITO_DESCRIPCION[tipo],
                "producto": detalles
            })
    return eventos_relevantes


@carrito.post("/restaurar/user_id/{user_id}")
async def restaurar_carrito(user_id, event_time: str):
    user = chek_user_id(user_id)
    carrito_estado = obtener_estado_carrito(user_id, event_time)
    if not carrito_estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    redis_client.hset(f"user:{user_id}", "carrito", carrito_estado)
    return {"carrito": eval(carrito_estado)}
