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

"""Security policies for tools."""

import collections.abc
import dataclasses
import fnmatch
import typing

from .capabilities import readers
from .capabilities import utils as capabilities_utils
from .interpreter import camel_value


@dataclasses.dataclass(frozen=True)
class Allowed:
    """Allowed access to the tool."""

    ...


@dataclasses.dataclass(frozen=True)
class Denied:
    """Denied access to the tool."""

    reason: str
    """Reason for denial."""


SecurityPolicyResult = Allowed | Denied


class SecurityPolicy(typing.Protocol):

    def __call__(
        self,
        tool_name: str,
        kwargs: collections.abc.Mapping[str, camel_value.Value],
    ) -> SecurityPolicyResult: ...


NO_SIDE_EFFECT_TOOLS = frozenset(
    {
        # Query AI assistant function
        "query_ai_assistant",
    }
)


def base_security_policy(
    tool_name: str,
    kwargs: collections.abc.Mapping[str, camel_value.Value],
    no_side_effect_tools: set[str],
) -> SecurityPolicyResult:
    """Base security policy.

    If *anything* in the arguments is *not* public, then access is denied.

    Args:
      tool_name: The name of the tool being called.
      kwargs: The arguments to the tool.
      no_side_effect_tools: Set of tools that do not have side effects.

    Returns:
      The result of the security policy check. Can be Allowed() or Denied().
    """
    r = [capabilities_utils.get_all_readers(data) for data in kwargs.values()]
    if (
        any(reader != readers.Public() for reader in r)
        and tool_name not in no_side_effect_tools
    ):
        return Denied("Data is not public.")
    return Allowed()


class SecurityPolicyDeniedError(Exception): ...


@typing.runtime_checkable
class SecurityPolicyEngine(typing.Protocol):
    """Protocol for a Security policy engine."""

    policies: list[tuple[str, SecurityPolicy]]
    no_side_effect_tools: set[str]

    def check_policy(
        self,
        tool_name: str,
        kwargs: collections.abc.Mapping[str, camel_value.Value],
        dependencies: collections.abc.Iterable[camel_value.Value],
    ) -> SecurityPolicyResult:
        """Checks if the tool is allowed to be executed with the given data.

        Policies in `POLICIES` are evaluated in order. If any evaluates to
        Allowed(), then the tool is executed.

        Args:
            tool_name: The name of the tool being called.
            kwargs: The arguments to the tool.
            dependencies: The dependencies of the tool.

        Returns:
            The result of the security policy check.
        """
        if tool_name in self.no_side_effect_tools:
            return Allowed()
        non_public_variables = [
            d.raw for d in dependencies if not capabilities_utils.is_public(d)
        ]
        if non_public_variables:
            return Denied(
                f"{tool_name} is state-changing and depends on private values"
                f" {non_public_variables}."
            )
        for policy_name, policy in self.policies:
            if fnmatch.fnmatch(tool_name, policy_name):
                return policy(tool_name, kwargs)
        return Denied("No security policy matched for tool. Defaulting to denial.")


class NoSecurityPolicyEngine(SecurityPolicyEngine):
    """A security policy engine that allows all tools and arguments."""

    def __init__(self) -> None:
        self.policies = []
        self.no_side_effect_tools = set()

    def check_policy(
        self,
        tool_name: str,
        kwargs: collections.abc.Mapping[str, camel_value.Value],
        dependencies: collections.abc.Iterable[camel_value.Value],
    ) -> SecurityPolicyResult:
        return Allowed()
