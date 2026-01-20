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

"""CaMeL values."""

import ast
import copy
import dataclasses
import enum
import types
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
)
from typing import Any, Generic, Protocol, Self, TypeVar, runtime_checkable

import pydantic

from ..capabilities import capabilities as camel_capabilities
from ..capabilities import readers, sources


@dataclasses.dataclass(frozen=True)
class Namespace:
    """A namespace for variables in CaMeL."""

    variables: dict[str, "Value"] = dataclasses.field(default_factory=dict)

    def add_variables(self, variables: dict[str, "Value"]) -> Self:
        """Creates a copy of this adding the variables passed as argument."""
        return dataclasses.replace(self, variables=self.variables | variables)

    def set_variable(self, name: str, value: "Value") -> None:
        self.variables[name] = value

    def get(self, name: str) -> "Value | None":
        return self.variables.get(name)


_T = TypeVar("_T", bound=Any)


@runtime_checkable
class Value(Generic[_T], Protocol):
    """A value in CaMeL."""

    python_value: _T
    _capabilities: camel_capabilities.Capabilities
    outer_dependencies: tuple["Value", ...]
    is_builtin: bool = False

    def __repr__(self) -> str:
        return self._repr_helper(indent_level=0)

    def _repr_helper(self, indent_level: int) -> str:
        indent = "  " * indent_level
        next_indent = "  " * (indent_level + 1)

        metadata_str = repr(self._capabilities)

        return f"""{type(self).__name__}(
  {next_indent}value={self.python_value!r},
  {next_indent}capabilities={metadata_str},
  {next_indent}dependencies=...
  {indent})"""

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple["Value", ...], frozenset[int]]:
        return self.outer_dependencies, frozenset({id(self)})

    @property
    def capabilities(self) -> camel_capabilities.Capabilities:
        return self._capabilities

    def __eq__(self, other) -> bool:
        if not is_value(other):
            return False
        return (
            isinstance(other, type(self))
            and self.python_value == other.python_value
            and self._capabilities == other._capabilities
            and self.outer_dependencies == other.outer_dependencies
        )

    def new_with_python_value(self, value: _T) -> Self:
        new_self = copy.copy(self)
        new_self.python_value = value
        return new_self

    def new_with_dependencies(self, dependencies: tuple["Value", ...]) -> Self:
        new_self = copy.copy(self)
        new_self.outer_dependencies = self.outer_dependencies + dependencies
        return new_self

    def new_with_capabilities(
        self, capabilities: camel_capabilities.Capabilities
    ) -> Self:
        new_self = copy.copy(self)
        new_self._capabilities = capabilities
        return new_self

    @property
    def raw(self) -> Any:
        return self.python_value

    @property
    def raw_type(self) -> str:
        return type(self.python_value).__name__

    def is_(self, other: "Value") -> "CaMeLBool":
        camel_metadata = camel_capabilities.Capabilities.camel()
        return (
            CaMeLTrue(camel_metadata, (self, other))
            if self.python_value is other.python_value
            else CaMeLFalse(camel_metadata, (self, other))
        )

    def is_not(self, other: "Value") -> "CaMeLBool":
        camel_metadata = camel_capabilities.Capabilities.camel()
        return (
            CaMeLTrue(camel_metadata, (self, other))
            if self.python_value is not other.python_value
            else CaMeLFalse(camel_metadata, (self, other))
        )

    def truth(self) -> "CaMeLBool":
        if bool(self.python_value):
            return CaMeLTrue(camel_capabilities.Capabilities.camel(), (self,))
        return CaMeLFalse(camel_capabilities.Capabilities.camel(), (self,))

    def not_(self) -> "CaMeLBool":
        if bool(self.python_value):
            return CaMeLFalse(camel_capabilities.Capabilities.camel(), (self,))
        return CaMeLTrue(camel_capabilities.Capabilities.camel(), (self,))

    def eq(self, value: "Value") -> "CaMeLBool":
        return (
            CaMeLTrue(camel_capabilities.Capabilities.camel(), (self, value))
            if self.python_value == value.python_value
            else CaMeLFalse(camel_capabilities.Capabilities.camel(), (self, value))
        )

    def neq(self, value: "Value") -> "Value[bool]":
        return (
            CaMeLTrue(camel_capabilities.Capabilities.camel(), (self, value))
            if self.python_value != value.python_value
            else CaMeLFalse(camel_capabilities.Capabilities.camel(), (self, value))
        )

    def hash(self) -> "Value[int]":
        return CaMeLInt(
            hash(self.raw), camel_capabilities.Capabilities.camel(), (self,)
        )

    def __hash__(self) -> int:
        return hash(self.raw) ^ hash(self._capabilities)

    def freeze(self) -> "CaMeLNone": ...

    def string(self) -> "CaMeLStr":
        return CaMeLStr.from_raw(
            str(self.python_value),
            camel_capabilities.Capabilities.camel(),
            (self,),
        )

    def type(self) -> "CaMeLStr":
        return CaMeLStr.from_raw(
            str(type(self.python_value)),
            camel_capabilities.Capabilities.camel(),
            (self,),
        )


_RT = TypeVar("_RT", bound=Value)


@runtime_checkable
class SupportsAdd(Generic[_RT], Protocol):

    def add(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsSub(Generic[_RT], Protocol):

    def sub(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsMult(Generic[_RT], Protocol):

    def mult(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsTrueDiv(Generic[_RT], Protocol):

    def truediv(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsFloorDiv(Generic[_RT], Protocol):

    def floor_div(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsMod(Generic[_RT], Protocol):

    def mod(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsPow(Generic[_RT], Protocol):

    def pow(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsLShift(Generic[_RT], Protocol):

    def l_shift(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRShift(Generic[_RT], Protocol):

    def r_shift(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsBitOr(Generic[_RT], Protocol):

    def bit_or(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsBitXor(Generic[_RT], Protocol):

    def bit_xor(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsBitAnd(Generic[_RT], Protocol):

    def bit_and(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRAdd(Generic[_RT], Protocol):

    def r_add(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRSub(Generic[_RT], Protocol):

    def r_sub(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRMult(Generic[_RT], Protocol):

    def r_mult(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRTrueDiv(Generic[_RT], Protocol):

    def r_truediv(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRFloorDiv(Generic[_RT], Protocol):

    def r_floor_div(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRMod(Generic[_RT], Protocol):

    def r_mod(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRPow(Generic[_RT], Protocol):

    def r_pow(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRLShift(Generic[_RT], Protocol):

    def r_l_shift(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRRShift(Generic[_RT], Protocol):

    def r_r_shift(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRBitOr(Generic[_RT], Protocol):

    def r_bit_or(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRBitXor(Generic[_RT], Protocol):

    def r_bit_xor(self, other: Value) -> _RT | types.NotImplementedType: ...


@runtime_checkable
class SupportsRBitAnd(Generic[_RT], Protocol):

    def r_bit_and(self, other: Value) -> _RT | types.NotImplementedType: ...


_V = TypeVar("_V", bound=Value)


def is_value(obj: Any) -> bool:
    return isinstance(obj, Value)


class PythonComparable(Protocol):

    def __lt__(self, other: Self, /) -> bool: ...

    def __gt__(self, other: Self, /) -> bool: ...


_CT = TypeVar("_CT", bound=PythonComparable)


class TotallyOrdered(Value[_CT]):

    def cmp(self, y: Self) -> "CaMeLInt":
        if self.raw > y.raw:
            return CaMeLInt(1, camel_capabilities.Capabilities.camel(), (self, y))
        if self.raw < y.raw:
            return CaMeLInt(-1, camel_capabilities.Capabilities.camel(), (self, y))
        return CaMeLInt(0, camel_capabilities.Capabilities.camel(), (self, y))


@runtime_checkable
class HasAttrs(Generic[_T], Value[_T], Protocol):

    def attr(self, name: str) -> Value | None: ...

    def attr_names(self) -> set[str]: ...


@runtime_checkable
class HasSetField(Generic[_T], HasAttrs[_T], Protocol):

    def set_field(self, name: str, value: Value) -> "CaMeLNone": ...


class FunctionCallWithSideEffectError(Exception): ...


@runtime_checkable
class CaMeLCallable(Generic[_T], Value[Callable[..., _T]], Protocol):
    """Represents a callable value in CaMeL."""

    python_value: Callable[..., _T]
    _capabilities: camel_capabilities.Capabilities
    _name: str
    _recv: Value | None
    _bound_python_value: Callable[..., _T] | None = None
    is_class_method: bool = False

    def name(self) -> "CaMeLStr":
        return CaMeLStr.from_raw(
            self._name, camel_capabilities.Capabilities.camel(), (self,)
        )

    @property
    def raw(self) -> Any:
        return self._bound_python_value or self.python_value

    def freeze(self) -> "CaMeLNone":
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable

    def string(self) -> "CaMeLStr":
        return self.name().add(
            CaMeLStr.from_raw("()", camel_capabilities.Capabilities.camel(), (self,))
        )

    def wrap_output(
        self,
        value: _T,
        args: "CaMeLTuple",
        kwargs: "CaMeLDict[CaMeLStr, Value]",
        namespace: Namespace,
    ) -> Value[_T]:
        return value_from_raw(
            value,
            camel_capabilities.Capabilities(
                frozenset({sources.Tool(self.name().raw)}),
                readers.Public(),
            ),
            namespace,
            (self, args, kwargs),
        )

    def call(
        self,
        args: "CaMeLTuple",
        kwargs: "CaMeLDict[CaMeLStr, Value]",
        namespace: Namespace,
    ) -> tuple[Value[_T], dict[str, Any]]:
        """Calls the callable value with the given arguments.

        Args:
            args: The positional arguments to pass to the callable.
            kwargs: The keyword arguments to pass to the callable.
            namespace: The current namespace. Needed to convert the output Python
              values to CaMeL values.

        Returns:
            A tuple containing the wrapped output of the callable and a dictionary
            of arguments by keyword.

        Raises:
            FunctionCallWithSideEffectError: If the call has side effects.
        """
        raw_args = args.raw
        raw_kwargs = kwargs.raw
        output = self.python_value(*raw_args, **raw_kwargs)
        if args.raw != raw_args or kwargs.raw != raw_kwargs:
            raise FunctionCallWithSideEffectError(
                "Call to a function or method with side-effects detected. "
                "Use functions and methods that have no side-effects. "
                "For example, instead of `list.append`, use list comprehensions "
                "or the [*l, new_element] syntax."
            )
        wrapped_output = self.wrap_output(output, args, kwargs, namespace)
        args_by_keyword = self._make_args_by_keyword(args, kwargs)
        return wrapped_output, args_by_keyword

    def bind_recv(self, recv: Value):
        self._recv = recv
        # Bind also to the original python method
        self._bound_python_value = types.MethodType(self.python_value, self._recv.raw)

    def receiver(self) -> Value | None:
        return self._recv

    def make_args_by_keyword_preserve_values(
        self, args: "CaMeLTuple", kwargs: "CaMeLDict[CaMeLStr, Value]"
    ) -> dict[str, Value]: ...

    def _make_args_by_keyword(
        self, args: "CaMeLTuple", kwargs: "CaMeLDict[CaMeLStr, Value]"
    ) -> dict[str, Any]:
        args_by_keyword = self.make_args_by_keyword_preserve_values(args, kwargs)
        return {k: v.raw for k, v in args_by_keyword.items()}


_IT = TypeVar("_IT", bound=Iterable)


class CaMeLIterable(Generic[_IT, _V], Value[_IT]):
    """Represents an iterable value in CaMeL."""

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple["Value", ...], frozenset[int]]:
        dependencies = self.outer_dependencies
        if id(self) in visited_objects:
            return dependencies, visited_objects
        for el in self.python_value:
            (new_dependencies, visited_objects) = el.get_dependencies(
                visited_objects | {id(self)}
            )
            dependencies += new_dependencies
        return dependencies, visited_objects | {id(self)}

    def iterate(self) -> "CaMeLIterator[_V]":
        return CaMeLIterator(
            iter(self.python_value),
            camel_capabilities.Capabilities.camel(),
            (self,),
        )

    def eq(self, value: "Value") -> "CaMeLBool":
        if not isinstance(value, type(self)):
            return CaMeLFalse(camel_capabilities.Capabilities.camel(), (self, value))
        for self_c, value_c in zip(self.python_value, value.python_value):
            if not self_c.eq(value_c).raw:
                return CaMeLFalse(
                    camel_capabilities.Capabilities.camel(), (self, value)
                )
        return CaMeLTrue(camel_capabilities.Capabilities.camel(), (self, value))

    def iterate_python(self) -> Iterator[_V]:
        return iter(self.python_value)

    def contains(self, other: Value) -> "CaMeLBool":
        inner_element = next((el for el in self.iterate_python() if el.eq(other)), None)
        if inner_element is not None:
            return CaMeLTrue(
                camel_capabilities.Capabilities.camel(), (self, other, inner_element)
            )
        # Add capabilities from elements as well as False reveal something about all
        # of them (i.e., that none of them is `other`).
        return CaMeLFalse(
            camel_capabilities.Capabilities.camel(),
            (*self.get_dependencies()[0], other),
        )


_ST = TypeVar("_ST", bound=Sequence[Value])


class CaMeLSequence(Generic[_ST, _V], CaMeLIterable[_ST, _V]):
    """Represents a sequence value in CaMeL."""

    python_value: _ST

    def index(self, index: "CaMeLInt") -> _V:
        return self.python_value[index.raw].new_with_dependencies((self, index))

    def slice(
        self,
        start: "CaMeLInt | CaMeLNone",
        end: "CaMeLInt | CaMeLNone",
        step: "CaMeLInt | CaMeLNone",
    ) -> Self:
        s = slice(start.raw, end.raw, step.raw)
        newpython_value: _ST = self.python_value[s]  # type: ignore  # can't specify CT[T] bc Python does not support higher-kinded types
        return self.new_with_python_value(newpython_value).new_with_dependencies(
            (self, start, end, step)
        )

    def len(self) -> "CaMeLInt":
        return CaMeLInt(
            len(self.python_value),
            camel_capabilities.Capabilities.camel(),
            (self, *self.python_value),
        )


_MCT = TypeVar("_MCT", bound=MutableSequence[Value])


class CaMeLMutableSequence(Generic[_MCT, _V], CaMeLSequence[_MCT, _V]):
    """Represents a mutable sequence value in CaMeL."""

    def set_index(self, index: "CaMeLInt", value: _V) -> "CaMeLNone":
        self.python_value[index.raw] = value
        return CaMeLNone(camel_capabilities.Capabilities.camel(), (self, index))


class CaMeLIterator(Generic[_V], Value[Iterator[_V]]):
    """Represents an iterator value in CaMeL."""

    def freeze(self) -> "CaMeLNone":
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable

    def __init__(
        self,
        iterator: Iterator[_V],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = iterator
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def next(self) -> _V:
        return next(self.python_value)


_MT = TypeVar("_MT", bound=Mapping)
_KV = TypeVar("_KV", bound=Value)
_VV = TypeVar("_VV", bound=Value)


class CaMeLMapping(Generic[_MT, _KV, _VV], Value[_MT]):
    """Represents a mapping value in CaMeL."""

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple["Value", ...], frozenset[int]]:
        dependencies = self.outer_dependencies
        if id(self) in visited_objects:
            return dependencies, visited_objects
        visited_objects |= {id(self)}
        for k, v in self.python_value.items():
            k_dependencies, k_visited_objects = k.get_dependencies(visited_objects)
            v_dependencies, v_visited_objects = v.get_dependencies(k_visited_objects)
            dependencies += k_dependencies + v_dependencies
            visited_objects = v_visited_objects
        return dependencies, visited_objects

    def get(self, key: _KV) -> _VV:
        dict_key = next((el for el in self.iterate_python() if el.eq(key)), None)
        if dict_key is None:
            raise KeyError(key)
        return self.python_value[dict_key].new_with_dependencies((self, key))

    def eq(self, value: "Value") -> "CaMeLBool":
        if not isinstance(value, type(self)):
            return CaMeLFalse(camel_capabilities.Capabilities.camel(), (self, value))
        for (self_k, self_v), (value_k, value_v) in zip(
            self.python_value.items(), value.python_value.items()
        ):
            if not self_k.eq(value_k).raw:
                return CaMeLFalse(
                    camel_capabilities.Capabilities.camel(), (self, value)
                )
            if not self_v.eq(value_v).raw:
                return CaMeLFalse(
                    camel_capabilities.Capabilities.camel(), (self, value)
                )
        return CaMeLTrue(camel_capabilities.Capabilities.camel(), (self, value))

    def items(self) -> "CaMeLList[CaMeLTuple]":
        items = []
        for k, v in self.python_value.items():
            items.append(
                CaMeLTuple((k, v), camel_capabilities.Capabilities.camel(), (self,))
            )
        return CaMeLList(items, self._capabilities, (self,))

    def iterate_python(self) -> Iterator[_KV]:
        return iter(self.python_value)

    def iterate(self) -> "CaMeLIterator[_KV]":
        return CaMeLIterator(
            iter(self.python_value),
            camel_capabilities.Capabilities.camel(),
            (self,),
        )

    def contains(self, other: Value) -> "CaMeLBool":
        """Checks if the mapping contains a given value.

        Args:
            other: The value to check for.

        Returns:
            A CaMeLBool indicating whether the mapping contains the value.
        """
        dependencies = [self, other]
        inner_element = next((el for el in self.iterate_python() if el.eq(other)), None)
        if inner_element is not None:
            return CaMeLTrue(
                camel_capabilities.Capabilities.camel(),
                (*dependencies, inner_element),
            )
        keys_dependencies = []
        for k in self.iterate_python():
            keys_dependencies.extend(k.get_dependencies()[0])
        return CaMeLFalse(
            camel_capabilities.Capabilities.camel(),
            (*dependencies, *keys_dependencies),
        )


_MMT = TypeVar("_MMT", bound=MutableMapping)


class CaMeLMutableMapping(Generic[_MMT, _KV, _VV], CaMeLMapping[_MMT, _KV, _VV]):
    """Represents a mutable mapping value in CaMeL."""

    python_value: _MMT

    def set_key(self, key: _KV, value: _VV) -> "CaMeLNone":
        """Sets a key-value pair in the mutable mapping.

        Args:
            key: The key to set.
            value: The value to set.

        Returns:
            A CaMeLNone indicating the operation completed.
        """
        dict_key = next((el for el in self.iterate_python() if el.eq(key).raw), None)
        if dict_key is None:
            dict_key = key
        if key is not dict_key:
            new_dict_key = dict_key.new_with_dependencies((key,))
            # Remove key value pair with key with old dependencies
            del self.python_value[dict_key]
        else:
            new_dict_key = dict_key
        self.python_value[new_dict_key] = value
        return CaMeLNone(camel_capabilities.Capabilities.camel(), (self,))


class CaMeLNone(Value[None]):
    """Represents the None value in CaMeL."""

    python_value = None

    def __init__(
        self,
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple["Value", ...],
    ) -> None:
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def freeze(self) -> "CaMeLNone":
        return self


class _Bool(TotallyOrdered[bool]):
    """Base class for CaMeL boolean values."""

    python_value: bool

    def __bool__(self):
        return self.python_value

    def __init__(
        self,
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def freeze(self) -> CaMeLNone:
        return CaMeLNone(camel_capabilities.Capabilities.camel(), (self,))


class CaMeLTrue(_Bool):  # noqa: N801
    python_value = True


class CaMeLFalse(_Bool):  # noqa: N801
    python_value = False


CaMeLBool = CaMeLTrue | CaMeLFalse


@runtime_checkable
class HasUnary(Protocol):

    def unary(self, op: ast.unaryop) -> Self | types.NotImplementedType: ...


class CaMeLFloat(
    TotallyOrdered[float],
    HasUnary,
    SupportsAdd["CaMeLFloat"],
    SupportsRAdd["CaMeLFloat"],
    SupportsSub["CaMeLFloat"],
    SupportsRSub["CaMeLFloat"],
    SupportsMult["CaMeLFloat"],
    SupportsRMult["CaMeLFloat"],
    SupportsTrueDiv["CaMeLFloat"],
    SupportsRTrueDiv["CaMeLFloat"],
    SupportsFloorDiv["CaMeLFloat"],
    SupportsRFloorDiv["CaMeLFloat"],
    SupportsMod["CaMeLFloat"],
    SupportsRMod["CaMeLFloat"],
    SupportsPow["CaMeLFloat"],
    SupportsRPow["CaMeLFloat"],
):
    """Represents a floating point number in CaMeL."""

    def __init__(
        self,
        val: float,
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = val
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def freeze(self) -> CaMeLNone:
        return CaMeLNone(self._capabilities, (self, *self.outer_dependencies))

    def add(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value + other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_add(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value + other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def sub(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value - other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_sub(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            other.python_value - self.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mult(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value * other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_mult(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            other.python_value * self.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def truediv(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value / other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_truediv(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            other.python_value / self.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def floor_div(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value // other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_floor_div(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            other.python_value // self.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mod(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value % other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_mod(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            other.python_value % self.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def pow(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value**other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_pow(self, other: Value) -> "CaMeLFloat | types.NotImplementedType":
        if not isinstance(other, CaMeLFloat | CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            other.python_value**self.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def unary(self, op: ast.unaryop) -> "CaMeLFloat | types.NotImplementedType":
        match op:
            case ast.USub():
                r = -self.python_value
            case ast.UAdd():
                r = +self.python_value
            case ast.Invert():
                raise TypeError("bad operand type for unary ~: 'float'")
            case _:
                raise NotImplementedError(f"Unary operator {op} not supported.")
        return CaMeLFloat(r, camel_capabilities.Capabilities.camel(), (self,))


class CaMeLInt(
    TotallyOrdered[int],
    HasUnary,
    SupportsAdd["CaMeLInt"],
    SupportsSub["CaMeLInt"],
    SupportsMult["CaMeLInt"],
    SupportsTrueDiv["CaMeLFloat"],
    SupportsFloorDiv["CaMeLInt"],
    SupportsMod["CaMeLInt"],
    SupportsPow["CaMeLInt"],
    SupportsLShift["CaMeLInt"],
    SupportsRShift["CaMeLInt"],
    SupportsBitOr["CaMeLInt"],
    SupportsBitXor["CaMeLInt"],
    SupportsBitAnd["CaMeLInt"],
):
    """Represents an integer value in CaMeL."""

    def __init__(
        self,
        val: int,
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = val
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def freeze(self) -> CaMeLNone:
        return CaMeLNone(camel_capabilities.Capabilities.camel(), (self,))

    def unary(self, op: ast.unaryop) -> "CaMeLInt | types.NotImplementedType":
        match op:
            case ast.USub():
                r = -self.python_value
            case ast.UAdd():
                r = +self.python_value
            case ast.Invert():
                r = ~self.python_value
            case _:
                raise NotImplementedError(f"Unary operator {op} not supported.")
        return CaMeLInt(r, self._capabilities, (self, *self.outer_dependencies))

    def add(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value + other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def sub(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value - other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mult(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value * other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def truediv(self, other: Value) -> CaMeLFloat | types.NotImplementedType:
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLFloat(
            self.python_value / other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def floor_div(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value // other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mod(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value % other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def pow(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value**other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def bit_or(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value | other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def bit_and(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value & other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def bit_xor(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value ^ other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def r_shift(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value >> other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def l_shift(self, other: Value) -> "CaMeLInt | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLInt(
            self.python_value << other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )


class _Char(TotallyOrdered[str]):
    """Represents a single character in CaMeL."""

    def __init__(
        self,
        val: str,
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = val
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def __gt__(self, other) -> bool:
        if not isinstance(other, _Char):
            return NotImplemented
        return self.python_value > other.python_value

    def __lt__(self, other) -> bool:
        if not isinstance(other, _Char):
            return NotImplemented
        return self.python_value < other.python_value

    def freeze(self) -> CaMeLNone:
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable


class CaMeLStr(
    TotallyOrdered[tuple[_Char, ...]],
    HasAttrs,
    CaMeLSequence[tuple[_Char, ...], _Char],
    SupportsAdd["CaMeLStr"],
    SupportsMult["CaMeLStr"],
    SupportsRMult["CaMeLStr"],
):
    """Represents a string in CaMeL."""

    def __init__(
        self,
        string: Sequence[_Char],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = tuple(string)
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    def contains(self, other: Value) -> "CaMeLBool":
        if not isinstance(other, CaMeLStr | _Char):
            raise TypeError(
                f"in <string>' requires string as left operand, not {other.raw_type}"
            )
        if other.raw in self.raw:
            return CaMeLTrue(
                camel_capabilities.Capabilities.camel(),
                (self, *other.get_dependencies()[0]),
            )
        # Add capabilities from elements as well as False reveal something about all
        # of them (i.e., that none of them is `other`).
        return CaMeLFalse(
            camel_capabilities.Capabilities.camel(),
            (*self.get_dependencies()[0], other),
        )

    @classmethod
    def from_raw(
        cls,
        string: str,
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> Self:
        return cls(
            tuple(_Char(c, capabilities, dependencies) for c in string),
            capabilities,
            dependencies,
        )

    def attr(self, name) -> Value | None:
        attr = SUPPORTED_BUILT_IN_METHODS[self.raw_type].get(name)
        if attr is not None:
            return attr.new_with_dependencies((self,))
        return attr

    def attr_names(self) -> set[str]:
        return set(SUPPORTED_BUILT_IN_METHODS[self.raw_type].keys())

    def string(self) -> "CaMeLStr":
        return self

    def freeze(self) -> CaMeLNone:
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable

    @property
    def raw(self) -> str:
        s = ""
        for c in self.python_value:
            s += c.python_value
        return s

    def iterate(self) -> CaMeLIterator["CaMeLStr"]:
        strings_iterator = iter(
            CaMeLStr([c], camel_capabilities.Capabilities.camel(), (self,))
            for c in self.python_value
        )
        return CaMeLIterator(
            strings_iterator, camel_capabilities.Capabilities.camel(), (self,)
        )

    @property
    def raw_type(self) -> str:
        return "str"

    def add(self, other: Value) -> "CaMeLStr | types.NotImplementedType":
        if not isinstance(other, CaMeLStr):
            return NotImplemented
        return CaMeLStr(
            self.python_value + other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mult(self, other: Value) -> "CaMeLStr | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLStr(
            self.python_value * other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    r_mult = mult


class CaMeLTuple(
    Generic[_V],
    TotallyOrdered[tuple[_V, ...]],
    CaMeLSequence[tuple[_V, ...], _V],
    SupportsAdd["CaMeLTuple"],
    SupportsMult["CaMeLTuple"],
    SupportsRMult["CaMeLTuple"],
):
    """Represents a tuple in CaMeL."""

    def __init__(
        self,
        it: Iterable[_V],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self._capabilities = capabilities
        self.python_value = tuple(it)
        self.outer_dependencies = dependencies

    @property
    def raw(self) -> tuple[Any, ...]:
        return tuple(v.raw for v in self.python_value)

    def freeze(self) -> "CaMeLNone":
        # already immutable
        return CaMeLNone(camel_capabilities.Capabilities.camel(), (self,))

    def add(self, other: "Value") -> "CaMeLTuple | types.NotImplementedType":
        if not isinstance(other, CaMeLTuple):
            return NotImplemented
        return CaMeLTuple(
            self.python_value + other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mult(self, other: "Value") -> "CaMeLTuple | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLTuple(
            self.python_value * other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    r_mult = mult


class CaMeLList(
    Generic[_V],
    TotallyOrdered[list[_V]],
    CaMeLMutableSequence[list[_V], _V],
    SupportsAdd["CaMeLList"],
    SupportsMult["CaMeLList"],
    SupportsRMult["CaMeLList"],
):
    """Represents a list in CaMeL."""

    def __init__(
        self,
        it: Iterable[_V],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = list(it)
        self._frozen = False
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    @property
    def raw(self) -> list[Any]:
        return list(v.raw for v in self.python_value)

    def attr(self, name) -> Value | None:
        attr = SUPPORTED_BUILT_IN_METHODS[self.raw_type].get(name)
        if attr is not None:
            return attr.new_with_dependencies((self,))
        return attr

    def attr_names(self) -> set[str]:
        return set(SUPPORTED_BUILT_IN_METHODS[self.raw_type].keys())

    def freeze(self) -> "CaMeLNone":
        _ = [el.freeze() for el in self.python_value]
        self._frozen = True
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self, *self.iterate_python())
        )

    def add(self, other: Value) -> "CaMeLList | types.NotImplementedType":
        if not isinstance(other, CaMeLList):
            return NotImplemented

        return CaMeLList(
            self.python_value + other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def mult(self, other: Value) -> "CaMeLList | types.NotImplementedType":
        if not isinstance(other, CaMeLInt):
            return NotImplemented
        return CaMeLList(
            self.python_value * other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    r_mult = mult


class CaMeLSet(
    Generic[_V],
    TotallyOrdered[set[_V]],
    CaMeLIterable[set[_V], _V],
    SupportsBitOr["CaMeLSet"],
    SupportsBitAnd["CaMeLSet"],
    SupportsSub["CaMeLSet"],
):
    """Represents a set in CaMeL."""

    def __init__(
        self,
        it: Iterable[_V],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = set(it)
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    @property
    def raw(self) -> set[Any]:
        return set(v.raw for v in self.python_value)

    def freeze(self) -> "CaMeLNone":
        _ = [el.freeze() for el in self.python_value]
        self._frozen = True
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self, *self.iterate_python())
        )

    def sub(self, other: Value) -> "CaMeLSet | types.NotImplementedType":
        if not isinstance(other, CaMeLSet):
            return NotImplemented
        return CaMeLSet(
            self.python_value - other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def bit_or(self, other: Value) -> "CaMeLSet | types.NotImplementedType":
        if not isinstance(other, CaMeLSet):
            return NotImplemented
        return CaMeLSet(
            self.python_value | other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def bit_xor(self, other: Value) -> "CaMeLSet | types.NotImplementedType":
        if not isinstance(other, CaMeLSet):
            return NotImplemented
        return CaMeLSet(
            self.python_value ^ other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )

    def bit_and(self, other: Value) -> "CaMeLSet | types.NotImplementedType":
        if not isinstance(other, CaMeLSet):
            return NotImplemented
        return CaMeLSet(
            self.python_value & other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )


class CaMeLDict(
    Generic[_KV, _VV],
    CaMeLMutableMapping[dict[_KV, _VV], _KV, _VV],
    SupportsBitOr["CaMeLDict[_KV, _VV]"],
    HasAttrs,
):
    """Represents a dictionary in CaMeL."""

    def __init__(
        self,
        it: Mapping[_KV, _VV],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ) -> None:
        self.python_value = dict(it)
        self._frozen = False
        self._capabilities = capabilities
        self.outer_dependencies = dependencies

    @property
    def raw(self) -> dict[Any, Any]:
        return {k.raw: v.raw for k, v in self.python_value.items()}

    def attr(self, name) -> Value | None:
        attr = SUPPORTED_BUILT_IN_METHODS[self.raw_type].get(name)
        if attr is not None:
            return attr.new_with_dependencies((self,))
        return attr

    def attr_names(self) -> set[str]:
        return set(SUPPORTED_BUILT_IN_METHODS[self.raw_type].keys())

    def freeze(self) -> "CaMeLNone":
        _ = [(k.freeze(), v.freeze()) for k, v in self.python_value.items()]
        self._frozen = True
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(),
            (self, *self.python_value.keys(), *self.python_value.values()),
        )

    def bit_or(
        self,
        other: Value,
    ) -> "CaMeLDict[_KV, _VV] | types.NotImplementedType":
        if not isinstance(other, CaMeLDict):
            return NotImplemented
        return CaMeLDict(
            self.python_value | other.python_value,
            camel_capabilities.Capabilities.camel(),
            (self, other),
        )


def _get_class_attr_names(instance: Any | type[Any]) -> set[str]:
    if dataclasses.is_dataclass(instance):
        return {f.name for f in dataclasses.fields(instance)}

    if isinstance(instance, pydantic.BaseModel) or (
        isinstance(instance, type) and issubclass(instance, pydantic.BaseModel)
    ):
        return set(instance.model_fields)

    return {
        attr
        for attr in dir(instance)
        if not (attr.startswith("__") and attr.endswith("__"))
        and not isinstance(getattr(instance, attr), Callable)
    }


class CaMeLClass(Generic[_T], CaMeLCallable[_T], HasAttrs):
    """Represents a class in CaMeL."""

    def __init__(
        self,
        name: str,
        py_callable: type[_T],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
        methods: dict[str, CaMeLCallable[Any]],
        base_classes: tuple["CaMeLClass", ...] = (),
        is_totally_ordered: bool = False,
        is_builtin: bool = False,
    ):
        self.python_value = py_callable  # type: ignore
        self._capabilities = capabilities
        self._name = name
        self._base_classes = base_classes
        self._recv: Value | None = None
        inherited_methods = {}
        for base_class in base_classes:
            inherited_methods.update(base_class.methods)
        self.methods = methods | inherited_methods
        self._is_totally_ordered = is_totally_ordered
        self.outer_dependencies = dependencies
        self.is_builtin = is_builtin

    def __hash__(self) -> int:
        return super().__hash__()

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple["Value", ...], frozenset[int]]:
        dependencies = self.outer_dependencies
        if id(self) in visited_objects:
            return dependencies, visited_objects
        for method in self.methods.values():
            new_dependencies, visited_objects = method.get_dependencies(
                visited_objects | {id(self)}
            )
            dependencies += new_dependencies
        return dependencies, visited_objects

    def init(
        self,
        namespace: Namespace,
        *args: Any,
        **kwargs: dict[str, Any],
    ) -> "CaMeLClassInstance[_T]":
        return CaMeLClassInstance(
            self.python_value(*args, **kwargs),
            self,
            self._capabilities,
            namespace,
            (self,),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CaMeLClass):
            return False
        return (
            self.python_value.__name__ == other.python_value.__name__
            and dir(self.python_value) == dir(other.python_value)
            and self._capabilities == other._capabilities
        )

    def call(
        self,
        args: CaMeLTuple,
        kwargs: CaMeLDict[CaMeLStr, Value],
        namespace: Namespace,
    ) -> tuple["CaMeLClassInstance[_T]", dict[str, Any]]:
        return self.init(
            namespace, *args.raw, **kwargs.raw
        ), self._make_args_by_keyword(args, kwargs)

    def make_args_by_keyword_preserve_values(
        self, args: "CaMeLTuple", kwargs: "CaMeLDict[CaMeLStr, Value]"
    ) -> dict[str, Value]:
        return {str(i): arg for i, arg in enumerate(args.iterate_python())} | {
            k.raw: v for k, v in kwargs.python_value.items()
        }

    def freeze(self) -> "CaMeLNone":
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable

    def attr(self, name: str) -> Value | None:
        assert isinstance(self.python_value, type)
        if issubclass(self.python_value, enum.Enum):
            try:
                val: enum.Enum = getattr(self.python_value, name)
            except AttributeError:
                return None
            if isinstance(val, str):
                return CaMeLStr.from_raw(val, self._capabilities, (self,))
            if isinstance(val, int):
                return CaMeLInt(val, self._capabilities, (self,))
            raise TypeError(f"invalid enum type: {type(val)}")
        if name not in self.methods:
            return None
        return self.methods[name].new_with_dependencies((self,))

    def attr_names(self) -> set[str]:
        class_attrs = _get_class_attr_names(self.python_value) | set(
            self.methods.keys()
        )
        return class_attrs | (
            set.union(*[c.attr_names() for c in self._base_classes])
            if self._base_classes
            else set()
        )


class CaMeLClassInstance(Generic[_T], HasSetField[_T]):
    """Represents an instance of a class in CaMeL."""

    def __init__(
        self,
        value: _T,
        camel_class: CaMeLClass[_T],
        capabilities: camel_capabilities.Capabilities,
        namespace: Namespace,
        dependencies: tuple[Value, ...],
    ):
        self.python_value = value
        self._camel_class = camel_class
        self._capabilities = capabilities
        self._namespace = namespace
        self.outer_dependencies = dependencies
        self._frozen = False

        if self._camel_class._is_totally_ordered:
            self.cmp = self._cmp

    def __hash__(self) -> int:
        return super().__hash__()

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple["Value", ...], frozenset[int]]:
        dependencies = self.outer_dependencies
        if id(self) in visited_objects:
            return dependencies, visited_objects
        for attr_name in self.attr_names():
            attr = self.attr(attr_name)
            if attr is not None and attr_name not in self._camel_class.methods:
                new_dependencies, visited_objects = attr.get_dependencies(
                    visited_objects | {id(self)}
                )
                dependencies += new_dependencies
        return dependencies, visited_objects

    def _cmp(self, y: Self) -> "CaMeLInt":
        if self.raw > y.raw:  # type: ignore  # this is hardcoded
            return CaMeLInt(1, camel_capabilities.Capabilities.camel(), (self, y))
        if self.raw < y.raw:  # type: ignore  # this is hardcoded
            return CaMeLInt(-1, camel_capabilities.Capabilities.camel(), (self, y))
        return CaMeLInt(0, camel_capabilities.Capabilities.camel(), (self, y))

    def __eq__(self, other) -> bool:
        if not isinstance(other, CaMeLClassInstance):
            return False
        return (
            self.python_value == other.python_value
            and self._camel_class == other._camel_class
            and self._capabilities == other._capabilities
            and self._frozen == other._frozen
        )

    @property
    def raw(self) -> _T:
        # create a copy of the Python instance
        instance = copy.copy(self.python_value)
        # replace all `Value` attributes with their `raw` respective
        for attr_name in self.attr_names():
            attr_value = getattr(self.python_value, attr_name)
            if isinstance(attr_value, Value):
                setattr(instance, attr_name, attr_value.raw)
        return instance

    def freeze(self) -> "CaMeLNone":
        self._frozen = True
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable

    def set_field(self, name: str, value: Value) -> "CaMeLNone":
        if self._frozen:
            raise ValueError("instance is frozen")
        setattr(self.python_value, name, value)
        return CaMeLNone(camel_capabilities.Capabilities.default(), ())

    def attr(self, name: str) -> Value | None:
        if name not in self.attr_names():
            return None
        if name in self._camel_class.methods:
            return self._camel_class.methods[name]
        attr = getattr(self.python_value, name)
        if not isinstance(attr, Value):
            return value_from_raw(
                attr, camel_capabilities.Capabilities.camel(), self._namespace, ()
            )
        return attr.new_with_dependencies((self,))

    def attr_names(self) -> set[str]:
        return self._camel_class.attr_names() | _get_class_attr_names(self.python_value)


class ValueAsWrapper(Generic[_T], CaMeLClassInstance[_T]):
    """Wraps a Python value as a CaMeL value.

    This is used when a Python value does not have a corresponding CaMeL class
    and we need to wrap it as a CaMeL value.
    """

    _camel_class: CaMeLClass[_T]
    _namespace: Namespace
    _frozen: bool

    def __init__(
        self,
        value: _T,
        capabilities: camel_capabilities.Capabilities,
        namespace: Namespace,
        dependencies: tuple[Value, ...],
    ):
        py_class = namespace.get(type(value).__name__)
        if py_class is None:
            raise NameError(f"name {type(value).__name__} is not defined")
        if not isinstance(py_class, CaMeLClass):
            raise TypeError(f"{type(value).__name__} is not callable")
        super().__init__(value, py_class, capabilities, namespace, dependencies)

    @property
    def raw(self) -> _T:
        return self.python_value

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple["Value", ...], frozenset[int]]:
        return self.outer_dependencies, visited_objects | {id(self)}

    def attr(self, name: str) -> Value | None:
        if name not in self.attr_names():
            return None
        return value_from_raw(
            getattr(self.python_value, name),
            camel_capabilities.Capabilities.camel(),
            self._namespace,
            self.outer_dependencies,
        )

    def set_field(self, name: str, value: Value) -> "CaMeLNone":
        if self._frozen:
            raise ValueError("instance is frozen")
        setattr(self.python_value, name, value.raw)
        return CaMeLNone(camel_capabilities.Capabilities.default(), ())

    def freeze(self) -> CaMeLNone:
        return CaMeLNone(
            camel_capabilities.Capabilities.camel(), (self,)
        )  # already immutable


class CaMeLFunction(Generic[_T], CaMeLCallable[_T]):
    """Represents a function in CaMeL."""

    def __init__(
        self,
        name: str,
        py_callable: Callable[..., _T],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
    ):
        self.python_value = py_callable
        self._capabilities = capabilities
        self.outer_dependencies = dependencies
        self._name = name
        self._recv: Value | None = None

    def make_args_by_keyword_preserve_values(
        self, args: "CaMeLTuple", kwargs: "CaMeLDict[CaMeLStr, Value]"
    ) -> dict[str, Value]:
        return {str(i): arg for i, arg in enumerate(args.iterate_python())} | {
            k.raw: v for k, v in kwargs.python_value.items()
        }


class UndefinedClassError(Exception): ...


def value_from_raw(
    raw_value: Any,
    capabilities: camel_capabilities.Capabilities,
    namespace: Namespace,
    dependencies: tuple[Value, ...],
) -> Value:
    match raw_value:
        # Extremely important to keep the order because in Python `bool` subclasses
        # `int`
        case bool():
            return (
                CaMeLTrue(capabilities, dependencies)
                if raw_value
                else CaMeLFalse(capabilities, dependencies)
            )
        case int():
            return CaMeLInt(raw_value, capabilities, dependencies)
        case str():
            return CaMeLStr.from_raw(raw_value, capabilities, dependencies)
        case float():
            return CaMeLFloat(raw_value, capabilities, dependencies)
        case None:
            return CaMeLNone(capabilities, dependencies)
        case list():
            return CaMeLList(
                [
                    value_from_raw(
                        val, camel_capabilities.Capabilities.camel(), namespace, ()
                    )
                    for val in raw_value
                ],
                capabilities,
                dependencies,
            )
        case dict():
            return CaMeLDict(
                {
                    value_from_raw(
                        k, camel_capabilities.Capabilities.camel(), namespace, ()
                    ): value_from_raw(v, capabilities, namespace, ())
                    for k, v in raw_value.items()
                },
                capabilities,
                dependencies,
            )
        case set():
            return CaMeLSet(
                {
                    value_from_raw(
                        val, camel_capabilities.Capabilities.camel(), namespace, ()
                    )
                    for val in raw_value
                },
                capabilities,
                dependencies,
            )
        case tuple():
            return CaMeLTuple(
                tuple(
                    value_from_raw(
                        val, camel_capabilities.Capabilities.camel(), namespace, ()
                    )
                    for val in raw_value
                ),
                capabilities,
                dependencies,
            )
        case type():
            return CaMeLClass(
                raw_value.__name__, raw_value, capabilities, dependencies, {}
            )
        case Callable():
            return CaMeLFunction(
                raw_value.__name__, raw_value, capabilities, dependencies
            )
        case _ if (
            value_class := namespace.get(type(raw_value).__name__)
        ) is not None and isinstance(value_class, CaMeLClass):
            raw_value_copy = copy.copy(raw_value)
            for attr in value_class.attr_names():
                if attr in value_class.methods:
                    continue
                try:
                    converted_attr = value_from_raw(
                        getattr(raw_value, attr),
                        camel_capabilities.Capabilities.camel(),
                        namespace,
                        (),
                    )
                    setattr(raw_value_copy, attr, converted_attr)
                except (AttributeError, RecursionError):
                    # Some built-in classes do not allow writing some attributes
                    # and/or have weird self references (which causes RecursionErrors)
                    # so we wrap the entire class for consistency
                    return ValueAsWrapper(
                        raw_value, capabilities, namespace, dependencies
                    )
            return CaMeLClassInstance(
                raw_value_copy, value_class, capabilities, namespace, dependencies
            )
        case _:
            # Value of unknown class, raise exception
            raise UndefinedClassError(f"Undefined class {type(raw_value).__name__}")


class CaMeLBuiltin(Generic[_T], CaMeLCallable[_T]):
    """Represents a built-in function or method in CaMeL."""

    is_builtin: bool = True

    def __init__(
        self,
        name: str,
        py_callable: Callable[..., _T],
        capabilities: camel_capabilities.Capabilities,
        dependencies: tuple[Value, ...],
        is_class_method: bool = False,
    ):
        self.python_value = py_callable
        self._capabilities = capabilities
        self._name = name
        self._recv: Value | None = None
        self.is_class_method = is_class_method
        self.outer_dependencies = dependencies

    def freeze(self) -> CaMeLNone:
        if self._recv is not None:
            self._recv.freeze()
            dependencies = (self, self._recv)
        else:
            dependencies = (self,)
        return CaMeLNone(camel_capabilities.Capabilities.camel(), dependencies)

    def string(self) -> CaMeLStr:
        if self._recv is None:
            return CaMeLStr.from_raw(
                f"built-in function {self._name}",
                camel_capabilities.Capabilities.camel(),
                (self,),
            )
        return CaMeLStr.from_raw(
            f"built-in method '{self._name}' of {self._recv.raw_type} object",
            camel_capabilities.Capabilities.camel(),
            (self,),
        )

    def type(self) -> CaMeLStr:
        return CaMeLStr.from_raw(
            "builtin_function_or_method",
            camel_capabilities.Capabilities.camel(),
            (self,),
        )

    def make_args_by_keyword_preserve_values(
        self, args: "CaMeLTuple", kwargs: "CaMeLDict[CaMeLStr, Value]"
    ) -> dict[str, Value]:
        return {str(i): arg for i, arg in enumerate(args.iterate_python())} | {
            k.raw: v for k, v in kwargs.python_value.items()
        }


def make_builtin(
    name: str, fn: Callable[..., _T], is_class_method: bool = False
) -> CaMeLBuiltin[_T]:
    return CaMeLBuiltin[_T](
        name, fn, camel_capabilities.Capabilities.camel(), (), is_class_method
    )


SUPPORTED_BUILT_IN_METHODS: dict[str, dict[str, CaMeLBuiltin]] = {
    "dict": {
        # "clear": make_builtin("clear", dict.clear),
        "get": make_builtin("get", dict.get),
        "items": make_builtin("items", lambda d: list(d.items())),
        "keys": make_builtin("keys", lambda d: list(d.keys())),
        # "pop": make_builtin("pop", dict.pop),
        # "popitem": make_builtin("popitem", dict.popitem),
        # "setdefault": make_builtin("setdefault", dict.setdefault),
        # "update": make_builtin("update", dict.update),
        "values": make_builtin("values", lambda d: list(d.values())),
    },
    "list": {
        # "append": make_builtin("append", list.append),
        # "clear": make_builtin("clear", list.clear),
        # "extend": make_builtin("extend", list.extend),
        "index": make_builtin("index", list.index),
        # "insert": make_builtin("insert", list.insert),
        # "pop": make_builtin("pop", list.pop),
        # "remove": make_builtin("remove", list.remove),
    },
    "str": {
        "capitalize": make_builtin("capitalize", str.capitalize),
        "count": make_builtin("count", str.count),
        "endswith": make_builtin("endswith", str.endswith),
        "find": make_builtin("find", str.find),
        "format": make_builtin("format", str.format),
        "index": make_builtin("index", str.index),
        "isalnum": make_builtin("isalnum", str.isalnum),
        "isalpha": make_builtin("isalpha", str.isalpha),
        "isdigit": make_builtin("isdigit", str.isdigit),
        "islower": make_builtin("islower", str.islower),
        "isspace": make_builtin("isspace", str.isspace),
        "istitle": make_builtin("istitle", str.istitle),
        "isupper": make_builtin("isupper", str.isupper),
        "join": make_builtin("join", str.join),
        "lower": make_builtin("lower", str.lower),
        "lstrip": make_builtin("lstrip", str.lstrip),
        "partition": make_builtin("partition", str.partition),
        "removeprefix": make_builtin("removeprefix", str.removeprefix),
        "removesuffix": make_builtin("removesuffix", str.removesuffix),
        "replace": make_builtin("replace", str.replace),
        "rfind": make_builtin("rfind", str.rfind),
        "rindex": make_builtin("rindex", str.rindex),
        "rpartition": make_builtin("rpartition", str.rpartition),
        "rsplit": make_builtin("rsplit", str.rsplit),
        "rstrip": make_builtin("rstrip", str.rstrip),
        "split": make_builtin("split", str.split),
        "splitlines": make_builtin("splitlines", str.splitlines),
        "startswith": make_builtin("startswith", str.startswith),
        "strip": make_builtin("strip", str.strip),
        "title": make_builtin("title", str.title),
        "upper": make_builtin("upper", str.upper),
    },
}
"""Built-in methods supported in Starlark (plus or minus some extra).

See https://github.com/bazelbuild/starlark/blob/master/spec.md#built-in-constants-and-functions"""
