import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from .utilities import mongo, chek_user_id, user_activity_log
from .utilities import redis_client

ventas = APIRouter(tags=["ventas"], prefix="/ventas")
logger = logging.getLogger("uvicorn.error")

class MetodoPago(BaseModel):
    metodo: str
    numero_tarjeta: Optional[str] = None
    nombre_tarjeta: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    ccv: Optional[str] = None
    guardar_tarjeta: Optional[bool] = False

class PagoMultiple(BaseModel):
    venta_ids: List[int]
    metodo: str
    operador: Optional[str] = None
    numero_tarjeta: Optional[str] = None
    nombre_tarjeta: Optional[str] = None
    fecha_vencimiento: Optional[str] = None
    ccv: Optional[str] = None
    guardar_tarjeta: Optional[bool] = False

METODOS_VALIDOS = {"Efectivo", "MP", "Tarjeta"}

def get_card_operator(number: Optional[str]) -> Optional[str]:
    if not number:
        return None
    n = number.replace(" ", "").replace("-", "")
    if n.startswith("4"):
        return "Visa"
    if n[:2] in ("51", "52", "53", "54", "55"):
        return "Mastercard"
    if n.startswith(("34", "37")):
        return "American Express"
    if n.startswith(("60", "62", "65")):
        return "Discover"
    if n.startswith(("36", "38", "30")):
        return "Diners Club"
    if n.startswith(("50", "56", "57", "58", "59", "6042")):
        return "Cabal"
    return None

@ventas.post("/pagar_varias")
async def pagar_varias(user_id: str, pago: PagoMultiple):
    user = chek_user_id(user_id)
    metodo = pago.metodo
    operador = pago.operador or user["user_name"]

    if metodo not in METODOS_VALIDOS:
        raise HTTPException(400, "Método de pago inválido")

    if metodo == "Tarjeta":
        op = get_card_operator(pago.numero_tarjeta)
        if not op:
            raise HTTPException(400, "Tarjeta no válida (Visa, Mastercard, AmEx, Cabal)")
        operador = op

    pendientes = list(mongo.ventas.find({
        "_id": {"$in": pago.venta_ids},
        "PagoCompleto": False
    }))
    if not pendientes:
        raise HTTPException(404, "No hay ventas pendientes para pagar")

    monto_total = sum(v.get("TotalDeVenta", 0) for v in pendientes)
    if monto_total == 0:
        for v in pendientes:
            iva_rate = (v.get("IVA", 0) or 21) / 100
            subtotal = sum(item.get("subtotal", 0) for item in v.get("Carrito", []))
            monto_total += round(subtotal * (1 + iva_rate), 2)

    pago_dict = {
        "user_id": int(user_id),
        "venta_ids": pago.venta_ids,
        "metodo": metodo,
        "operador": operador,
        "monto": monto_total,
        "fecha": datetime.now().isoformat(),
    }
    result = mongo.pagos.insert_one(pago_dict)

    if metodo == "Tarjeta" and pago.guardar_tarjeta:
        num = (pago.numero_tarjeta or "").replace(" ", "").replace("-", "")
        ultimos4 = num[-4:] if len(num) >= 4 else num
        tarjeta_doc = {
            "ultimos4": ultimos4,
            "operador": operador,
            "nombre": pago.nombre_tarjeta,
            "fecha_vencimiento": pago.fecha_vencimiento
        }
        mongo.users.update_one(
            {"_id": int(user_id)},
            {"$push": {"TarjetasGuardadas": tarjeta_doc}}
        )

    pago_id = result.inserted_id

    for venta in pendientes:
        new_cart = []
        for item in venta.get("Carrito", []):
            prod = mongo.products.find_one({"_id": int(item["product_id"])})
            precio = prod.get("price", 0)
            desc   = prod.get("descuento", 0)
            pu     = round(precio * (1 - desc/100), 2)

            new_cart.append({
                "product_id":      item["product_id"],
                "cantidad":        item["amount"],
                "nombre":          prod.get("name"),
                "description":     prod.get("description"),
                "image":           prod.get("image"),
                "precio_original": precio,
                "descuento":       desc,
                "precio_unitario": pu,
                "subtotal":        round(pu * item["amount"], 2)
            })

        mongo.ventas.update_one(
            {"_id": venta["_id"]},
            {"$set": {
                "Carrito":     new_cart,
                "PagoCompleto": True,
                "MetodoPago":   metodo,
                "operador":     operador,
                "FechaPago":    pago_dict["fecha"],
                "pago_id":      pago_id
            }}
        )

        for it in new_cart:
            mongo.products.update_one(
                {"_id": int(it["product_id"])},
                {"$inc": {"stock": -it["cantidad"]}}
            )

    user_activity_log(user_id, "PURCHASE_MULTIPLE", pago.venta_ids)
    redis_client.hdel(f"user:{user_id}", "carrito")
    return {"message": "Pago registrado", "pago_id": str(pago_id)}

@ventas.get("/historial/{user_id}")
async def traer_historial_compras(user_id: str):
    chek_user_id(user_id)
    compras = list(mongo.ventas.find({"idUser": user_id, "PagoCompleto": True}))
    if not compras:
        raise HTTPException(404, "No se encontraron compras")

    usuario = mongo.users.find_one({"_id": int(user_id)})
    user_name = usuario.get("user_name", "")
    nombre = usuario.get("name", "")

    historial = []
    for c in compras:
        vid = str(c.get("_id"))
        productos = c.get("Carrito", [])
        total = round(c.get("TotalDeVenta", 0), 2)
        if total == 0:
            iva_rate = (c.get("IVA", 0) or 21) / 100
            subtotal = sum(item.get("subtotal", 0) for item in productos)
            total = round(subtotal * (1 + iva_rate), 2)
        entry = {
            "idVenta": vid,
            "user_name": user_name,
            "nombre": nombre,
            "productos": productos,
            "total": total,
            "IVA": c.get("IVA", 21),
            "fecha": c.get("Fecha"),
            "metodo_pago": c.get("MetodoPago"),
            "operador": c.get("operador"),
            "fecha_pago": c.get("FechaPago"),
        }
        historial.append(entry)

    return historial

@ventas.get("/historial_pagos/{user_id}")
async def traer_historial_pagos(user_id: str):
    chek_user_id(user_id)
    pagos = list(mongo.pagos.find({"user_id": int(user_id)}).sort("fecha", -1))

    historial = []
    for p in pagos:
        monto = p.get("monto", 0)
        if monto == 0:
            for vid in p.get("venta_ids", []):
                v = mongo.ventas.find_one({"_id": vid})
                iva_rate = (v.get("IVA", 0) or 21) / 100
                subtotal = sum(item.get("subtotal", 0) for item in v.get("Carrito", []))
                monto += round(subtotal * (1 + iva_rate), 2)
        entry = {
            "pago_id": str(p.get("_id")),
            "fecha": p.get("fecha"),
            "metodo": p.get("metodo"),
            "operador": p.get("operador"),
            "monto": monto,
            "ventas_cubiertas": p.get("venta_ids", []),
        }
        historial.append(entry)

    return historial

@ventas.post("/comprar/{user_id}/{id_venta}")
async def comprar_venta(user_id: str, id_venta: int, metodo_pago: MetodoPago):
    return await pagar_varias(user_id, PagoMultiple(
        venta_ids=[id_venta],
        metodo=metodo_pago.metodo,
        operador=None,
        numero_tarjeta=metodo_pago.numero_tarjeta,
        nombre_tarjeta=metodo_pago.nombre_tarjeta,
        fecha_vencimiento=metodo_pago.fecha_vencimiento,
        ccv=metodo_pago.ccv,
        guardar_tarjeta=metodo_pago.guardar_tarjeta
    ))
