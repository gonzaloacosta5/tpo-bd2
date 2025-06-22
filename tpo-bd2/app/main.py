from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from bson import ObjectId
from typing import Annotated
import bcrypt
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta, timezone
from os import environ
from neo4j import GraphDatabase
import redis
import json
import jwt
from cassandra.cluster import Cluster
import uuid
from jwt.exceptions import InvalidTokenError
from .utilities import mongo, redis_client, cassandra, mongo_client
from .usuarios import usuario
from .productos import productos
from .carrito import carrito
from .ventas import ventas
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONT_DIR = BASE_DIR / "frontend"

@app.get("/")
def read_index():
    return FileResponse(FRONT_DIR / "index.html")

app.include_router(router=usuario)
app.include_router(router=productos)
app.include_router(router=carrito)
app.include_router(router=ventas)

@app.get("/health")
def health_check():
    status = {}

    try:
        mongo_client.admin.command("ping")
        status["MongoDB"] = "alive"
    except ConnectionFailure:
        status["MongoDB"] = "unreachable"

    try:
        redis_client.ping()
        status["Redis"] = "alive"
    except redis.ConnectionError:
        status["Redis"] = "unreachable"

    try:
        session = cassandra.connect()
        session.execute("SELECT now() FROM system.local")
        status["Cassandra"] = "alive"
        session.shutdown()
    except Exception as e:
        status["Cassandra"] = f"unreachable: {str(e)}"

    return status
