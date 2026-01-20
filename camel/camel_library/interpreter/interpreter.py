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

# pytype: skip-file

"""Implementation of a subset of the Python interpreter.

Unfortunately, it can't be broken down in multiple files because the recursive
calls would create circular imports.
"""

import ast
import dataclasses
import enum
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Generic, NamedTuple, TypeAlias, TypeVar

import pydantic
import pydantic.fields

from .. import function_types, result, security_policy
from ..capabilities import capabilities as camel_capabilities
from ..capabilities import readers, sources
from . import camel_value, library

ExceptionASTNodes: TypeAlias = ast.expr | ast.stmt | ast.excepthandler

_E = TypeVar("_E", bound=Exception)


@dataclasses.dataclass(frozen=True)
class CaMeLException(Generic[_E]):
    """A custom exception class for CaMeL, wrapping a standard exception with additional context.

    Attributes:
        exception: The original exception object.
        nodes: A tuple of AST nodes related to the exception.
        dependencies: A tuple of CaMeL values that the exception depends on.
        capabilities: CaMeL capabilities associated with the exception.
    """

    exception: _E
    nodes: tuple[ExceptionASTNodes, ...]
    dependencies: tuple[camel_value.Value[Any], ...]
    capabilities: camel_capabilities.Capabilities = dataclasses.field(
        default_factory=camel_capabilities.Capabilities.camel
    )

    def __hash__(self) -> int:
        return hash(self.exception) ^ hash(self.nodes) ^ hash(self.capabilities)

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple[camel_value.Value[Any], ...], frozenset[int]]:
        return self.dependencies, visited_objects | {id(self)}

    def __repr__(self) -> str:
        return f"""\
CaMeLException(
  exception={type(self.exception).__name__}({self.exception}),
  nodes={[ast.dump(node) for node in self.nodes]},
  dependencies={self.get_dependencies()}
  capabilities={self.capabilities}
)"""


CaMeLResult: TypeAlias = (
    result.Ok[camel_value.Value[Any]] | result.Error[CaMeLException[Exception]]
)


def _make_not_implemented_error(
    node: ExceptionASTNodes, message: str
) -> result.Error[CaMeLException[Exception]]:
    return result.Error(CaMeLException(SyntaxError(message), (node,), ()))


def _update_error_with_node(
    error: result.Error[CaMeLException[Exception]], node: ExceptionASTNodes
):
    return result.Error(
        dataclasses.replace(error.error, nodes=(*error.error.nodes, node))
    )


_T = TypeVar("_T", bound=camel_value.Value[Any])
_E = TypeVar("_E", bound=Exception)


class EvalResult(NamedTuple):
    """Result of an evaluation."""

    result: CaMeLResult
    namespace: camel_value.Namespace
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]]
    dependencies: Iterable[camel_value.Value[Any]]


class DependenciesPropagationMode(str, enum.Enum):
    """Mode of evaluation for the interpreter.

    `STRICT` mode will propagate capabilities in a more conservative way.
    """

    STRICT = "STRICT"
    NORMAL = "NORMAL"

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


@dataclasses.dataclass(frozen=True)
class EvalArgs:
    """Evaluation arguments that remain fixed throughout execution."""

    security_policy_engine: security_policy.SecurityPolicyEngine
    """The list of security policies to apply."""
    eval_mode: DependenciesPropagationMode
    """The evaluation mode, either `STRICT` or `NORMAL`."""


def _eval_formatted_value(
    node: ast.FormattedValue,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a formatted value (e.g., f"{value}").

    Args:
        node: The AST node representing the formatted value.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    eval_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match eval_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(eval_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_value = v
        case _:
            raise ValueError("Invalid eval result type")

    if node.format_spec is not None:
        evaled_format_spec, namespace, tool_calls_chain, dependencies = camel_eval(
            node.format_spec, namespace, tool_calls_chain, dependencies, eval_args
        )
        if isinstance(evaled_format_spec, result.Error):
            return EvalResult(
                evaled_format_spec, namespace, tool_calls_chain, dependencies
            )
        evaled_format_spec = evaled_format_spec.value
    else:
        evaled_format_spec = camel_value.CaMeLNone(
            camel_capabilities.Capabilities.default(), ()
        )
    # TODO(edebenedetti): This loses character level capabilities for strings.
    # Consider handling strings differently in the future.
    str_val = evaled_value.raw
    try:
        match node.conversion:
            # No formatting
            case -1:
                formatted_evaled_data = f"{str_val:{evaled_format_spec.raw or ''}}"
            # !s formatting
            case 115:
                formatted_evaled_data = f"{str_val!s:{evaled_format_spec.raw or ''}}"
            # !r formatting
            case 114:
                formatted_evaled_data = f"{str_val!r:{evaled_format_spec.raw or ''}}"
            # !a formatting
            case 97:
                formatted_evaled_data = f"{str_val!a:{evaled_format_spec.raw or ''}}"
            case _:
                return EvalResult(
                    _make_not_implemented_error(node, "Invalid conversion specifier."),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
    except ValueError as e:
        if str(e) == "Invalid format specifier":
            return EvalResult(
                result.Error(CaMeLException(e, (node,), (evaled_format_spec,))),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        raise e

    if isinstance(evaled_format_spec, camel_value.CaMeLNone):
        deps = (evaled_value,)
    else:
        deps = (evaled_value, evaled_format_spec)

    formatted_string = camel_value.CaMeLStr.from_raw(
        formatted_evaled_data, camel_capabilities.Capabilities.camel(), deps
    )
    return EvalResult(
        result.Ok(formatted_string), namespace, tool_calls_chain, dependencies
    )


def _eval_starred_iterable(
    node: ast.Starred,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a starred expression (e.g., *iterable).

    Args:
        node: The AST node representing the starred expression.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_starred_value_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_starred_value_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_starred_value_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_starred_value = v
        case _:
            raise ValueError("Invalid eval result type")
    if not isinstance(
        evaled_starred_value, camel_value.CaMeLIterable | camel_value.CaMeLMapping
    ):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(f"Value after * must be an iterable, not {v.raw_type}"),
                    (node,),
                    (v,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    return EvalResult(
        result.Ok(evaled_starred_value), namespace, tool_calls_chain, dependencies
    )


def _eval_iterable(
    elts: Iterable[ExceptionASTNodes],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an iterable of expressions.

    Args:
        elts: The AST nodes representing the iterable elements.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_elts: list[camel_value.Value[Any]] = []
    iter_dependencies = ()
    for elt in elts:
        if isinstance(elt, ast.Starred):
            evaled_elt_res, namespace, tool_calls_chain, dependencies = (
                _eval_starred_iterable(
                    elt, namespace, tool_calls_chain, dependencies, eval_args
                )
            )
            match evaled_elt_res:
                case result.Error():
                    return EvalResult(
                        _update_error_with_node(evaled_elt_res, elt),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                case result.Ok(v):
                    # This is only the container capabilities of v as the elements'
                    # capabilities are being preserved in the elements themselves
                    iter_dependencies = (*iter_dependencies, v)
                    evaled_elts.extend(v.python_value)
                case _:
                    raise ValueError("Invalid eval result type")
        else:
            evaled_elt_res, namespace, tool_calls_chain, dependencies = camel_eval(
                elt, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_elt_res:
                case result.Error():
                    return EvalResult(
                        _update_error_with_node(evaled_elt_res, elt),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                case result.Ok(v):
                    evaled_elts.append(v)
                case _:
                    raise ValueError("Invalid eval result type")
    return EvalResult(
        result.Ok(
            camel_value.CaMeLList(
                evaled_elts,
                camel_capabilities.Capabilities.camel(),
                iter_dependencies,
            )
        ),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_joined_str(
    node: ast.JoinedStr,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a joined string (e.g., "hello" + "world").

    Args:
        node: The AST node representing the joined string.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_iterable_res, namespace, tool_calls_chain, dependencies = _eval_iterable(
        node.values, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_iterable_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_iterable_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_data: camel_value.CaMeLList[Any] = v
        case _:
            raise ValueError("Invalid eval result type")

    string = camel_value.CaMeLStr.from_raw(
        "", camel_capabilities.Capabilities.camel(), ()
    )

    for d in evaled_data.iterate_python():
        string.python_value = (*string.python_value, *d.string().python_value)
        # string = string.new_with_dependencies((d,))

    return EvalResult(result.Ok(string), namespace, tool_calls_chain, dependencies)


def _eval_constant(
    node: ast.Constant,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,  # pylint: disable=unused-argument
) -> EvalResult:
    """Evaluates a constant value (e.g., 1, "hello", True).

    Args:
        node: The AST node representing the constant value.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    # Constants are assumed to come from the user prompt and public.
    default_metadata = camel_capabilities.Capabilities.default()
    match node.value:
        case None:
            v = camel_value.CaMeLNone(default_metadata, ())
        case str():
            v = camel_value.CaMeLStr.from_raw(node.value, default_metadata, ())
        case bool():
            v = (
                camel_value.CaMeLTrue(default_metadata, ())
                if node.value
                else camel_value.CaMeLFalse(default_metadata, ())
            )
        case int():
            v = camel_value.CaMeLInt(node.value, default_metadata, ())
        case float():
            v = camel_value.CaMeLFloat(node.value, default_metadata, ())
        case _:  # bytes, complex, Ellipsis
            return EvalResult(
                result.Error(
                    CaMeLException(
                        NotImplementedError(
                            f"unsupported constant type {type(node.value).__type__}"
                        ),
                        (node,),
                        (),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
    return EvalResult(result.Ok(v), namespace, tool_calls_chain, dependencies)


def _eval_module(
    node: ast.Module,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a module (e.g., a script).

    Args:
        node: The AST node representing the module.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    return _eval_stmt_list(
        node.body, namespace, tool_calls_chain, dependencies, eval_args
    )


def _eval_name_load(
    node: ast.Name,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,  # pylint: disable=unused-argument
) -> EvalResult:
    """Evaluates a name (variable) load.

    Args:
        node: The AST node representing the name.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    match var := namespace.get(node.id):
        case None:
            r = result.Error(
                CaMeLException(
                    NameError(f"name '{node.id}' is not defined"), (node,), ()
                )
            )
        case _:
            r = result.Ok(var)
    return EvalResult(r, namespace, tool_calls_chain, dependencies)


def get_attr(
    obj: camel_value.HasAttrs[Any], name: str
) -> camel_value.Value[Any] | None:
    return obj.attr(name)


def has_attr(obj: camel_value.HasAttrs[Any], name: str) -> bool:
    return name in obj.attr_names()


def _eval_attribute_load(
    node: ast.Attribute,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a subscript load (e.g., obj[key]).

    Args:
        node: The AST node representing the subscript load.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_obj_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_obj_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_obj_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            obj = v
        case _:
            raise ValueError("Invalid eval result type")
    attr_error = result.Error(
        CaMeLException(
            AttributeError(f"'{obj.raw_type}' object has no attribute '{node.attr}'"),
            (node,),
            (),
        )
    )

    if not isinstance(obj, camel_value.HasAttrs) or not isinstance(
        obj, camel_value.Value
    ):
        return EvalResult(attr_error, namespace, tool_calls_chain, dependencies)

    attr = get_attr(obj, node.attr)
    if attr is None:
        return EvalResult(attr_error, namespace, tool_calls_chain, dependencies)

    # If this is a method, then bind the object to the method (we assume
    # `@classmethod` cannot being used) which holds as long as method definitions
    # are not supported since no built-in classes have any `@classmethod`s
    if (
        isinstance(attr, camel_value.CaMeLCallable)
        and isinstance(obj, camel_value.HasAttrs)
        # Method is already bound for `ValueAsWrapper` instances
        and not isinstance(obj, camel_value.ValueAsWrapper)
        and not attr.is_class_method
    ):
        # This should already be a copy of the original value so we can edit
        # in-place
        attr.bind_recv(obj)

    return EvalResult(result.Ok(attr), namespace, tool_calls_chain, dependencies)


def _eval_subscript_load(
    node: ast.Subscript,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a subscript load (e.g., obj[key]).

    Args:
        node: The AST node representing the subscript load.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_obj_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_obj_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_obj_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            obj = v
        case _:
            raise ValueError("Invalid eval result type")
    type_error = result.Error(
        CaMeLException(
            TypeError(f"'{obj.raw_type}' object is not subscriptable'"),
            (node,),
            (),
        )
    )

    evaled_slice_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.slice, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_slice_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_slice_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            slice_v = v
        case _:
            raise ValueError("Invalid eval result type")

    match obj:
        case camel_value.CaMeLSequence():
            if not isinstance(slice_v, camel_value.CaMeLInt):
                return EvalResult(
                    result.Error(
                        CaMeLException(
                            TypeError(
                                f"{obj.raw_type} indices must be integers not"
                                f" {slice_v.raw_type}"
                            ),
                            (node,),
                            (slice_v,),
                        )
                    ),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            try:
                return EvalResult(
                    result.Ok(obj.index(slice_v)),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            except IndexError as e:
                return EvalResult(
                    result.Error(CaMeLException(e, (node,), (slice_v, obj))),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
        case camel_value.CaMeLMapping():
            try:
                return EvalResult(
                    result.Ok(obj.get(slice_v)),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            except KeyError as e:
                return EvalResult(
                    result.Error(CaMeLException(e, (node,), (slice_v, obj))),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
        case _:
            return EvalResult(type_error, namespace, tool_calls_chain, dependencies)


def _eval_list(
    node: ast.List,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a list (e.g., [1, 2, 3]).

    Args:
        node: The AST node representing the list.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_iterable_res, namespace, tool_calls_chain, dependencies = _eval_iterable(
        node.elts, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_iterable_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_iterable_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            elts_evaled_data = v
        case _:
            raise ValueError("Invalid eval result type")

    elts_evaled_data_list = camel_value.CaMeLList(
        elts_evaled_data.iterate_python(),
        camel_capabilities.Capabilities.default(),
        elts_evaled_data.outer_dependencies,
    )

    return EvalResult(
        result.Ok(elts_evaled_data_list),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_tuple(
    node: ast.Tuple,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a tuple (e.g., (1, 2, 3)).

    Args:
        node: The AST node representing the tuple.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_iterable_res, namespace, tool_calls_chain, dependencies = _eval_iterable(
        node.elts, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_iterable_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_iterable_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            elts_evaled_data = v
        case _:
            raise ValueError("Invalid eval result type")

    elts_evaled_data_tuple = camel_value.CaMeLTuple(
        elts_evaled_data.iterate_python(),
        camel_capabilities.Capabilities.default(),
        elts_evaled_data.outer_dependencies,
    )

    return EvalResult(
        result.Ok(elts_evaled_data_tuple),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_set(
    node: ast.Set,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a set (e.g., {1, 2, 3}).

    Args:
        node: The AST node representing the set.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_iterable_res, namespace, tool_calls_chain, dependencies = _eval_iterable(
        node.elts, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_iterable_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_iterable_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            elts_evaled_data = v
        case _:
            raise ValueError("Invalid eval result type")

    elts_evaled_data_set = camel_value.CaMeLSet(
        elts_evaled_data.iterate_python(),
        camel_capabilities.Capabilities.default(),
        elts_evaled_data.outer_dependencies,
    )

    return EvalResult(
        result.Ok(elts_evaled_data_set), namespace, tool_calls_chain, dependencies
    )


def _eval_dict(
    node: ast.Dict,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a dictionary (e.g., {"key": 1, "key2": 2}).

    Args:
        node: The AST node representing the dictionary.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    result_dict = camel_value.CaMeLDict(
        {}, camel_capabilities.Capabilities.default(), ()
    )
    for key, val in zip(node.keys, node.values):
        if key is not None:
            evaled_key_res, namespace, tool_calls_chain, dependencies = camel_eval(
                key, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_key_res:
                case result.Error():
                    return EvalResult(
                        _update_error_with_node(evaled_key_res, node),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                case result.Ok(v):
                    key_evaled_data = v
                case _:
                    raise ValueError("Invalid eval result type")
            evaled_value_res, namespace, tool_calls_chain, dependencies = camel_eval(
                val, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_value_res:
                case result.Error():
                    return EvalResult(
                        _update_error_with_node(evaled_value_res, node),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                case result.Ok(v):
                    value_evaled_data = v
                case _:
                    raise ValueError("Invalid eval result type")
            result_dict.set_key(key_evaled_data, value_evaled_data)
        else:
            # If key is None, it means that it's a dictionary being expanded, i.e.
            # {..., **d}
            # https://greentreesnakes.readthedocs.io/en/latest/nodes.html#Dict
            evaled_key_res, namespace, tool_calls_chain, dependencies = camel_eval(
                val, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_key_res:
                case result.Error():
                    return EvalResult(
                        _update_error_with_node(evaled_key_res, node),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                case result.Ok(v):
                    inner_dict = v
                case _:
                    raise ValueError("Invalid eval result type")
            if not isinstance(inner_dict, camel_value.CaMeLMapping):
                return EvalResult(
                    result.Error(
                        CaMeLException(
                            TypeError(f"'{inner_dict.raw_type}' is not a mapping."),
                            (node,),
                            (),
                        )
                    ),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            result_dict = result_dict.new_with_python_value(
                result_dict.python_value | inner_dict.python_value
            ).new_with_dependencies((*result_dict.outer_dependencies, inner_dict))

    return EvalResult(result.Ok(result_dict), namespace, tool_calls_chain, dependencies)


def _assign_name(
    name: ast.Name,
    v: camel_value.Value,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Assigns a value to a name (variable).

    Args:
        name: The AST node representing the name.
        v: The value to assign.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the assignment.
    """
    assert isinstance(name.ctx, ast.Store)
    if eval_args.eval_mode == DependenciesPropagationMode.STRICT:
        # If the evaluation mode is strict, then add the dependencies to the
        # capabilities.
        v = v.new_with_dependencies(tuple(dependencies))

    # If built-in do not allow reassigning
    if (val := namespace.get(name.id)) is not None and val.is_builtin:
        return EvalResult(
            result.Error(
                CaMeLException(
                    SyntaxError(f"cannot reassign built-in {name.id}"), (name,), ()
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    updated_variables = namespace.variables | {name.id: v}
    new_namespace = dataclasses.replace(namespace, variables=updated_variables)
    return EvalResult(
        result.Ok(camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())),
        new_namespace,
        tool_calls_chain,
        dependencies,
    )


def _assign_tuple_list(
    names: ast.Tuple | ast.List,
    v: camel_value.Value[Any],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Assigns a value to a tuple or list of names (variables).

    Args:
        names: The AST node representing the tuple or list of names.
        v: The value to assign.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the assignment.
    """
    if not isinstance(v, camel_value.CaMeLSequence):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(f"cannot unpack non-iterable {v.raw_type} object"),
                    (names,),
                    (v,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    starred_names = [name for name in names.elts if isinstance(name, ast.Starred)]
    if starred_names:
        # TODO(edebenedetti): support this in the future?
        return EvalResult(
            result.Error(
                CaMeLException(
                    SyntaxError("starred expressions are not supported."),
                    (names,),
                    (v,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    data_to_assign: Sequence[camel_value.Value[Any]] = v.python_value
    if len(names.elts) != len(data_to_assign):
        return EvalResult(
            result.Error(
                CaMeLException(
                    ValueError(
                        f"too many values to unpack (expected {len(names.elts)},"
                        f" got {len(data_to_assign)})"
                    ),
                    (names,),
                    (v,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    for name, v in zip(names.elts, data_to_assign):
        assign_res, namespace, tool_calls_chain, dependencies = _assign(
            v, name, namespace, tool_calls_chain, dependencies, eval_args
        )
        if isinstance(assign_res, result.Error):
            return EvalResult(assign_res, namespace, tool_calls_chain, dependencies)
    return EvalResult(
        result.Ok(camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def set_attr(
    obj: camel_value.HasSetField[Any], name: str, value: camel_value.Value[Any]
) -> camel_value.CaMeLNone:
    return obj.set_field(name, value)


def _assign_attribute(
    attribute: ast.Attribute,
    val: camel_value.Value[Any],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Assigns a value to an attribute of an object.

    Args:
        attribute: The AST node representing the attribute.
        val: The value to assign.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the assignment.
    """
    evaled_obj_res, namespace, tool_calls_chain, dependencies = camel_eval(
        attribute.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_obj_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_obj_res, attribute),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            obj = v
        case _:
            raise ValueError("Invalid eval result type")

    attr_name = attribute.attr
    attr_error = result.Error(
        CaMeLException(
            AttributeError(f"'{v.raw_type}' object has no attribute '{attr_name}'"),
            (attribute,),
            (obj,),
        )
    )

    if (
        not isinstance(obj, camel_value.Value)
        or not isinstance(obj, camel_value.HasSetField)
        or not has_attr(obj, attr_name)
    ):
        return EvalResult(attr_error, namespace, tool_calls_chain, dependencies)

    if eval_args.eval_mode == DependenciesPropagationMode.STRICT:
        # If the evaluation mode is strict, then add the dependencies to the
        # capabilities of the object.
        obj = obj.new_with_dependencies(tuple(dependencies))
        val = val.new_with_dependencies(tuple(dependencies))

    return EvalResult(
        result.Ok(set_attr(obj, attr_name, val)),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _assign_subscript(
    subscript: ast.Subscript,
    val: camel_value.Value[Any],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Assigns a value to an element of a sequence or mapping using a subscript.

    Args:
        subscript: The AST node representing the subscript.
        val: The value to assign.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the assignment.
    """
    evaled_sequence_res, namespace, tool_calls_chain, dependencies = camel_eval(
        subscript.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_sequence_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_sequence_res, subscript),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            sequence = v
        case _:
            raise ValueError("Invalid eval result type")

    if not isinstance(
        sequence,
        camel_value.CaMeLMutableSequence | camel_value.CaMeLMutableMapping,
    ):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(
                        f"'{sequence.raw_type}' object does not support item"
                        " assignment"
                    ),
                    (subscript,),
                    (sequence,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    assert isinstance(subscript.ctx, ast.Store)
    match subscript.slice:
        case ast.Slice():
            return EvalResult(
                result.Error(
                    CaMeLException(
                        SyntaxError("slices assignments are not supported."),
                        (subscript,),
                        (sequence,),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case _:
            evaled_index_res, namespace, tool_calls_chain, dependencies = camel_eval(
                subscript.slice, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_index_res:
                case result.Error():
                    return EvalResult(
                        _update_error_with_node(evaled_index_res, subscript),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                case result.Ok(v):
                    index = v
                case _:
                    raise ValueError("Invalid eval result type")
            if eval_args.eval_mode == DependenciesPropagationMode.STRICT:
                # If the evaluation mode is strict, then add the dependencies to the
                # capabilities.
                sequence = sequence.new_with_dependencies(
                    (sequence, index, *dependencies)
                )
                val = val.new_with_dependencies((val, index, *dependencies))
            if isinstance(sequence, camel_value.CaMeLMutableSequence):
                sequence.set_index(index, val)
            else:
                sequence.set_key(index, val)

    return EvalResult(
        result.Ok(camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _assign(
    evaled_value: camel_value.Value[Any],
    target: ast.expr,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an assignment statement (e.g., x = 1).

    Args:
        evaled_value: The value to assign.
        target: The AST node representing the target.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    match target:
        case ast.Name():
            return _assign_name(
                target,
                evaled_value,
                namespace,
                tool_calls_chain,
                dependencies,
                eval_args,
            )
        case ast.Tuple() | ast.List():
            return _assign_tuple_list(
                target,
                evaled_value,
                namespace,
                tool_calls_chain,
                dependencies,
                eval_args,
            )
        case ast.Attribute():
            return _assign_attribute(
                target,
                evaled_value,
                namespace,
                tool_calls_chain,
                dependencies,
                eval_args,
            )
        case ast.Subscript():
            return _assign_subscript(
                target,
                evaled_value,
                namespace,
                tool_calls_chain,
                dependencies,
                eval_args,
            )
        case ast.Starred():
            return EvalResult(
                result.Error(
                    CaMeLException(
                        SyntaxError("starred expressions are not supported."),
                        (target,),
                        (),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case _:
            raise NotImplementedError("Unsupported assignment type")


def _eval_assign(
    node: ast.Assign,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an assignment statement (e.g., x = 1).

    Args:
        node: The AST node representing the assignment statement.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_value_res, new_namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_value_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_value_res, node),
                new_namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_value = v
        case _:
            raise ValueError("Invalid eval result type")

    for target in node.targets:
        assign_res, new_namespace, tool_calls_chain, dependencies = _assign(
            evaled_value,
            target,
            new_namespace,
            tool_calls_chain,
            dependencies,
            eval_args,
        )
        if isinstance(assign_res, result.Error):
            return EvalResult(assign_res, new_namespace, tool_calls_chain, dependencies)

    return EvalResult(
        result.Ok(evaled_value), new_namespace, tool_calls_chain, dependencies
    )


def _eval_ann_assign(
    node: ast.AnnAssign,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an annotated assignment statement (e.g., x: int = 1).

    Args:
        node: The AST node representing the annotated assignment statement.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    if node.value is None:
        return EvalResult(
            result.Ok(
                camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    evaled_value_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_value_res:
        case result.Error():
            return EvalResult(
                evaled_value_res, namespace, tool_calls_chain, dependencies
            )
        case result.Ok(v):
            evaled_value = v
        case _:
            raise ValueError("Invalid eval result type")

    assign_res, new_namespace, tool_calls_chain, dependencies = _assign(
        evaled_value,
        node.target,
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
    )
    if isinstance(assign_res, result.Error):
        return EvalResult(assign_res, new_namespace, tool_calls_chain, dependencies)
    return EvalResult(
        result.Ok(evaled_value), new_namespace, tool_calls_chain, dependencies
    )


def _eval_aug_assign(
    node: ast.AugAssign,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an augmented assignment statement (e.g., x += 1).

    Args:
        node: The AST node representing the augmented assignment statement.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_target_res, new_namespace, tool_calls_chain, dependencies = camel_eval(
        node.target, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_target_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_target_res, node),
                new_namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_target = v
        case _:
            raise ValueError("Invalid eval result type")

    evaled_value_res, new_namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_value_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_value_res, node),
                new_namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_value = v
        case _:
            raise ValueError("Invalid eval result type")

    op_result_res = _eval_bin_op_inner(node, evaled_target, evaled_value, namespace)
    match op_result_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(op_result_res, node),
                new_namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            op_result = v
        case _:
            raise ValueError("Invalid eval result type")

    return _assign(
        op_result,
        node.target,
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
    )


def _get_assigned_names(node: ast.expr) -> set[str]:
    match node:
        case ast.Name():
            return {node.id}
        case ast.List() | ast.Tuple():
            return set().union(*[_get_assigned_names(elt) for elt in node.elts])
        case _:
            return set()


def _restore_or_delete_variables(
    original_namespace: camel_value.Namespace,
    updated_namespace: camel_value.Namespace,
    comprehension_variables: set[str],
):
    """Restores or deletes variables in a namespace after a comprehension.

    Args:
        original_namespace: The original namespace before the comprehension.
        updated_namespace: The updated namespace after the comprehension.
        comprehension_variables: The set of variables assigned in the
          comprehension.

    Returns:
        The updated namespace with variables restored or deleted.
    """
    restored_variables = {}
    for var_name in comprehension_variables:
        if var_name in original_namespace.variables:
            restored_variables[var_name] = original_namespace.variables[var_name]
        else:
            del updated_namespace.variables[var_name]
    updated_namespace = dataclasses.replace(
        updated_namespace,
        variables=updated_namespace.variables | restored_variables,
    )
    return updated_namespace


def _eval_comprehensions(
    generators: list[ast.comprehension],
    elts: (
        tuple[ast.expr] | tuple[ast.expr, ast.expr]
    ),  # pylint: disable=g-one-element-tuple
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
    evaled_iterators: tuple[camel_value.Value[Any], ...],
) -> tuple[EvalResult, tuple[camel_value.Value[Any], ...]]:
    """Evaluates a list, set, or dict comprehension.

    Args:
        generators: The AST nodes representing the comprehension generators.
        elts: The AST nodes representing the comprehension elements.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.
        evaled_iterators: The iterators that have been evaluated so far.

    Returns:
        The result of the evaluation and the evaluated iterators.
    """
    if not generators:
        # Base case: no more generators
        elts_results = []
        for elt in elts:
            elt_res, namespace, tool_calls_chain, dependencies = camel_eval(
                elt, namespace, tool_calls_chain, dependencies, eval_args
            )
            if isinstance(elt_res, result.Error):
                return (
                    EvalResult(elt_res, namespace, tool_calls_chain, dependencies),
                    (),
                )
            elts_results.append(
                camel_value.CaMeLList(
                    [elt_res.value], camel_capabilities.Capabilities.default(), ()
                )
            )

        return (
            EvalResult(
                result.Ok(
                    camel_value.CaMeLTuple(
                        elts_results, camel_capabilities.Capabilities.default(), ()
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            ),
            evaled_iterators,
        )

    current_comprehension = generators[0]
    iterable_res, namespace, tool_calls_chain, dependencies = camel_eval(
        current_comprehension.iter,
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
    )
    if isinstance(iterable_res, result.Error):
        return (
            EvalResult(iterable_res, namespace, tool_calls_chain, dependencies),
            (),
        )

    iterable = iterable_res.value
    if not isinstance(iterable, camel_value.CaMeLIterable | camel_value.CaMeLMapping):
        return (
            EvalResult(
                result.Error(
                    CaMeLException(
                        TypeError(f"'{iterable.raw_type}' object is not iterable"),
                        (
                            current_comprehension.iter,
                        ),  # Use the iter node for error reporting
                        (iterable,),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            ),
            (),
        )

    accumulated_results: tuple[camel_value.CaMeLList[Any], ...] = tuple(
        camel_value.CaMeLList([], camel_capabilities.Capabilities.camel(), ())
        for _ in elts
    )
    for element in iterable.iterate_python():
        inner_namespace = dataclasses.replace(namespace)
        assign_res, inner_namespace, tool_calls_chain, dependencies = _assign(
            element,
            current_comprehension.target,
            inner_namespace,
            tool_calls_chain,
            dependencies,
            eval_args,
        )
        if isinstance(assign_res, result.Error):
            return (
                EvalResult(assign_res, namespace, tool_calls_chain, dependencies),
                (),
            )

        # evaluate ifs
        all_ifs_true = True
        for if_expr in current_comprehension.ifs:
            if_res, inner_namespace, tool_calls_chain, dependencies = camel_eval(
                if_expr, inner_namespace, tool_calls_chain, dependencies, eval_args
            )
            if isinstance(if_res, result.Error):
                return EvalResult(if_res, namespace, tool_calls_chain, dependencies), ()
            if not if_res.value.truth().raw:
                all_ifs_true = False
                break
        if not all_ifs_true:
            continue

        (
            recursive_res,
            resulting_namespace,
            tool_calls_chain,
            dependencies,
        ), evaled_iterators = _eval_comprehensions(
            generators[1:],
            elts,
            inner_namespace,
            tool_calls_chain,
            dependencies,
            eval_args,
            evaled_iterators,
        )

        namespace = _restore_or_delete_variables(
            namespace,
            resulting_namespace,
            _get_assigned_names(current_comprehension.target),
        )

        if isinstance(recursive_res, result.Error):
            return (
                EvalResult(recursive_res, namespace, tool_calls_chain, dependencies),
                (),
            )

        for acc_res, rec_res in zip(
            accumulated_results, recursive_res.value.python_value
        ):
            acc_res.python_value.extend(rec_res.python_value)

    return EvalResult(
        result.Ok(
            camel_value.CaMeLTuple(
                accumulated_results, camel_capabilities.Capabilities.default(), ()
            )
        ),
        namespace,  # Return original namespace, not inner_namespace
        tool_calls_chain,
        dependencies,
    ), (*evaled_iterators, iterable)


def _eval_list_comp(
    node: ast.ListComp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a list comprehension (e.g., [x for x in range(5)]).

    Args:
        node: The AST node representing the list comprehension.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    (
        evaled_comprehension_res,
        namespace,
        tool_calls_chain,
        dependencies,
    ), evaled_iterators = _eval_comprehensions(
        node.generators,
        (node.elt,),
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
        (),
    )
    match evaled_comprehension_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_comprehension_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_comprehension = v
        case _:
            raise ValueError("Invalid eval result type")

    return EvalResult(
        result.Ok(
            evaled_comprehension.python_value[0].new_with_dependencies(evaled_iterators)
        ),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_set_comp(
    node: ast.SetComp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a set comprehension (e.g., {x for x in range(5)}).

    Args:
        node: The AST node representing the set comprehension.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    (
        evaled_comprehension_res,
        namespace,
        tool_calls_chain,
        dependencies,
    ), evaled_iterators = _eval_comprehensions(
        node.generators,
        (node.elt,),
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
        (),
    )
    match evaled_comprehension_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_comprehension_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_comprehension = v
        case _:
            raise ValueError("Invalid eval result type")

    elements = camel_value.CaMeLSet(
        evaled_comprehension.python_value[0].iterate_python(),
        camel_capabilities.Capabilities.camel(),
        evaled_iterators,
    )

    return EvalResult(result.Ok(elements), namespace, tool_calls_chain, dependencies)


def _eval_dict_comp(
    node: ast.DictComp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a dict comprehension (e.g., {x: x*2 for x in range(5)}).

    Args:
        node: The AST node representing the dict comprehension.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    (
        evaled_comprehension_res,
        namespace,
        tool_calls_chain,
        dependencies,
    ), evaled_iterators = _eval_comprehensions(
        node.generators,
        (node.key, node.value),
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
        (),
    )
    match evaled_comprehension_res:
        case result.Error():
            return EvalResult(
                _update_error_with_node(evaled_comprehension_res, node),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case result.Ok(v):
            evaled_comprehension = v
        case _:
            raise ValueError("Invalid eval result type")

    keys, values = evaled_comprehension.iterate_python()
    elements = camel_value.CaMeLDict(
        dict(zip(keys.iterate_python(), values.iterate_python())),
        camel_capabilities.Capabilities.camel(),
        evaled_iterators,
    )

    return EvalResult(result.Ok(elements), namespace, tool_calls_chain, dependencies)


def _eval_expr(
    node: ast.Expr,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an expression (e.g., a standalone expression).

    Args:
        node: The AST node representing the expression.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    return camel_eval(node.value, namespace, tool_calls_chain, dependencies, eval_args)


def _eval_named_expr(
    node: ast.NamedExpr,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a named expression (e.g., x := 1).

    Args:
        node: The AST node representing the named expression.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_val_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.value, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_val_res:
        case result.Error():
            return EvalResult(evaled_val_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            val = v
        case _:
            raise ValueError("Invalid eval result type")
    assign_res, namespace, tool_calls_chain, dependencies = _assign_name(
        node.target,
        val,
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
    )
    if isinstance(assign_res, result.Error):
        return EvalResult(assign_res, namespace, tool_calls_chain, dependencies)
    return EvalResult(result.Ok(val), namespace, tool_calls_chain, dependencies)


_OPERAND_SYMBOLS: dict[type[ast.unaryop], str] = {
    ast.USub: "-",
    ast.UAdd: "+",
    ast.Not: "not",
    ast.Invert: "~",
}

S = TypeVar("S", bound=camel_value.HasUnary)


def unary(op: ast.unaryop, val: S) -> S:
    return val.unary(op)


def _eval_unary_op(
    node: ast.UnaryOp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a unary operation (e.g., -x, not x).

    Args:
        node: The AST node representing the unary operation.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_operand_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.operand, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_operand_res:
        case result.Error():
            return EvalResult(
                evaled_operand_res, namespace, tool_calls_chain, dependencies
            )
        case result.Ok(v):
            operand = v
        case _:
            raise ValueError("Invalid eval result type")

    # In Python all types implement `not x`
    if isinstance(node.op, ast.Not):
        return EvalResult(
            result.Ok(operand.not_()), namespace, tool_calls_chain, dependencies
        )

    if not isinstance(operand, camel_value.Value) or not isinstance(
        operand, camel_value.HasUnary
    ):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(
                        "bad operand type for unary"
                        f" {_OPERAND_SYMBOLS[type(node.op)]}: '{operand.raw_type}'"
                    ),
                    (node,),
                    (operand,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    try:
        r = result.Ok(unary(node.op, operand))
    except TypeError:
        r = result.Error(
            CaMeLException(
                TypeError(
                    f"bad operand type for unary {_OPERAND_SYMBOLS[type(node.op)]}:"
                    f" '{operand.raw_type}'"
                ),
                (node,),
                (operand,),
            )
        )

    return EvalResult(r, namespace, tool_calls_chain, dependencies)


_OPERATOR_SYMBOLS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "*",
    ast.LShift: "<<",
    ast.RShift: ">>",
    ast.BitOr: "|",
    ast.BitXor: "^",
    ast.BitAnd: "&",
}


def _make_error(
    op: ast.BinOp | ast.AugAssign,
    left: camel_value.Value[Any],
    right: camel_value.Value[Any],
) -> result.Error:
    return result.Error(
        CaMeLException(
            TypeError(
                "unsupported operand type(s) for"
                f" {_OPERATOR_SYMBOLS[type(op.op)]}: '{left.raw_type}' and"
                f" '{right.raw_type}'"
            ),
            (op,),
            (left, right),
        )
    )


BinaryOp: TypeAlias = Callable[[camel_value.Value[Any]], camel_value.Value[Any]]


def is_bound(m: Callable[..., Any]) -> bool:
    return hasattr(m, "__self__")


def _eval_bin_op_inner(
    op: ast.BinOp | ast.AugAssign,
    left: camel_value.Value[Any],
    right: camel_value.Value[Any],
    namespace: camel_value.Namespace,
) -> CaMeLResult:
    """Evaluates a binary operation.

    Args:
        op: The AST node representing the binary operation.
        left: The left operand.
        right: The right operand.
        namespace: The current namespace.

    Returns:
        The result of the evaluation.
    """
    op_map: dict[type[ast.operator], tuple[str, type[Any], type[Any]]] = {
        ast.Add: ("add", camel_value.SupportsAdd, camel_value.SupportsRAdd),
        ast.Sub: ("sub", camel_value.SupportsSub, camel_value.SupportsRSub),
        ast.Mult: ("mult", camel_value.SupportsMult, camel_value.SupportsRMult),
        ast.Div: (
            "truediv",
            camel_value.SupportsTrueDiv,
            camel_value.SupportsRTrueDiv,
        ),
        ast.Mod: ("mod", camel_value.SupportsMod, camel_value.SupportsRMod),
        ast.Pow: ("pow", camel_value.SupportsPow, camel_value.SupportsRPow),
        ast.FloorDiv: (
            "floor_div",
            camel_value.SupportsFloorDiv,
            camel_value.SupportsRFloorDiv,
        ),
        ast.BitAnd: (
            "bit_and",
            camel_value.SupportsBitAnd,
            camel_value.SupportsRBitAnd,
        ),
        ast.BitOr: (
            "bit_or",
            camel_value.SupportsBitOr,
            camel_value.SupportsRBitOr,
        ),
        ast.BitXor: (
            "bit_xor",
            camel_value.SupportsBitXor,
            camel_value.SupportsRBitXor,
        ),
        ast.LShift: (
            "l_shift",
            camel_value.SupportsLShift,
            camel_value.SupportsRLShift,
        ),
        ast.RShift: (
            "r_shift",
            camel_value.SupportsRShift,
            camel_value.SupportsRRShift,
        ),
    }

    method_name, protocol, r_protocol = op_map[type(op.op)]

    # Check for operator methods
    if isinstance(left, camel_value.CaMeLClassInstance):
        operator_method_name = f"__{method_name}__"  # Operator method name
        method_fn: camel_value.CaMeLCallable[Any] | None = left.attr(operator_method_name)  # type: ignore
        right_operator_method_name = f"__r{method_name}__"
        right_method_fn: camel_value.CaMeLCallable[Any] | None = left.attr(right_operator_method_name)  # type: ignore
        try:
            if method_fn is not None:
                # For `ValueAsWrapper` instances, the method might be bound to the
                # object
                if is_bound(method_fn.python_value):
                    r = method_fn.python_value(right.raw)
                else:
                    r = method_fn.python_value(left.raw, right.raw)
                if r is not NotImplemented:
                    return result.Ok(
                        camel_value.value_from_raw(
                            r,
                            camel_capabilities.Capabilities.camel(),
                            namespace,
                            (left, right),
                        )
                    )
                if right_method_fn is None:
                    return _make_error(op, left, right)
                if is_bound(method_fn.python_value):
                    r = right_method_fn.python_value(left.raw)
                else:
                    r = right_method_fn.python_value(right.raw, left.raw)
                if r is not NotImplemented:
                    return result.Ok(
                        camel_value.value_from_raw(
                            r,
                            camel_capabilities.Capabilities.camel(),
                            namespace,
                            (left, right),
                        )
                    )
                return _make_error(op, left, right)
        except TypeError as e:
            return result.Error(CaMeLException(e, [op], (left, right)))

    isinstance(left, protocol)
    method: BinaryOp | None = getattr(left, method_name, None)
    if isinstance(left, protocol) and method is not None:
        r = method(right)
        if r is not NotImplemented:
            return result.Ok(r)

    r_method_name = f"r_{method_name}"
    r_method: BinaryOp | None = getattr(right, r_method_name, None)

    if (
        hasattr(right, r_method_name)
        and isinstance(right, r_protocol)
        and r_method is not None
    ):  # Check if the reflected method exists
        if isinstance(right, protocol):
            r = r_method(left)
            if r is not NotImplemented:
                return result.Ok(r)

    return _make_error(op, left, right)


def _eval_bin_op(
    node: ast.BinOp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a binary operation (e.g., x + y).

    Args:
        node: The AST node representing the binary operation.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    left_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.left, namespace, tool_calls_chain, dependencies, eval_args
    )
    match left_res:
        case result.Error():
            return EvalResult(left_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            left = v
        case _:
            raise ValueError("Invalid eval result type")

    right_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.right, namespace, tool_calls_chain, dependencies, eval_args
    )
    match right_res:
        case result.Error():
            return EvalResult(right_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            right = v
        case _:
            raise ValueError("Invalid eval result type")

    return EvalResult(
        _eval_bin_op_inner(node, left, right, namespace),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_bool_op(
    node: ast.BoolOp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a boolean operation (e.g., x and y, x or y).

    Args:
        node: The AST node representing the boolean operation.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    match node.op:
        case ast.And():
            neutral_element = camel_value.CaMeLTrue(
                camel_capabilities.Capabilities.default(), ()
            )
        case ast.Or():
            neutral_element = camel_value.CaMeLFalse(
                camel_capabilities.Capabilities.default(), ()
            )
        case _:
            raise NotImplementedError(f"Boolean operator {node.op} not supported.")
    # Start with neutral element: True for AND, False for OR.
    r = neutral_element

    for v in node.values:
        evaled_value_res, namespace, tool_calls_chain, dependencies = camel_eval(
            v, namespace, tool_calls_chain, dependencies, eval_args
        )
        match evaled_value_res:
            case result.Error():
                return EvalResult(
                    evaled_value_res, namespace, tool_calls_chain, dependencies
                )
            case result.Ok(v):
                evaled_value = v
            case _:
                raise ValueError("Invalid eval result type")
        # Save bool in a Value instance, by keeping in mind that the resulting
        # expression carries all capabilities from the data that are used in it.
        # Hence, its dependency includes the previous value of r.
        r = (
            evaled_value.new_with_dependencies((r,))
            if r is not neutral_element
            else evaled_value
        )
        # If data is still equal to the neutral element (i.e. True for AND and False
        # for OR, then we continue. Otherwise we stop to preserve the
        # short-circuiting semantics.
        if r.truth().neq(neutral_element).raw:
            return EvalResult(result.Ok(r), namespace, tool_calls_chain, dependencies)
    return EvalResult(result.Ok(r), namespace, tool_calls_chain, dependencies)


def cmp(
    op: ast.Lt | ast.LtE | ast.Gt | ast.GtE,
    left: camel_value.TotallyOrdered[camel_value.PythonComparable],
    right: camel_value.TotallyOrdered[camel_value.PythonComparable],
) -> camel_value.CaMeLBool:
    """Evaluates a comparison operation (e.g., x < y).

    Args:
        op: The AST node representing the comparison operator.
        left: The left operand.
        right: The right operand.

    Returns:
        The result of the evaluation.
    """
    cmp_res = left.cmp(right)
    match op:
        case ast.Lt():
            b = camel_value.CaMeLTrue if cmp_res.raw < 0 else camel_value.CaMeLFalse
        case ast.LtE():
            b = camel_value.CaMeLTrue if cmp_res.raw <= 0 else camel_value.CaMeLFalse
        case ast.Gt():
            b = camel_value.CaMeLTrue if cmp_res.raw > 0 else camel_value.CaMeLFalse
        case ast.GtE():
            b = camel_value.CaMeLTrue if cmp_res.raw >= 0 else camel_value.CaMeLFalse
        case _:
            raise NotImplementedError(f"Comparison operator {op} not supported.")
    # Explicitly add left and right as a dependency instead of `cmp_res`
    # to improve clarity.
    return b(camel_capabilities.Capabilities.camel(), (left, right))


def in_not_in(
    op: ast.In | ast.NotIn,
    left: camel_value.Value[Any],
    right: (
        camel_value.CaMeLIterable[Iterable[Any], camel_value.Value[Any]]
        | camel_value.CaMeLMapping[
            Mapping[Any, Any], camel_value.Value[Any], camel_value.Value[Any]
        ]
    ),
) -> camel_value.CaMeLBool:
    contains = right.contains(left)
    match op:
        case ast.In():
            return contains
        case ast.NotIn():
            if contains.raw:
                return camel_value.CaMeLFalse(
                    contains.capabilities, contains.outer_dependencies
                )
            return camel_value.CaMeLTrue(
                contains.capabilities, contains.outer_dependencies
            )


_CMP_OPS_REPR = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


def _eval_compare(
    node: ast.Compare,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a comparison operation (e.g., x < y, x == y).

    Args:
        node: The AST node representing the comparison operation.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    if len(node.comparators) != 1:
        return EvalResult(
            result.Error(
                CaMeLException(
                    SyntaxError("chained comparisons are not supported"),
                    (node,),
                    (),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    if len(node.ops) != 1:
        return EvalResult(
            result.Error(
                CaMeLException(
                    SyntaxError("exactly one comparison operator is expected"),
                    (node,),
                    (),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    left_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.left, namespace, tool_calls_chain, dependencies, eval_args
    )
    match left_res:
        case result.Error():
            return EvalResult(left_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            left = v
        case _:
            raise ValueError("Invalid eval result type")
    right_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.comparators[0], namespace, tool_calls_chain, dependencies, eval_args
    )
    match right_res:
        case result.Error():
            return EvalResult(right_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            right = v
        case _:
            raise ValueError("Invalid eval result type")

    # compare
    match node.ops[0]:
        case ast.Eq():
            r = left.eq(right)
        case ast.NotEq():
            r = left.neq(right)
        case ast.Lt() | ast.LtE() | ast.Gt() | ast.GtE():
            type_error = EvalResult(
                result.Error(
                    CaMeLException(
                        TypeError(
                            f"'{_CMP_OPS_REPR[type(node.ops[0])]}' not supported"
                            f" between instances of '{left.raw_type}' and"
                            f" '{right.raw_type}'"
                        ),
                        (node,),
                        (left, right),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
            if not (hasattr(left, "cmp") or hasattr(right, "cmp")):
                return type_error
            try:
                r = cmp(node.ops[0], left, right)
            except TypeError as e:
                return EvalResult(
                    result.Error(CaMeLException(e, (node,), (left, right))),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
        case ast.Is():
            r = left.is_(right)
        case ast.IsNot():
            r = left.is_not(right)
        case ast.In() | ast.NotIn():
            if not isinstance(
                right, camel_value.CaMeLIterable | camel_value.CaMeLMapping
            ):
                return EvalResult(
                    result.Error(
                        CaMeLException(
                            TypeError(
                                f"argument of type '{right.raw_type}' is not iterable"
                            ),
                            (node,),
                            (left, right),
                        )
                    ),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            r = in_not_in(node.ops[0], left, right)
        case _:
            raise NotImplementedError(
                f"Comparison operator {node.ops[0]} not supported."
            )
    return EvalResult(result.Ok(r), namespace, tool_calls_chain, dependencies)


def _eval_if(
    node: ast.If,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an if statement.

    Args:
        node: The AST node representing the if statement.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    test_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.test, namespace, tool_calls_chain, dependencies, eval_args
    )
    match test_res:
        case result.Error():
            return EvalResult(test_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            test = v
        case _:
            raise ValueError("Invalid eval result type")
    if test.truth().python_value:
        body_res, namespace, tool_calls_chain, dependencies = _eval_stmt_list(
            node.body,
            namespace,
            tool_calls_chain,
            [*dependencies, test],
            eval_args,
        )
    elif node.orelse:
        body_res, namespace, tool_calls_chain, dependencies = _eval_stmt_list(
            node.orelse,
            namespace,
            tool_calls_chain,
            [*dependencies, test],
            eval_args,
        )
    # If/else statements can't be assigned, so what is returned is meaningless.
    else:
        return EvalResult(
            result.Ok(
                camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    dependencies = list(dependencies)
    dependencies.remove(test)

    if isinstance(body_res, result.Error):
        return EvalResult(body_res, namespace, tool_calls_chain, dependencies)

    return EvalResult(
        result.Ok(camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_if_exp(
    node: ast.IfExp,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates an if expression (e.g., x if cond else y).

    Args:
        node: The AST node representing the if expression.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    test_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.test, namespace, tool_calls_chain, dependencies, eval_args
    )
    match test_res:
        case result.Error():
            return EvalResult(test_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            test = v
        case _:
            raise ValueError("Invalid eval result type")

    inner_dependencies = [*dependencies, test]
    if test.truth().python_value:
        body_res, namespace, tool_calls_chain, dependencies = camel_eval(
            node.body,
            namespace,
            tool_calls_chain,
            inner_dependencies,
            eval_args,
        )
    else:
        body_res, namespace, tool_calls_chain, dependencies = camel_eval(
            node.orelse, namespace, tool_calls_chain, inner_dependencies, eval_args
        )

    dependencies = list(dependencies)
    dependencies.remove(test)

    if isinstance(body_res, result.Error):
        return EvalResult(body_res, namespace, tool_calls_chain, dependencies)

    return EvalResult(
        result.Ok(body_res.value.new_with_dependencies(tuple(inner_dependencies))),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_for(
    node: ast.For,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a for loop.

    Args:
        node: The AST node representing the for loop.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    if node.orelse:
        return EvalResult(
            result.Error(
                CaMeLException(
                    SyntaxError(
                        "orelse blocks in for loops are not supported because break"
                        " is not supported."
                    ),
                    (node,),
                    (),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    iterable_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.iter, namespace, tool_calls_chain, dependencies, eval_args
    )
    match iterable_res:
        case result.Error():
            return EvalResult(iterable_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            iterable = v
        case _:
            raise ValueError("Invalid eval result type")

    if not isinstance(iterable, camel_value.CaMeLIterable | camel_value.CaMeLMapping):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(f"'{iterable.raw_type}' object is not iterable"),
                    (node,),
                    (iterable,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    dependencies = [*dependencies, iterable]
    for elt in iterable.iterate_python():
        assign_res, namespace, tool_calls_chain, dependencies = _assign(
            elt,
            node.target,
            namespace,
            tool_calls_chain,
            dependencies,
            eval_args,
        )
        if isinstance(assign_res, result.Error):
            return EvalResult(assign_res, namespace, tool_calls_chain, dependencies)

        final_val_res, namespace, tool_calls_chain, dependencies = _eval_stmt_list(
            node.body,
            namespace,
            tool_calls_chain,
            # no need to add `elt` to the dependency, as whether the statement gets
            # evaluated depends on the iterable overall, and not on `elt` directly.
            # Of course if `elt` is used in the statement, this will be considered
            # by the evaluation of the statement.
            dependencies,
            eval_args,
        )
        if isinstance(final_val_res, result.Error):
            return EvalResult(final_val_res, namespace, tool_calls_chain, dependencies)

    dependencies = list(dependencies)
    dependencies.remove(iterable)

    return EvalResult(
        result.Ok(camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_stmt_list(
    stmts: Sequence[ast.stmt],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a list of statements.

    Args:
        stmts: The AST nodes representing the statements.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    # The only case where len(stmts) == 0 should be if there is no code at all
    # passed to ast.parse. In which case it's fine if it's not None. It's not
    # possible to have empty bodies for for and if/else bodies.
    val = camel_value.CaMeLNone(camel_capabilities.Capabilities.default(), ())
    for stmt in stmts:
        val_res, namespace, tool_calls_chain, dependencies = camel_eval(
            stmt, namespace, tool_calls_chain, dependencies, eval_args
        )
        match val_res:
            case result.Error():
                return EvalResult(val_res, namespace, tool_calls_chain, dependencies)
            case result.Ok(v):
                val = v
            case _:
                raise ValueError("Invalid eval result type")
    return EvalResult(result.Ok(val), namespace, tool_calls_chain, dependencies)


def _eval_args(
    args: list[ast.expr],
    fn: camel_value.Value[Any],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates function arguments.

    Args:
        args: The AST nodes representing the arguments.
        fn: The function being called.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_args: list[camel_value.Value[Any]] = []
    for arg in args:
        if not isinstance(arg, ast.Starred):
            # normal positional arg
            evaled_arg_res, namespace, tool_calls_chain, dependencies = camel_eval(
                arg, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_arg_res:
                case result.Error():
                    return EvalResult(
                        evaled_arg_res, namespace, tool_calls_chain, dependencies
                    )
                case result.Ok(v):
                    evaled_arg = v
                case _:
                    raise ValueError("Invalid eval result type")
            evaled_args.append(evaled_arg)
        else:
            # starred iterable
            evaled_arg_res, namespace, tool_calls_chain, dependencies = camel_eval(
                arg.value, namespace, tool_calls_chain, dependencies, eval_args
            )
            match evaled_arg_res:
                case result.Error():
                    return EvalResult(
                        evaled_arg_res, namespace, tool_calls_chain, dependencies
                    )
                case result.Ok(v):
                    evaled_arg = v
                case _:
                    raise ValueError("Invalid eval result type")
            if not isinstance(
                evaled_arg, camel_value.CaMeLIterable | camel_value.CaMeLMapping
            ):
                return EvalResult(
                    result.Error(
                        CaMeLException(
                            TypeError(
                                f"{fn.string().raw} argument after * must be an"
                                f" iterable, not {evaled_arg.raw_type}"
                            ),
                            (arg,),
                            (evaled_arg,),
                        )
                    ),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            evaled_args.extend(evaled_arg.iterate_python())

    return EvalResult(
        result.Ok(
            camel_value.CaMeLTuple(
                evaled_args, camel_capabilities.Capabilities.default(), ()
            )
        ),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_keywords(
    node: ast.Call,
    fn: camel_value.Value[Any],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates keyword arguments for a function call.

    Args:
        node: The AST node representing the function call.
        fn: The function being called.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_kwargs: dict[camel_value.CaMeLStr, camel_value.Value[Any]] = {}
    for keyword in node.keywords:
        kwarg_value_res, namespace, tool_calls_chain, dependencies = camel_eval(
            keyword.value, namespace, tool_calls_chain, dependencies, eval_args
        )
        match kwarg_value_res:
            case result.Error():
                return EvalResult(
                    kwarg_value_res, namespace, tool_calls_chain, dependencies
                )
            case result.Ok(v):
                kwarg_value = v
            case _:
                raise ValueError("Invalid eval result type")
        if isinstance(keyword.arg, str):
            # regular named argument
            arg = camel_value.CaMeLStr.from_raw(
                keyword.arg, camel_capabilities.Capabilities.default(), ()
            )
            if arg in evaled_kwargs:
                return EvalResult(
                    result.Error(
                        CaMeLException(
                            SyntaxError(f"keyword argument repeated: {arg.raw}"),
                            (node,),
                            (kwarg_value,),
                        )
                    ),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            evaled_kwargs[arg] = kwarg_value
        elif isinstance(kwarg_value, camel_value.CaMeLMapping):
            # **d where d is a dictionary with strings as keys.
            for arg, val in kwarg_value.python_value.items():
                if not isinstance(arg, camel_value.CaMeLStr):
                    return EvalResult(
                        result.Error(
                            CaMeLException(
                                TypeError("keywords must be strings"),
                                (node,),
                                (kwarg_value,),
                            )
                        ),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                if arg in evaled_kwargs:
                    return EvalResult(
                        result.Error(
                            CaMeLException(
                                TypeError(
                                    f"{fn.string().raw} got multiple values for keyword"
                                    f" argument: {arg.raw}"
                                ),
                                (node,),
                                (kwarg_value,),
                            )
                        ),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                evaled_kwargs[arg] = val
        else:
            return EvalResult(
                result.Error(
                    CaMeLException(
                        TypeError(
                            f"{fn.string().raw}() argument after ** must be a"
                            f" mapping, not {kwarg_value.raw_type}"
                        ),
                        (node,),
                        (kwarg_value,),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
    return EvalResult(
        result.Ok(
            camel_value.CaMeLDict(
                evaled_kwargs, camel_capabilities.Capabilities.default(), ()
            )
        ),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_call(
    node: ast.Call,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a function call.

    Args:
        node: The AST node representing the function call.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    # Evaluation order is:
    # - Object being called
    # - Positional and starred (unpacked) arguments
    # - Named arguments and double-starred, unpacked dicts
    # Only after everything is evaluated whether the function is callable is
    # checked.
    evaled_fn_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.func, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_fn_res:
        case result.Error():
            return EvalResult(evaled_fn_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            evaled_fn = v
        case _:
            raise ValueError("Invalid eval result type")
    evaled_args_res, namespace, tool_calls_chain, dependencies = _eval_args(
        node.args, evaled_fn, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_args_res:
        case result.Error():
            return EvalResult(
                evaled_args_res, namespace, tool_calls_chain, dependencies
            )
        case result.Ok(v):
            evaled_args = v
        case _:
            raise ValueError("Invalid eval result type")

    # If this is a method, place the receiver as first argument
    if evaled_fn.receiver() is not None:
        evaled_args = evaled_args.new_with_python_value(
            (evaled_fn.receiver(), *evaled_args.python_value)
        )

    evaled_kwargs_res, namespace, tool_calls_chain, dependencies = _eval_keywords(
        node, evaled_fn, namespace, tool_calls_chain, dependencies, eval_args
    )
    match evaled_kwargs_res:
        case result.Error():
            return EvalResult(
                evaled_kwargs_res, namespace, tool_calls_chain, dependencies
            )
        case result.Ok(v):
            evaled_kwargs = v
        case _:
            raise ValueError("Invalid eval result type")

    # In Python, this check is done after args are evaluated.
    if not isinstance(evaled_fn, camel_value.CaMeLCallable):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(f"'{evaled_fn.raw_type}' is not callable"),
                    (node,),
                    (evaled_fn,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    try:
        # make sure policy evaluation is constant time to prevent side-channels
        policy_check_result = eval_args.security_policy_engine.check_policy(
            evaled_fn.name().raw,
            evaled_fn.make_args_by_keyword_preserve_values(evaled_args, evaled_kwargs),
            dependencies,
        )
    except (
        Exception
    ) as e:  # pylint: disable=broad-except. # sometimes exceptions can be thrown when checking policies
        return EvalResult(
            result.Error(CaMeLException(e, (node,), (evaled_fn,))),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    if not isinstance(
        evaled_fn,
        camel_value.CaMeLBuiltin | camel_value.CaMeLClass,
    ) and isinstance(policy_check_result, security_policy.Denied):
        raise security_policy.SecurityPolicyDeniedError(
            f"Execution of tool '{evaled_fn.name().raw}' denied:"
            f" {policy_check_result.reason}"
        )

    if (
        evaled_fn.name().raw == "query_ai_assistant"
        and eval_args.eval_mode == DependenciesPropagationMode.STRICT
    ):
        dependencies = [
            *dependencies,
            *evaled_args.python_value,
            *evaled_kwargs.python_value.values(),
        ]

    try:
        ret_res, args_by_keyword = evaled_fn.call(evaled_args, evaled_kwargs, namespace)
    except (
        Exception
    ) as e:  # pylint: disable=broad-except  # catch all exceptions to be able to return them to the P-LLM
        if isinstance(e, library.NotEnoughInformationError):
            return EvalResult(
                result.Error(
                    CaMeLException(
                        e,
                        (node,),
                        (evaled_args, evaled_kwargs),
                        camel_capabilities.Capabilities(
                            sources_set=frozenset({sources.Tool(evaled_fn.name().raw)}),
                            readers_set=readers.Public(),
                        ),
                    )
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        if isinstance(e, RecursionError):
            # This should not silently fail. There could be recursion issues when the
            # object refers to another object and vice-versa, or an object refers to
            # itself
            # Same for errors in the unprivileged LLM
            raise e
        raw_args = []
        for arg in e.args:
            if isinstance(arg, camel_value.Value):
                raw_args.append(arg.raw)
            else:
                raw_args.append(arg)
        try:
            exception = type(e)(*raw_args)
        except TypeError:
            exception = e
        return EvalResult(
            result.Error(
                CaMeLException(
                    exception,
                    (node,),
                    (evaled_fn, evaled_args, evaled_kwargs),
                    camel_capabilities.Capabilities(
                        sources_set=frozenset({sources.Tool(evaled_fn.name().raw)}),
                        readers_set=readers.Public(),
                    ),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    receiver = evaled_fn.receiver()
    if receiver is not None:
        object_type = receiver.raw_type
    # Needed for ValueAsWrapper (e.g., `datetime` objects)
    # This can be removed once ValueAsWrapper is not needed anymore
    elif (
        hasattr(evaled_fn.raw, "__self__")
        and type(evaled_fn.raw.__self__).__name__ != "module"
    ):
        object_type = type(evaled_fn.raw.__self__).__name__
    else:
        object_type = None

    tool_call = function_types.FunctionCall(
        function=evaled_fn.name().raw,
        object_type=object_type,
        args=args_by_keyword,
        output=ret_res.raw,
        is_builtin=isinstance(
            evaled_fn, camel_value.CaMeLBuiltin | camel_value.CaMeLClass
        ),
    )

    return EvalResult(
        result.Ok(ret_res),
        namespace,
        [*tool_calls_chain, tool_call],
        dependencies,
    )


def _eval_expr_list(
    nodes: Iterable[ast.expr],
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a list of expressions.

    Args:
        nodes: The AST nodes representing the expressions.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    evaled_exprs: list[camel_value.Value[Any]] = []
    for node in nodes:
        evaled_expr_res, namespace, tool_calls_chain, dependencies = camel_eval(
            node, namespace, tool_calls_chain, dependencies, eval_args
        )
        match evaled_expr_res:
            case result.Error():
                return EvalResult(
                    evaled_expr_res, namespace, tool_calls_chain, dependencies
                )
            case result.Ok(v):
                evaled_exprs.append(v)
            case _:
                raise ValueError("Invalid eval result type")
    return EvalResult(
        result.Ok(
            camel_value.CaMeLTuple(
                evaled_exprs, camel_capabilities.Capabilities.default(), ()
            )
        ),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _check_decorators(decorator_list: list[ast.expr]) -> bool:
    """Checks if the decorator list contains only @dataclass or @dataclasses.dataclass.

    Args:
        decorator_list: The list of decorators to check.

    Returns:
        True if the decorator list contains only @dataclass or
        @dataclasses.dataclass, False otherwise.
    """
    if len(decorator_list) != 1:
        return False
    decorator = decorator_list[0]
    if not (
        (isinstance(decorator, ast.Name) and decorator.id == "dataclass")
        or (
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "dataclass"
            and isinstance(decorator.value, ast.Name)
            and decorator.value.id == "dataclasses"
        )
    ):
        return False
    return True


def _check_bases(
    bases_list: camel_value.CaMeLTuple[camel_value.CaMeLClass],
) -> bool:
    return {b.__name__ for b in bases_list.raw} == {"BaseModel"}


def _get_defined_classes(
    namespace: camel_value.Namespace,
) -> dict[str, type[Any]]:
    return {
        k: v.raw
        for k, v in namespace.variables.items()
        if isinstance(v, camel_value.CaMeLClass)
    }


def _parse_data_value_fields(
    valuebody: list[ast.stmt],
    namespace: camel_value.Namespace,
) -> result.Ok[list[tuple[str, type[Any]]]] | result.Error[CaMeLException[Exception]]:
    """Parses the fields of a data value class definition.

    Args:
        valuebody: The AST nodes representing the body of the class definition.
        namespace: The current namespace.

    Returns:
        A Result containing a list of tuples, where each tuple contains the field
        name and its type, or an error if parsing fails.
    """
    # parse fields
    fields = []
    for field in valuebody:
        if not isinstance(field, ast.AnnAssign):
            return result.Error(
                CaMeLException(
                    NotImplementedError(
                        "only field definitions are supported in class definitions."
                    ),
                    (field,),
                    (),
                )
            )
        if not isinstance(field.target, ast.Name):
            return result.Error(
                CaMeLException(
                    SyntaxError(
                        "cannot assign an attribute or a subscript in class"
                        " definitions.",
                    ),
                    (field,),
                    (),
                )
            )
        if field.value is not None:
            return result.Error(
                CaMeLException(
                    SyntaxError(
                        "cannot specify default values for fields in class"
                        " definitions."
                    ),
                    (field,),
                    (),
                )
            )
        field_name = field.target.id
        field_type = ast.unparse(field.annotation)
        field_type_class = namespace.get(field_type)
        if isinstance(field_type_class, camel_value.CaMeLClass):
            fields.append((field_name, field_type_class.python_value))
        else:
            # TODO(edebenedetti): used to easily evaluate type hints.
            # Ideally these are natively supported by the interpreter.
            try:
                fields.append(
                    (
                        field_name,
                        eval(
                            field_type, None, _get_defined_classes(namespace)
                        ),  # pylint: disable=eval-used
                    )
                )
            except (AttributeError, NameError) as e:
                return result.Error(CaMeLException(e, (field,), ()))
    return result.Ok(fields)


def _eval_class_def(
    node: ast.ClassDef,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a class definition."""
    if node.name in namespace.variables:
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError(
                        "You are trying to re-define the already existing class"
                        f" {node.name}. Use directly {node.name} without defining"
                        " it again."
                    ),
                    (node,),
                    (),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    bases_eval_res, namespace, tool_calls_chain, dependencies = _eval_expr_list(
        node.bases, namespace, tool_calls_chain, dependencies, eval_args
    )
    match bases_eval_res:
        case result.Error():
            return EvalResult(bases_eval_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            bases: camel_value.CaMeLTuple[camel_value.CaMeLClass[Any]] = v
        case _:
            raise ValueError("Invalid eval result type")

    # check that the definition has the `@dataclass` or `@dataclasses.dataclass`
    # decorator and no other decorator
    if not _check_decorators(node.decorator_list) and not _check_bases(bases):
        return EvalResult(
            result.Error(
                CaMeLException(
                    SyntaxError("all class definitions must inherit from BaseModel."),
                    (node,),
                    (bases,),
                )
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )

    # parse fields
    fields_res = _parse_data_value_fields(node.body, namespace)
    match fields_res:
        case result.Error():
            return EvalResult(fields_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            fields = v
        case _:
            raise ValueError("Invalid eval result type")

    # Create Python type
    python_type: type[Any]
    if len(node.decorator_list) == 1:
        # Only create a dataclass if necessary
        dataclass_python_type = dataclasses.make_dataclass(
            node.name, fields, bases=tuple(bases.raw)
        )
        python_type = pydantic.dataclasses.dataclass(dataclass_python_type)
    else:
        type_pydantic_fields: dict[str, tuple[type[Any], pydantic.fields.FieldInfo]] = {
            k: (v, pydantic.Field()) for k, v in fields
        }
        try:
            python_type = pydantic.create_model(
                node.name,
                **type_pydantic_fields,  # type: ignore
            )
        except pydantic.PydanticSchemaGenerationError as e:
            return EvalResult(
                result.Error(CaMeLException(e, (node,), ())),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        except TypeError as e:
            if "pydantic.RootModel" in str(e):
                return EvalResult(
                    result.Error(
                        CaMeLException(
                            TypeError(
                                "Can't use a RootModel. Use a normal BaseModel instead."
                            ),
                            (node,),
                            (),
                        )
                    ),
                    namespace,
                    tool_calls_chain,
                    dependencies,
                )
            raise e

    # Class definitions are assumed to come from the user prompt and public.
    value_metadata = camel_capabilities.Capabilities.default()
    value_value = camel_value.CaMeLClass(
        node.name,
        python_type,
        value_metadata,
        (),
        methods={},
        base_classes=bases.python_value,
    )
    assign_res, new_namespace, new_tool_calls_chain, dependencies = _assign(
        value_value,
        ast.Name(node.name, ast.Store()),
        namespace,
        tool_calls_chain,
        dependencies,
        eval_args,
    )
    if isinstance(assign_res, result.Error):
        return EvalResult(assign_res, new_namespace, new_tool_calls_chain, dependencies)
    return EvalResult(
        result.Ok(value_value), new_namespace, new_tool_calls_chain, dependencies
    )


def _eval_raise(
    node: ast.Raise,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Evaluates a raise statement.

    Args:
        node: The AST node representing the raise statement.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    if node.exc is None:
        return EvalResult(
            result.Error(
                CaMeLException(
                    RuntimeError("No active exception to reraise"), (node,), ()
                ),
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    exc_eval_res, namespace, tool_calls_chain, dependencies = camel_eval(
        node.exc, namespace, tool_calls_chain, dependencies, eval_args
    )
    match exc_eval_res:
        case result.Error():
            return EvalResult(exc_eval_res, namespace, tool_calls_chain, dependencies)
        case result.Ok(v):
            exc = v
        case _:
            raise ValueError("Invalid eval result type")
    if not isinstance(v, camel_value.CaMeLClassInstance) and not isinstance(
        v.python_value, Exception
    ):
        return EvalResult(
            result.Error(
                CaMeLException(
                    TypeError("exceptions must derive from BaseException"),
                    (node,),
                    (v,),
                ),
            ),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    return EvalResult(
        result.Error(
            CaMeLException(exc.raw, (node,), (exc,)),
        ),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def _eval_function_def(
    node: ast.FunctionDef,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,  # pylint: disable=unused-argument
) -> EvalResult:
    """Evaluates a function definition."""
    return EvalResult(
        _make_not_implemented_error(node, "Function definitions are not supported"),
        namespace,
        tool_calls_chain,
        dependencies,
    )


def camel_eval(
    node: ast.AST,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Interprets the given AST enforcing security policies."""
    match node:
        # Literals
        case ast.Constant():
            return _eval_constant(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.FormattedValue():
            return _eval_formatted_value(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.JoinedStr():
            return _eval_joined_str(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.List():
            return _eval_list(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Tuple():
            return _eval_tuple(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Set():
            return _eval_set(node, namespace, tool_calls_chain, dependencies, eval_args)
        case ast.Dict():
            return _eval_dict(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        # namespace, attribute and subscript loading
        case ast.Name():
            return _eval_name_load(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Attribute():
            return _eval_attribute_load(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Subscript():
            return _eval_subscript_load(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Slice():
            return EvalResult(
                _make_not_implemented_error(
                    node,
                    "Slices are not supported.",
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Statements
        case ast.Assign():
            return _eval_assign(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.AnnAssign():
            return _eval_ann_assign(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.AugAssign():
            return _eval_aug_assign(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        # Comprehensions
        case ast.ListComp():
            return _eval_list_comp(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.SetComp():
            return _eval_set_comp(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.DictComp():
            return _eval_dict_comp(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        # Expressions
        case ast.Expr():
            return _eval_expr(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.NamedExpr():
            return _eval_named_expr(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.UnaryOp():
            return _eval_unary_op(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.BinOp():
            return _eval_bin_op(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.BoolOp():
            return _eval_bool_op(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Compare():
            return _eval_compare(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        # Control flow
        case ast.If():
            return _eval_if(node, namespace, tool_calls_chain, dependencies, eval_args)
        case ast.IfExp():
            return _eval_if_exp(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.For():
            return _eval_for(node, namespace, tool_calls_chain, dependencies, eval_args)
        case ast.Call():
            return _eval_call(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        # Rest
        case ast.Module():
            return _eval_module(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.ClassDef():
            return _eval_class_def(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.FunctionDef():
            return _eval_function_def(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Raise():
            return _eval_raise(
                node, namespace, tool_calls_chain, dependencies, eval_args
            )
        case ast.Pass():
            return EvalResult(
                result.Ok(
                    camel_value.CaMeLNone(camel_capabilities.Capabilities.camel(), ())
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # The following are unsupported language constructs
        case ast.GeneratorExp():
            return EvalResult(
                _make_not_implemented_error(
                    node,
                    "Generator expressions are not supported. Use a list"
                    " comprehension instead if possible.",
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.While():
            return EvalResult(
                _make_not_implemented_error(
                    node,
                    "While statements are not supported. Use a for loop instead.",
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.Break():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Break statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.Continue():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Continue statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.Match():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Match statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Function and class definitions (not supported)
        case ast.Lambda():
            return EvalResult(
                _make_not_implemented_error(
                    node,
                    "Defining lambda functions is not supported. If you are operating"
                    " on a list, consider using a list comprehension or a for loop.",
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Reuturn, yield, yield from (not supported)
        case ast.Return():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Return statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.Yield():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Yield statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.YieldFrom():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Yield from statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Exceptions and assertions (not supported)
        case ast.ExceptHandler() | ast.Try():
            return EvalResult(
                _make_not_implemented_error(
                    node,
                    "Try blocks are are not supported. DO not try to catch"
                    " exceptions.",
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.Assert():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Assert statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Delete (not supported):
        case ast.Delete():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Delete statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Context managers (not supported):
        case ast.With():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Context managers are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Async (not supported)
        case ast.AsyncFor() | ast.AsyncWith() | ast.AsyncFunctionDef() | ast.Await():
            return EvalResult(
                _make_not_implemented_error(node, "Async is not supported."),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Global and non-local (not supported)
        case ast.Global():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Global statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.Nonlocal():
            return EvalResult(
                _make_not_implemented_error(
                    node, "Nonlocal statements are not supported."
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        # Imports (not supported)
        case ast.Import():
            return EvalResult(
                _make_not_implemented_error(
                    node,
                    "You can't import modules. Instead, use what you have been"
                    " provided as described in the system prompt, which you can"
                    " assume has already been imported.",
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case ast.ImportFrom():
            # Just skip imports, do not raise exceptions if an import is issued. The
            # model is likely trying to import something that is already included
            # (e.g., Pydantic)
            for alias in node.names:
                if alias.name not in namespace.variables:
                    return EvalResult(
                        _make_not_implemented_error(
                            node,
                            f"You can't import {alias.name}. Instead, use what you have"
                            " been provided as described in the system prompt, which you"
                            " can assume has already been imported.",
                        ),
                        namespace,
                        tool_calls_chain,
                        dependencies,
                    )
                if alias.asname is not None:
                    namespace.variables[alias.asname] = namespace.variables[alias.name]
                    del namespace.variables[alias.name]
            return EvalResult(
                result.Ok(
                    camel_value.CaMeLNone(camel_capabilities.Capabilities.camel(), ())
                ),
                namespace,
                tool_calls_chain,
                dependencies,
            )
        case _:
            raise NotImplementedError(
                f"Node of type {type(node).__name__} is not supported."
            )


class InvalidOutputError(Exception): ...


def extract_code_block(markdown_text: str) -> str:
    """Parses code fences in Markdown text and extracts language and code.

    Args:
        markdown_text: The Markdown text to parse.

    Returns:
        A list of dictionaries, where each dictionary contains:
            - "language": The language of the code (or None if not specified).
            - "code": The code block itself.
        Returns an empty list if no code fences are found.
        Returns None if the input is not a string.
    Raises:
        InvalidOutputError: If the code block is empty or if there are multiple
        code blocks.
    """
    code_fences = []
    # Regular expression to match code fences
    # Matches ``` followed by optional language, then any characters (non-greedy),
    # followed by a matching ```. The re.DOTALL flag makes '.' match newlines.
    pattern = r"```([a-zA-Z0-9_+\-#]*)\n(.*?)\n```"
    matches = re.findall(pattern, markdown_text, re.DOTALL)

    for match in matches:
        _ = match[0].strip() or None  # Handle empty language specifiers
        code = match[1].strip()
        code_fences.append(code)

    if len(code_fences) != 1:
        raise InvalidOutputError(
            "You must provide exactly one non-empty code block in markdown format."
        )

    return code_fences[0]


def parse_and_interpret_code(
    code: str,
    namespace: camel_value.Namespace,
    tool_calls_chain: Sequence[function_types.FunctionCall[Any]],
    dependencies: Iterable[camel_value.Value[Any]],
    eval_args: EvalArgs,
) -> EvalResult:
    """Parses and interprets the given code enforcing security policies.

    Args:
        code: The code to parse and interpret.
        namespace: The current namespace.
        tool_calls_chain: The current chain of tool calls.
        dependencies: The current dependencies.
        eval_args: The evaluation arguments.

    Returns:
        The result of the evaluation.
    """
    try:
        code = extract_code_block(code)
    except InvalidOutputError as e:
        error_nodes: tuple[ExceptionASTNodes, ...] = (
            ast.expr(
                lineno=0,
                end_lineno=-1,
            ),
        )
        return EvalResult(
            result.Error(CaMeLException(e, error_nodes, ())),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    try:
        parsed_code = ast.parse(code)
    except SyntaxError as e:
        error_nodes: tuple[ExceptionASTNodes, ...] = (
            ast.expr(
                lineno=e.lineno or 0,
                end_lineno=e.end_lineno,
            ),
        )
        return EvalResult(
            result.Error(CaMeLException(e, error_nodes, ())),
            namespace,
            tool_calls_chain,
            dependencies,
        )
    return EvalResult(
        *camel_eval(parsed_code, namespace, tool_calls_chain, dependencies, eval_args)
    )
