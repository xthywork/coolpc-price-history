"""Query-parameter types that treat an empty-string value the same as omitted.

Browsers submit GET forms with every field present, including unfilled
number/select inputs sent as `field=`. FastAPI/Pydantic normally rejects an
empty string for an `int | None` / `float | None` / `bool | None` query
parameter with a 422, even though the user's intent ("no filter") is
unambiguous. These annotated types coerce `""` to `None` before validation
so optional filters behave the same whether the field was omitted or left
blank.
"""
from __future__ import annotations
import datetime as dt
from typing import Annotated
from pydantic import BeforeValidator


def _empty_str_to_none(value):
    if value == "":
        return None
    return value


OptionalInt = Annotated[int | None, BeforeValidator(_empty_str_to_none)]
OptionalFloat = Annotated[float | None, BeforeValidator(_empty_str_to_none)]
OptionalBool = Annotated[bool | None, BeforeValidator(_empty_str_to_none)]
OptionalDatetime = Annotated[dt.datetime | None, BeforeValidator(_empty_str_to_none)]
