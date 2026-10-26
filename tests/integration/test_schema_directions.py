"""Every API schema says which way it flows (src/api/schemas/base.py).

A request field with a default is optional for the client; a response field
is always sent. The spec - and the frontend types generated from it - can
only say so when each schema inherits RequestModel or ResponseModel.
"""

import importlib
import inspect
import pkgutil
import typing
from collections.abc import Iterator
from typing import Any

from flask import Flask
from pydantic import BaseModel

import src.api.schemas as schemas_package
from src.api.schemas.base import RequestModel, ResponseModel


def _schema_classes() -> list[type[BaseModel]]:
    modules = [
        importlib.import_module(f"{schemas_package.__name__}.{info.name}")
        for info in pkgutil.iter_modules(schemas_package.__path__)
    ]
    modules.append(importlib.import_module("src.api.errors"))
    return [
        obj
        for module in modules
        for obj in vars(module).values()
        if inspect.isclass(obj)
        and issubclass(obj, BaseModel)
        and obj.__module__ == module.__name__
        and obj not in (RequestModel, ResponseModel)
    ]


def _model(schema: Any) -> type[BaseModel] | None:
    for candidate in (getattr(schema, "model_class", None), schema):
        if inspect.isclass(candidate) and issubclass(candidate, BaseModel):
            return candidate
    return None


def test_every_schema_picks_a_direction() -> None:
    undirected = [
        cls.__name__
        for cls in _schema_classes()
        if not issubclass(cls, (RequestModel, ResponseModel))
    ]
    assert not undirected, undirected


def _nested_models(annotation: Any) -> Iterator[type[BaseModel]]:
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in typing.get_args(annotation):
        yield from _nested_models(arg)


def test_responses_nest_no_request_models() -> None:
    # A request model inside a response makes its defaulted fields optional in
    # the spec, though the server sends them (the client then hand-writes the
    # real shape). Give the response its own ResponseModel.
    nested = [
        f"{cls.__name__}.{name}: {sub.__name__}"
        for cls in _schema_classes()
        if issubclass(cls, ResponseModel)
        for name, field in cls.model_fields.items()
        for sub in _nested_models(field.annotation)
        if not issubclass(sub, ResponseModel)
    ]
    assert not nested, nested


def test_routes_use_the_right_direction(app: Flask) -> None:
    wrong = []
    for endpoint, view in app.view_functions.items():
        spec = getattr(view, "_spec", None) or {}
        response = spec.get("response")
        output = _model(response.get("schema")) if isinstance(response, dict) else None
        if output and not issubclass(output, ResponseModel):
            wrong.append(f"{endpoint} returns {output.__name__}")
        body = getattr(view, "_validated_body", None) or _model(spec.get("body"))
        if body and not issubclass(body, RequestModel):
            wrong.append(f"{endpoint} takes {body.__name__}")
    assert not wrong, wrong


def test_the_spec_requires_response_defaults_and_not_request_ones(app: Flask) -> None:
    components = app.spec["components"]["schemas"]  # type: ignore[attr-defined]
    # BrowserError.stack defaults to None but is always sent
    browser_error = components["AdminOverviewResponse.BrowserError"]
    assert "stack" in browser_error["required"]
    # ClientErrorReport.stack defaults to None and may be left out
    assert "stack" not in components["ClientErrorReport"].get("required", [])
