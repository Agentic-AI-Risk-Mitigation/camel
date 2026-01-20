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

"""Utility functions for capabilities."""

from typing import Any, Protocol

from ..interpreter import camel_value
from . import capabilities, readers, sources


class HasDependenciesAndCapabilities(Protocol):

    def get_dependencies(
        self, visited_objects: frozenset[int] = frozenset()
    ) -> tuple[tuple[camel_value.Value, ...], frozenset[int]]: ...

    @property
    def capabilities(self) -> capabilities.Capabilities | None: ...


def get_all_readers(
    value: HasDependenciesAndCapabilities,
    visited_objects: frozenset[int] = frozenset(),
) -> tuple[readers.Readers[Any], frozenset[int]]:
    """Returns the set of readers for a value and the visited objects.

    Args:
      value: The value to get the readers for.
      visited_objects: The set of visited objects to avoid circular dependencies.

    Returns:
      A tuple containing the set of readers and the set of visited objects.
    """
    value_capabilities = value.capabilities
    if value_capabilities is None:
        return frozenset(), frozenset()
    value_readers = value_capabilities.readers_set
    if id(value) in visited_objects:
        # Catch circular dependencies.
        return value_readers, visited_objects
    for dependency in value.get_dependencies()[0]:
        if dependency == readers.Public():
            continue
        new_value_readers, visited_objects = get_all_readers(
            dependency, visited_objects | {id(value)}
        )
        if new_value_readers is not None:
            value_readers &= new_value_readers
    return value_readers, visited_objects | {id(value)}


def is_public(value: HasDependenciesAndCapabilities):
    value_readers = get_all_readers(value)[0]
    if isinstance(value_readers, frozenset):
        return readers.Public() in value_readers
    else:
        return value_readers == readers.Public()


def can_readers_read_value(
    potential_readers: set[Any], value: camel_value.Value
) -> bool:
    value_readers, _ = get_all_readers(value)
    if isinstance(value_readers, readers.Public):
        return True
    return potential_readers.issubset(value_readers)


def get_all_sources(
    value: HasDependenciesAndCapabilities,
    visited_objects: frozenset[int] = frozenset(),
) -> tuple[frozenset[sources.Source], frozenset[int]]:
    """Returns the set of sources for a value and the visited objects.

    Args:
      value: The value to get the sources for.
      visited_objects: The set of visited objects to avoid circular dependencies.

    Returns:
      A tuple containing the set of sources and the set of visited objects.
    """
    value_capabilities = value.capabilities
    if value_capabilities is None:
        return frozenset(), frozenset()
    value_sources = value_capabilities.sources_set
    # Catch circular dependencies.
    if id(value) in visited_objects:
        return value_sources, visited_objects
    for dependency in value.get_dependencies()[0]:
        new_value_sources, visited_objects = get_all_sources(
            dependency, visited_objects | {id(value)}
        )
        value_sources |= new_value_sources
    return value_sources, visited_objects


_TRUSTED_SET = frozenset(
    {
        sources.SourceEnum.USER,
        sources.SourceEnum.CAMEL,
        sources.SourceEnum.ASSISTANT,
        sources.SourceEnum.TRUSTED_TOOL_SOURCE,
    }
)


def _source_is_trusted(s: sources.Source, trusted_set: set[Any] | None) -> bool:
    trusted_set = trusted_set or _TRUSTED_SET
    if s in trusted_set:
        return True
    if (
        isinstance(s, sources.Tool)
        and not s.inner_sources
        and s.inner_sources.issubset(_TRUSTED_SET)
    ):
        return True
    return False


def is_trusted(
    value: HasDependenciesAndCapabilities, trusted_set: set[Any] | None = None
) -> bool:
    """Checks if all sources of a value are trusted.

    Args:
      value: The value to check.
      trusted_set: The set of trusted sources. If None, the default set is used.

    Returns:
      True if all sources of the value are trusted, False otherwise.
    """
    trusted_set = trusted_set or _TRUSTED_SET
    return all(
        _source_is_trusted(source, trusted_set) for source in get_all_sources(value)[0]
    )
