# Copyright 2026 Julien Bombled
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
"""Incremental Confluence writer for Cortex ingestion generations."""


def __getattr__(name: str) -> object:
    """Load the public writer only when that public attribute is requested."""
    if name != "ConfluenceWriter":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from confluence_writer.writer import ConfluenceWriter

    return ConfluenceWriter

__all__ = ["ConfluenceWriter"]
