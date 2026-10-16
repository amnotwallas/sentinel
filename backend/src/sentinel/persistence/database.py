import json
from decimal import Decimal
from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel.regression.policy import canonical_json


def serialize_json(value: object) -> str:
    return canonical_json(value)


def deserialize_json(value: str) -> object:
    return cast(object, json.loads(value, parse_float=Decimal))


def create_database(url: str) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
        json_serializer=serialize_json,
        json_deserializer=deserialize_json,
    )
    return engine, sessionmaker(engine, expire_on_commit=False)
