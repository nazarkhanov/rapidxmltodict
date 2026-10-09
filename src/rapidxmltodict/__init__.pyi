"""Static API for xmltodict 0.14.2 through 1.0.4; see README typing limits."""
from collections.abc import Callable, Container, Generator, Mapping, MutableMapping
from typing import Any, BinaryIO, Literal, TextIO, Protocol, TypeVar, Union, overload

__version__: str

class ParsingInterrupted(Exception): ...

# Private aliases exist only in this stub, not as runtime exports.
_Path = list[tuple[str, Union[MutableMapping[str, Any], None]]]
class _BinaryReader(Protocol):
    def read(self, size: int, /) -> bytes: ...

class _BinaryWriter(Protocol):
    def write(self, data: bytes, /) -> Any: ...

_XMLInput = Union[str, bytes, bytearray, memoryview, _BinaryReader, Generator[Union[str, bytes, bytearray, memoryview], Any, Any]]
_Postprocessor = Callable[[_Path, str, Any], Union[tuple[Any, Any], None]]
_Predicate = Callable[[_Path, Any, Any], Any]
_Mapping = TypeVar("_Mapping", bound=MutableMapping[Any, Any])

@overload
def parse(
    xml_input: _XMLInput,
    encoding: Union[str, None] = None,
    expat: Any = ...,
    process_namespaces: bool = False,
    namespace_separator: str = ":",
    disable_entities: bool = True,
    process_comments: bool = False,
    *,
    item_depth: Literal[0] = 0,
    item_callback: Callable[[_Path, Any], Any] = ...,
    xml_attribs: bool = True,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    force_cdata: Union[bool, Container[str], _Predicate] = False,
    cdata_separator: str = "",
    postprocessor: None = None,
    dict_constructor: Callable[..., _Mapping],
    strip_whitespace: bool = True,
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    force_list: Union[bool, Container[Any], _Predicate, None] = None,
    comment_key: str = "#comment",
) -> _Mapping:
    """Parse XML; advanced options delegate to the installed xmltodict."""

@overload
def parse(
    xml_input: _XMLInput,
    encoding: Union[str, None] = None,
    expat: Any = ...,
    process_namespaces: bool = False,
    namespace_separator: str = ":",
    disable_entities: bool = True,
    process_comments: bool = False,
    *,
    item_depth: Literal[0] = 0,
    item_callback: Callable[[_Path, Any], Any] = ...,
    xml_attribs: bool = True,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    force_cdata: Union[bool, Container[str], _Predicate] = False,
    cdata_separator: str = "",
    postprocessor: None = None,
    dict_constructor: type[dict[str, Any]] = ...,
    strip_whitespace: bool = True,
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    force_list: Union[bool, Container[Any], _Predicate, None] = None,
    comment_key: str = "#comment",
) -> dict[str, Any]:
    """Parse XML; advanced options delegate to the installed xmltodict."""

@overload
def parse(
    xml_input: _XMLInput,
    encoding: Union[str, None] = None,
    expat: Any = ...,
    process_namespaces: bool = False,
    namespace_separator: str = ":",
    disable_entities: bool = True,
    process_comments: bool = False,
    *,
    item_depth: int = 0,
    item_callback: Callable[[_Path, Any], Any] = ...,
    xml_attribs: bool = True,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    force_cdata: Union[bool, Container[str], _Predicate] = False,
    cdata_separator: str = "",
    postprocessor: Union[_Postprocessor, None] = None,
    dict_constructor: Callable[..., _Mapping],
    strip_whitespace: bool = True,
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    force_list: Union[bool, Container[Any], _Predicate, None] = None,
    comment_key: str = "#comment",
) -> Union[_Mapping, None]:
    """Parse XML; advanced options delegate to the installed xmltodict."""

@overload
def parse(
    xml_input: _XMLInput,
    encoding: Union[str, None] = None,
    expat: Any = ...,
    process_namespaces: bool = False,
    namespace_separator: str = ":",
    disable_entities: bool = True,
    process_comments: bool = False,
    *,
    item_depth: int = 0,
    item_callback: Callable[[_Path, Any], Any] = ...,
    xml_attribs: bool = True,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    force_cdata: Union[bool, Container[str], _Predicate] = False,
    cdata_separator: str = "",
    postprocessor: Union[_Postprocessor, None] = None,
    dict_constructor: type[dict[Any, Any]] = ...,
    strip_whitespace: bool = True,
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    force_list: Union[bool, Container[Any], _Predicate, None] = None,
    comment_key: str = "#comment",
) -> Union[dict[Any, Any], None]:
    """Parse XML; advanced options delegate to the installed xmltodict."""

@overload
def unparse(
    input_dict: Mapping[str, Any],
    output: None = None,
    encoding: str = "utf-8",
    full_document: bool = True,
    short_empty_elements: bool = False,
    comment_key: str = "#comment",  # xmltodict 1.0.4; not 0.14.2
    *,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    depth: int = 0,
    preprocessor: Union[Callable[[str, Any], Union[tuple[str, Any], None]], None] = None,
    pretty: bool = False,
    newl: str = "\n",
    indent: Union[str, int] = "\t",
    namespace_separator: str = ":",
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    expand_iter: Union[str, None] = None,
    bytes_errors: str = "replace",  # xmltodict 1.0.4; not 0.14.2
) -> str:
    """Return XML text, or write to output and return None."""

@overload
def unparse(
    input_dict: Mapping[str, Any],
    output: Union[TextIO, BinaryIO, _BinaryWriter],
    encoding: str = "utf-8",
    full_document: bool = True,
    short_empty_elements: bool = False,
    comment_key: str = "#comment",  # xmltodict 1.0.4; not 0.14.2
    *,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    depth: int = 0,
    preprocessor: Union[Callable[[str, Any], Union[tuple[str, Any], None]], None] = None,
    pretty: bool = False,
    newl: str = "\n",
    indent: Union[str, int] = "\t",
    namespace_separator: str = ":",
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    expand_iter: Union[str, None] = None,
    bytes_errors: str = "replace",  # xmltodict 1.0.4; not 0.14.2
) -> None:
    """Return XML text, or write to output and return None."""

@overload
def unparse(
    input_dict: Mapping[str, Any],
    output: Union[TextIO, BinaryIO, _BinaryWriter, None],
    encoding: str = "utf-8",
    full_document: bool = True,
    short_empty_elements: bool = False,
    comment_key: str = "#comment",  # xmltodict 1.0.4; not 0.14.2
    *,
    attr_prefix: str = "@",
    cdata_key: str = "#text",
    depth: int = 0,
    preprocessor: Union[Callable[[str, Any], Union[tuple[str, Any], None]], None] = None,
    pretty: bool = False,
    newl: str = "\n",
    indent: Union[str, int] = "\t",
    namespace_separator: str = ":",
    namespaces: Union[Mapping[str, Union[str, None]], None] = None,
    expand_iter: Union[str, None] = None,
    bytes_errors: str = "replace",  # xmltodict 1.0.4; not 0.14.2
) -> Union[str, None]:
    """Return XML text, or write to output and return None."""

