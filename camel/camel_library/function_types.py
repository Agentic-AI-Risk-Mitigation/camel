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

"""Pydantic models used in CaMeL."""

from collections.abc import Callable
from typing import Any, Generic, Mapping, ParamSpec, TypeVar

import pydantic

_T = TypeVar("_T")
_P = ParamSpec("_P")


class Function(pydantic.BaseModel, Generic[_P, _T]):
    name: str
    """The name of the function."""
    call: Callable[_P, _T]
    """The call of the function."""
    full_docstring: str
    """The full docstring of the function."""
    parameters: type[pydantic.BaseModel]
    """The parameters of the function."""
    return_type: Any | None
    """The return type of the function."""


class FunctionCall(pydantic.BaseModel, Generic[_T]):
    """An object containing information about a function call requested by an agent."""

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    function: str
    """The name of the function to call."""
    object_type: str | None
    """The name of the type of the object of the method if the function is a method. Otherwise it is `None`."""
    args: Mapping[str, Any]
    """The arguments to pass to the function."""
    output: _T | Exception
    """The output of the function call."""
    is_builtin: bool
    """Whether it is a builtin function."""
