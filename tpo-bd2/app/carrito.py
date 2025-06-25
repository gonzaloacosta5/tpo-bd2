from fastapi import APIRouter, HTTPException
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import copy
import json
import logging
from .productos import obtener_precio_producto
from .utilities import (
    mongo,
    redis_client,
    obtener_stock_producto,
    chek_user_id,
    user_activity_log,
    obtener_historial_carrito,
    obtener_estado_carrito,
    obtener_porcentaje_iva,
)

logger = logging.getLogger("uvicorn.error")

carrito = APIRouter(tags=["carrito"], prefix="/carrito")

class Carrito(BaseModel):
    product_id: str
    amount: int

class CaritoDef(Carrito):
    discount: int

class Pedido(BaseModel):
    idUser: str
    Fecha: Optional[datetime] = Field(default_factory=datetime.today)
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
    carrito_raw = redis_client.hget(f"user:{user_id}", "carrito")
    if not carrito_raw:
        return []
    try:
        carrito = eval(carrito_raw)
        if all(isinstance(x, str) for x in carrito):
            carrito = [json.loads(x) for x in carrito]
    except Exception:
        raise HTTPException(status_code=500, detail="Carrito corrupto")
    resultado = []
    for item in carrito:
        if not isinstance(item, dict):
            continue
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
    try:
        carrito_viejo = [] if carrito_viejo is None else eval(carrito_viejo)
        if all(isinstance(x, str) for x in carrito_viejo):
            carrito_viejo = [json.loads(x) for x in carrito_viejo]
    except:
        carrito_viejo = []
    carrito_nuevo = copy.deepcopy(carrito_viejo)
    stock = await obtener_stock_producto(carrito.product_id)
    if stock < carrito.amount:
        raise HTTPException(status_code=400, detail="No hay mas productos en el stock")
    for producto in carrito_nuevo:
        if carrito.product_id == producto.get("product_id"):
            cantidad = producto.get("amount") + carrito.amount
            if stock < cantidad:
                raise HTTPException(status_code=400, detail="No hay mas productos en el stock")
            producto["amount"] = cantidad
            break
    else:
        carrito_nuevo.append(carrito.dict())
    redis_client.hset(f"user:{user_id}", "carrito", str(carrito_nuevo))
    user_activity_log(user_id, "ADD_CART", json.dumps(carrito_nuevo))
    return carrito_nuevo

@carrito.delete("/borrar/user_id/{user_id}")
async def borar_carrito(user_id, carrito: Carrito):
    user = chek_user_id(user_id)
    viejo = redis_client.hget(f"user:{user_id}", "carrito")
    try:
        lista = [] if viejo is None else eval(viejo)
        if all(isinstance(x, str) for x in lista):
            lista = [json.loads(x) for x in lista]
    except:
        lista = []
    nuevo = copy.deepcopy(lista)
    if not nuevo:
        raise HTTPException(status_code=404, detail="No hay datos en el carrito")
    for producto in nuevo[:]:
        if producto.get("product_id") == carrito.product_id:
            if carrito.amount == 0:
                nuevo.remove(producto)
            else:
                rem = producto.get("amount") - carrito.amount
                if rem < 0:
                    raise HTTPException(status_code=400, detail="No hay suficientes productos en el carrito")
                if rem == 0:
                    nuevo.remove(producto)
                else:
                    producto["amount"] = rem
            break
    redis_client.hset(f"user:{user_id}", "carrito", str(nuevo))
    user_activity_log(user_id, "REDUCE_CART", json.dumps(nuevo))
    return nuevo

@carrito.post("/confirmar/user_id/{user_id}")
async def confirmar_carrito(user_id):
    user = chek_user_id(user_id)
    raw = redis_client.hget(f"user:{user_id}", "carrito")
    if not raw:
        raise HTTPException(status_code=400, detail="No hay carrito cargado")
    try:
        carrito = eval(raw)
        if all(isinstance(x, str) for x in carrito):
            carrito = [json.loads(x) for x in carrito]
    except:
        raise HTTPException(status_code=400, detail="Error al interpretar el carrito")
    if not carrito:
        raise HTTPException(status_code=400, detail="No hay carrito cargado")
    sub_total = 0
    for producto in carrito:
        pid = int(producto.get("product_id"))
        stock = await obtener_stock_producto(str(pid))
        if stock < producto.get("amount"):
            raise HTTPException(status_code=400, detail=f"No hay stock suficiente para el producto {pid}")
        price, desc = obtener_precio_producto(pid)
        subtotal = price * producto.get("amount")
        sub_total += subtotal * (1 - desc/100)
        producto["discount"] = desc
    user_data = mongo.users.find_one({"_id": int(user_id)})
    iva_rate = obtener_porcentaje_iva(user_data.get("iva_condition"))
    total = round(sub_total * (1 + iva_rate), 2)
    pedido = Pedido(
        idUser=user_id,
        Carrito=carrito,
        TotalDeVenta=total,
        IVA=round(iva_rate*100,2),
        nombre=user_data.get("name"),
        apellido=user_data.get("last_name"),
        direccion=user_data.get("address"),
        condicion_iva=user_data.get("iva_condition"),
    )
    idv = crear_venta(pedido.dict())
    user_activity_log(user_id, "ORDER_CREATED", json.dumps(carrito))
    return {"idVenta": idv, "Fecha": pedido.Fecha, "TotalDeVenta": total, "IVA": round(iva_rate*100,2)}

@carrito.get("/pedido/user_id/{user_id}")
async def get_pedido(user_id):
    user = chek_user_id(user_id)
    if not verificar_otro_pedido(user_id):
        raise HTTPException(status_code=404, detail="No existe pedido pendiente")
    data = mongo.ventas.find_one({"idUser": user_id, "PagoCompleto": False})
    data["idVenta"] = str(data.get("_id"))
    data.pop("_id")
    data["IVA"] = data.get("IVA",21)
    return data

@carrito.delete("/pedido/user_id/{user_id}")
async def delete_pedido(user_id):
    user = chek_user_id(user_id)
    return eliminar_pedido(user_id)

def crear_venta(pedido):
    col = mongo.ventas
    last = col.find_one({"_id":{"$type":"int"}}, sort=[("_id",-1)])
    nid = last["_id"]+1 if last else 1
    pedido["_id"] = nid
    col.insert_one(pedido)
    return nid

def verificar_otro_pedido(user_id):
    return bool(mongo.ventas.find_one({"idUser":user_id,"PagoCompleto":False}))

def eliminar_pedido(user_id):
    if not verificar_otro_pedido(user_id):
        raise HTTPException(status_code=400, detail="No hay ningun pedido pendiente")
    venta = mongo.ventas.find_one({"idUser":user_id,"PagoCompleto":False})
    venta["idVenta"] = str(venta.get("_id"))
    venta.pop("_id")
    mongo.ventas.delete_one({"idUser":user_id,"PagoCompleto":False})
    user_activity_log(user_id, "ORDER_DELETED", json.dumps(venta.get("Carrito")))
    return {"message":"Pedido eliminado con éxito","venta":venta}

@carrito.get("/historial/user_id/{user_id}")
async def historial_carrito(user_id, limit: int=20):
    chek_user_id(user_id)
    logs = obtener_historial_carrito(user_id, limit)
    out = []
    for log in logs:
        t = log["event_type"]
        if t in EVENTO_CARRITO_DESCRIPCION:
            desc = ""
            if t in ("ADD_CART","REDUCE_CART"):
                info = log.get("carrito")
                try:
                    info = json.loads(info)
                except:
                    info = {}
                n = info.get("name","")
                c = info.get("amount","")
                desc = f"{n} (x{c})" if n and c else ""
            out.append({"fecha":log["event_time"],"tipo":t,"descripcion":EVENTO_CARRITO_DESCRIPCION[t],"producto":desc})
    return out

@carrito.post("/restaurar/user_id/{user_id}")
async def restaurar_carrito(user_id, event_time: str):
    user = chek_user_id(user_id)
    estado = obtener_estado_carrito(user_id, event_time)
    if not estado:
        raise HTTPException(status_code=404, detail="Estado no encontrado")
    try:
        lista = eval(estado)
        if all(isinstance(x, str) for x in lista):
            lista = [json.loads(x) for x in lista]
        redis_client.hset(f"user:{user_id}", "carrito", str(lista))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error restaurando carrito: {e}")
    return {"carrito": lista}

EVENTO_CARRITO_DESCRIPCION = {
    "ADD_CART": "Agregó un producto al carrito",
    "REDUCE_CART": "Quitó producto(s) del carrito",
    "ORDER_CREATED": "Confirmó el pedido",
    "ORDER_DELETED": "Canceló el pedido",
}
