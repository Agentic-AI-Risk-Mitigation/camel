# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Standard library implementation.

From https://github.com/google/starlark-go/blob/master/starlark/library.go#L157
"""

import collections.abc
import datetime
import enum
import typing
from typing import Any

import pydantic
import pydantic.fields as pydantic_fields

from ..capabilities import capabilities
from . import camel_value


# This can't be typed in a more narrow way bc of limitations of the Python type
# system.
def camel_zip(
    *x: collections.abc.Iterable[typing.Any],
) -> list[tuple[typing.Any, ...]]:
    return list(zip(*x))


_T = typing.TypeVar("_T")


def camel_enumerate(
    x: collections.abc.Iterable[_T], start: int = 0
) -> list[tuple[int, _T]]:
    return list(enumerate(x, start))


def camel_reversed(x: collections.abc.Reversible[_T]) -> list[_T]:
    return list(reversed(x))


def camel_bool(x: object) -> bool:
    return bool(x)


def camel_dir(x: object) -> list[str]:
    return dir(x)


def camel_range(
    start: int,
    stop: int | None = None,
    step: int | None = None,
    /,
) -> list[int]:
    match (stop, step):
        case None, None:
            return list(range(start))
        case (_, None):
            return list(range(start, stop))
        case (None, _):
            raise TypeError("'NoneType' object cannot be interpreted as an integer")
        case (_, _):
            return list(range(start, stop, step))


# pylint: disable=unused-argument
# we need these arguments to match Python's print function signature in case
# it gets called with these arguments
def camel_print(
    *values: object,
    sep: str | None = " ",
    end: str | None = "\n",
    file: typing.Any | None = None,
    flush: bool = False,
) -> None:
    return None


# pylint: enable=unused-argument


BUILT_IN_FUNCTIONS: dict[str, camel_value.CaMeLBuiltin] = {
    "abs": camel_value.make_builtin("abs", abs),
    "any": camel_value.make_builtin("any", any),
    "all": camel_value.make_builtin("all", all),
    "bool": camel_value.make_builtin("bool", camel_bool),
    "dir": camel_value.make_builtin("dir", camel_dir),
    "divmod": camel_value.make_builtin("divmod", divmod),
    # We don't want lazy objects, so `enumerate` must return a list
    "enumerate": camel_value.make_builtin("enumerate", camel_enumerate),
    "float": camel_value.make_builtin("float", float),
    "hash": camel_value.make_builtin("hash", hash),
    "int": camel_value.make_builtin("int", int),
    "len": camel_value.make_builtin("len", len),
    "list": camel_value.make_builtin("list", list),
    "max": camel_value.make_builtin("max", max),  # type: ignore  # unclear what's wrong here
    "min": camel_value.make_builtin("min", min),  # type: ignore  # unclear what's wrong here
    "print": camel_value.make_builtin("print", camel_print),
    "range": camel_value.make_builtin("range", camel_range),
    "repr": camel_value.make_builtin("repr", repr),
    # We don't want lazy objects, so `reversed` must return a list of tuples
    "reversed": camel_value.make_builtin("reversed", camel_reversed),
    "set": camel_value.make_builtin("set", set),
    "sorted": camel_value.make_builtin("sorted", sorted),
    "str": camel_value.make_builtin("str", str),
    "tuple": camel_value.make_builtin("tuple", tuple),
    "type": camel_value.make_builtin("type", lambda x: type(x).__name__),
    # We don't want lazy objects, so `zip` must return a list of tuples
    "zip": camel_value.make_builtin("zip", camel_zip),
    "sum": camel_value.make_builtin("sum", sum),
}
"""Built-in functions supported in Starlark (plus or minus some extra).

See https://github.com/bazelbuild/starlark/blob/master/spec.md#built-in-constants-and-functions"""


class NotEnoughInformationError(Exception):
    """Raised when the PrivilegedLLM has not provided enough information to the QuarantinedLLM."""

    ...


BUILT_IN_CLASSES: dict[str, camel_value.CaMeLClass] = {
    "ValueError": camel_value.CaMeLClass(
        "ValueError",
        ValueError,
        capabilities.Capabilities.camel(),
        (),
        {},
        is_builtin=True,
    ),
    "NotEnoughInformationError": camel_value.CaMeLClass(
        "NotEnoughInformationError",
        NotEnoughInformationError,
        capabilities.Capabilities.camel(),
        (),
        {},
        is_builtin=True,
    ),
    "Enum": camel_value.CaMeLClass(
        "Enum",
        enum.Enum,
        capabilities.Capabilities.camel(),
        (),
        {},
        is_builtin=True,
    ),
    "datetime": camel_value.CaMeLClass(
        "datetime",
        datetime.datetime,
        capabilities.Capabilities.camel(),
        (),
        {
            "strftime": camel_value.make_builtin(
                "strftime", datetime.datetime.strftime
            ),
            "replace": camel_value.make_builtin("replace", datetime.datetime.replace),
            "isoformat": camel_value.make_builtin(
                "isoformat", datetime.datetime.isoformat
            ),
            "utcoffset": camel_value.make_builtin(
                "utcoffset", datetime.datetime.utcoffset
            ),
            "strptime": camel_value.make_builtin(
                "strptime", datetime.datetime.strptime, is_class_method=True
            ),
            "fromisoformat": camel_value.make_builtin(
                "fromisoformat",
                datetime.datetime.fromisoformat,
                is_class_method=True,
            ),
            "date": camel_value.make_builtin(
                "date", datetime.datetime.date, is_class_method=False
            ),
            "time": camel_value.make_builtin(
                "time", datetime.datetime.time, is_class_method=False
            ),
            "weekday": camel_value.make_builtin(
                "weekday", datetime.datetime.weekday, is_class_method=False
            ),
            "combine": camel_value.make_builtin(
                "combine", datetime.datetime.combine, is_class_method=True
            ),
            "__add__": camel_value.make_builtin(
                "__add__", datetime.datetime.__add__
            ),  # Operator method in methods
            "__sub__": camel_value.make_builtin(
                "__sub__", datetime.datetime.__sub__
            ),  # Operator method in methods
        },
        is_totally_ordered=True,
        is_builtin=True,
    ),
    "timedelta": camel_value.CaMeLClass(
        "timedelta",
        datetime.timedelta,
        capabilities.Capabilities.camel(),
        (),
        {
            "total_seconds": camel_value.make_builtin(
                "total_seconds", datetime.timedelta.total_seconds
            ),
            "__add__": camel_value.make_builtin(
                "__add__", datetime.timedelta.__add__
            ),  # Operator method in methods
            "__sub__": camel_value.make_builtin(
                "__sub__", datetime.timedelta.__sub__
            ),  # Operator method in methods
            "__mul__": camel_value.make_builtin("__mul__", datetime.timedelta.__mul__),
            "__truediv__": camel_value.make_builtin(
                "__truediv__", datetime.timedelta.__truediv__
            ),
            "__radd__": camel_value.make_builtin(
                "__radd__", datetime.timedelta.__radd__
            ),
            "__rsub__": camel_value.make_builtin(
                "__rsub__", datetime.timedelta.__rsub__
            ),
            "__rmul__": camel_value.make_builtin(
                "__rmul__", datetime.timedelta.__rmul__
            ),
        },
        is_totally_ordered=True,
        is_builtin=True,
    ),
    "date": camel_value.CaMeLClass(
        "date",
        datetime.date,
        capabilities.Capabilities.camel(),
        (),
        {
            "replace": camel_value.make_builtin("replace", datetime.date.replace),
            "isoformat": camel_value.make_builtin("isoformat", datetime.date.isoformat),
            "strftime": camel_value.make_builtin("strftime", datetime.date.strftime),
            "fromisoformat": camel_value.make_builtin(
                "fromisoformat",
                datetime.date.fromisoformat,
                is_class_method=True,
            ),
            "__add__": camel_value.make_builtin("__add__", datetime.date.__add__),
            "__radd__": camel_value.make_builtin("__radd__", datetime.date.__radd__),
            "__sub__": camel_value.make_builtin("__sub__", datetime.date.__sub__),
        },
        is_totally_ordered=True,
        is_builtin=True,
    ),
    "time": camel_value.CaMeLClass(
        "time",
        datetime.time,
        capabilities.Capabilities.camel(),
        (),
        {
            "replace": camel_value.make_builtin("replace", datetime.time.replace),
            "isoformat": camel_value.make_builtin("isoformat", datetime.time.isoformat),
            "strftime": camel_value.make_builtin("strftime", datetime.time.strftime),
            "fromisoformat": camel_value.make_builtin(
                "fromisoformat",
                datetime.date.fromisoformat,
                is_class_method=True,
            ),
        },
        is_totally_ordered=True,
        is_builtin=True,
    ),
    "timezone": camel_value.CaMeLClass(
        "timezone",
        datetime.timezone,
        capabilities.Capabilities.camel(),
        (),
        {
            "utcoffset": camel_value.make_builtin(
                "utcoffset", datetime.timezone.utcoffset
            ),
            "tzname": camel_value.make_builtin("tzname", datetime.timezone.tzname),
            "dst": camel_value.make_builtin("dst", datetime.timezone.dst),
        },
        is_totally_ordered=False,
        is_builtin=True,
    ),
    "BaseModel": camel_value.CaMeLClass(
        "BaseModel",
        pydantic.BaseModel,
        capabilities.Capabilities.camel(),
        (),
        {
            "model_construct": camel_value.make_builtin(
                "model_construct", pydantic.BaseModel.model_construct
            ),
            "model_copy": camel_value.make_builtin(
                "model_copy", pydantic.BaseModel.model_copy
            ),
            "model_dump": camel_value.make_builtin(
                "model_dump", pydantic.BaseModel.model_dump
            ),
            "model_dump_json": camel_value.make_builtin(
                "model_dump_json", pydantic.BaseModel.model_dump_json
            ),
            "model_json_schema": camel_value.make_builtin(
                "model_json_schema", pydantic.BaseModel.model_json_schema
            ),
            "model_parametrized_name": camel_value.make_builtin(
                "model_parametrized_name",
                pydantic.BaseModel.model_parametrized_name,
            ),
            "model_validate": camel_value.make_builtin(
                "model_validate", pydantic.BaseModel.model_validate
            ),
            "model_validate_json": camel_value.make_builtin(
                "model_validate_json", pydantic.BaseModel.model_validate_json
            ),
            "model_validate_strings": camel_value.make_builtin(
                "model_validate_strings",
                pydantic.BaseModel.model_validate_strings,
            ),
        },
        is_builtin=True,
    ),
    "FieldInfo": camel_value.CaMeLClass(
        "FieldInfo",
        pydantic_fields.FieldInfo,  # type: ignore  # unclear what's wrong here
        capabilities.Capabilities.camel(),
        (),
        {},
        is_builtin=True,
    ),
    "EmailStr": camel_value.CaMeLClass(
        "EmailStr",
        pydantic.EmailStr,  # type: ignore
        capabilities.Capabilities.camel(),
        (),
        {},
        is_builtin=True,
    ),
    "NaiveDatetime": camel_value.CaMeLClass(
        "NaiveDatetime",
        pydantic.NaiveDatetime,  # type: ignore
        capabilities.Capabilities.camel(),
        (),
        {},
        is_builtin=True,
    ),
}


def make_builtins_namespace(
    variables: dict[str, camel_value.Value[Any]] | None = None,
) -> camel_value.Namespace:
    return camel_value.Namespace(
        variables=(BUILT_IN_FUNCTIONS | BUILT_IN_CLASSES | (variables or {}))
    )
