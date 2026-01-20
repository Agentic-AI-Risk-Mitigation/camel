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

"""Utils for CaMeL agent implementation."""

from collections.abc import Iterable

from google.genai import types

from ..camel_library import function_types

FunctionCall = function_types.FunctionCall


def sanitized_part(part: types.Part) -> str:
    """Returns a sanitized string representation of expected response parts."""
    if part.thought and part.text:
        return f"<thought>{part.text}</thought>\n"
    if part.text:
        return part.text
    if part.function_call:
        return f"FunctionCall({part.function_call})"
    if part.function_response:
        response_string = str(part.function_response)
        return (
            f"FunctionResponse({response_string[:256]}"
            f"{'...' if len(response_string) > 256 else ''})"
        )
    if part.executable_code:
        return f"ExecutableCode:\n```{part.executable_code.language}\n{part.executable_code.code}\n```"
    if part.code_execution_result:
        result_string = (
            f"outcome={part.code_execution_result.outcome},"
            f" output={part.code_execution_result.output}"
        )
        return (
            f"CodeExecutionResult({result_string[:1024]}"
            f"{'...' if len(result_string) > 1024 else ''})"
        )
    return ""


def extract_print_output(
    tool_calls: Iterable[FunctionCall],
) -> str:
    """Extracts and concatenates arguments from print calls."""

    printed_output = ""
    print_calls = [tc for tc in tool_calls if tc.function == "print"]
    for print_call in print_calls:
        for arg_value in print_call.args.values():
            printed_output += str(arg_value)
    return printed_output
