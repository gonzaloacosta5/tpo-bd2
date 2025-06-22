from fastapi import APIRouter, HTTPException, Body, Query, Path
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime
from .utilities import mongo, cassandra, chek_user_id
from dotenv import load_dotenv

load_dotenv()

cluster = cassandra

_init = cluster.connect()
_init.execute("""
    CREATE KEYSPACE IF NOT EXISTS bd2
    WITH replication = {'class':'SimpleStrategy','replication_factor':'1'};
""")
_init.set_keyspace('bd2')
_init.execute("""
    CREATE TABLE IF NOT EXISTS productos_activity_log (
        user_id    TEXT,
        product_id TEXT,
        event_time TIMESTAMP,
        event_type TEXT,
        producto   TEXT,
        field      TEXT,
        old_value  TEXT,
        new_value  TEXT,
        PRIMARY KEY ((product_id), event_time, event_type, field)
    ) WITH CLUSTERING ORDER BY (event_time DESC);
""")
_init.shutdown()

productos = APIRouter(tags=["productos"], prefix="/productos")

class PutProducto(BaseModel):
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    stock: Optional[int] = Field(default=None)
    price: Optional[float] = Field(default=None)
    descuento: Optional[int] = Field(default=None)
    image: Optional[str] = Field(default=None)

class Producto(BaseModel):
    name: str
    description: Optional[str] = Field(default=None)
    price: float
    stock: Optional[int] = Field(default=0)
    descuento: Optional[int] = Field(default=None)
    image: Optional[str] = Field(default=None)

def product_activity_log(user_id, product_id, event, producto, field=None, old_value=None, new_value=None):
    try:
        session = cluster.connect('bd2')
        insert_cql = """
            INSERT INTO productos_activity_log (
                user_id, product_id, event_time, event_type,
                producto, field, old_value, new_value
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        session.execute(
            insert_cql,
            (
                str(user_id),
                str(product_id),
                datetime.now(),
                event,
                str(producto),
                field,
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
            ),
        )
        session.shutdown()
        return True
    except Exception as e:
        print("Error logging product change:", e)
        return False

@productos.post("/user_id/{userid}")
async def post_producto(userid: str, product: Producto = Body(...)):
    chek_user_id(userid)
    return await agregar_producto(userid, product)

@productos.patch("/name/{product_name}/user_id/{userid}")
async def put_producto_name(product_name: str, userid: str, product: PutProducto = Body(...)):
    chek_user_id(userid)
    return await actualizar_producto_por_nombre(userid, product_name, product)

@productos.delete("/name/{product_name}/user_id/{userid}")
async def delete_producto_name(product_name: str, userid: str):
    chek_user_id(userid)
    return await eliminar_producto_por_nombre(userid, product_name)

@productos.get("/")
async def get_producto(id_product: Optional[str] = Query(None)):
    return await obtener_producto(id_product)

@productos.get("/precios")
async def lista_precios():
    productos_list = await obtener_producto()
    return [
        {
            "idProducto": p["idProducto"],
            "name": p["name"],
            "price": round(p["price"] * (1 - (p.get("descuento", 0) or 0) / 100), 2),
            "descuento": p.get("descuento", 0),
            "precio_original": p["price"]
        }
        for p in productos_list
    ]

async def agregar_producto(userid, producto: Producto):
    collection = mongo.products
    try:
        if not hasattr(producto, '_id') or producto._id is None:
            last_doc = collection.find_one({"_id": {"$type": "int"}}, sort=[("_id", -1)])
            producto._id = last_doc["_id"] + 1 if last_doc else 1
        else:
            producto._id = int(producto._id)

        if collection.find_one({"_id": producto._id, "disable_date": {"$exists": False}}):
            raise HTTPException(409, "El ID de producto ya existe")

        if collection.find_one({"name": producto.name, "disable_date": {"$exists": False}}):
            raise HTTPException(409, "El producto ya existe")

        producto_dict = producto.dict()
        producto_dict.update({"_id": producto._id, "date_added": datetime.utcnow()})
        collection.insert_one(producto_dict)

        product_activity_log(userid, producto._id, "ADD_PRODUCT", producto_dict)
        return {"message": "Producto agregado con éxito", "id": producto._id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

async def actualizar_producto_por_nombre(userid, nombre, producto: PutProducto):
    collection = mongo.products
    try:
        existing = collection.find_one({"name": nombre, "disable_date": {"$exists": False}})
        if not existing:
            raise HTTPException(404, "Producto no encontrado")

        cambios = producto.dict(exclude_unset=True)
        if "name" in cambios and cambios["name"] != nombre:
            if collection.find_one({"name": cambios["name"], "_id": {"$ne": existing["_id"]}, "disable_date": {"$exists": False}}):
                raise HTTPException(409, "Ya existe un producto con ese nombre")

        for campo, nuevo in cambios.items():
            viejo = existing.get(campo)
            if str(viejo) != str(nuevo):
                product_activity_log(userid, existing["_id"], "UPDATE_PRODUCT", None, field=campo, old_value=viejo, new_value=nuevo)

        collection.update_one({"_id": existing["_id"]}, {"$set": cambios})
        return {"message": "Producto actualizado con éxito", "idProducto": str(existing["_id"])}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

async def eliminar_producto_por_nombre(userid, nombre):
    collection = mongo.products
    try:
        existing = collection.find_one({"name": nombre, "disable_date": {"$exists": False}})
        if not existing:
            raise HTTPException(404, "Producto no encontrado o ya eliminado")

        collection.update_one({"_id": existing["_id"]}, {"$set": {"disable_date": datetime.utcnow()}})
        product_activity_log(userid, existing["_id"], "DELETE_PRODUCT", existing)
        return {"message": "Producto eliminado con éxito", "idProducto": str(existing["_id"])}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

async def obtener_producto(idProducto: str = None):
    collection = mongo.products
    try:
        filtro = {"disable_date": {"$exists": False}}
        if idProducto:
            filtro["_id"] = int(idProducto)
        docs = list(collection.find(filtro))
        if not docs:
            raise HTTPException(404, "No existe producto")

        for doc in docs:
            doc["idProducto"] = str(doc.pop("_id"))
            doc["precio_con_descuento"] = round(doc["price"] * (1 - (doc.get("descuento", 0) or 0) / 100), 2)
        return docs

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@productos.get("/activity/{nombre}", summary="Historial de cambios por nombre")
async def get_historial_producto(nombre: str = Path(..., description="Nombre exacto del producto")):
    nombre = nombre.strip()
    prod = mongo.products.find_one({"name": nombre, "disable_date": {"$exists": False}})
    if not prod:
        raise HTTPException(404, f"Producto '{nombre}' no encontrado")

    session = cluster.connect('bd2')
    query = "SELECT * FROM productos_activity_log WHERE product_id = %s ALLOW FILTERING;"
    rows = session.execute(query, (str(prod["_id"]),))
    session.shutdown()

    logs = [{
        "user_id": row.user_id,
        "product_id": row.product_id,
        "event_time": row.event_time.isoformat(),
        "event_type": row.event_type,
        "field": row.field,
        "old_value": row.old_value,
        "new_value": row.new_value,
        "producto": row.producto,
    } for row in rows]

    if not logs:
        raise HTTPException(404, f"No hay historial de cambios para '{nombre}'")
    return {"logs": logs}

def obtener_precio_producto(idProducto: str):
    collection = mongo.products
    try:
        prod = collection.find_one({"_id": int(idProducto), "disable_date": {"$exists": False}}, {"price": 1, "descuento": 1, "_id": 0})
        if not prod:
            raise HTTPException(404, "No se encontro producto")
        return prod.get("price", 0), prod.get("descuento", 0)
    except Exception as e:
        raise HTTPException(500, str(e))

async def obtener_stock_producto(idProducto: str):
    collection = mongo.products
    try:
        prod = collection.find_one({"_id": int(idProducto), "disable_date": {"$exists": False}}, {"stock": 1, "_id": 0})
        if not prod:
            raise HTTPException(404, "No se encontro producto")
        return prod.get("stock", 0)
    except Exception as e:
        raise HTTPException(500, str(e))
