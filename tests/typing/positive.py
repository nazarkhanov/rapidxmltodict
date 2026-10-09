from collections import OrderedDict
from collections.abc import MutableMapping
from io import BytesIO, StringIO
from typing import Any, Optional
from typing_extensions import assert_type
import rapidxmltodict as xml

assert_type(xml.parse('<root/>'), dict[str, Any])
assert_type(xml.parse(bytearray(b'<root/>')), dict[str, Any])
assert_type(xml.parse(BytesIO(b'<root/>')), dict[str, Any])
assert_type(xml.parse(part for part in ['<root>', '</root>']), dict[str, Any])

def make_mapping(*args: Any) -> OrderedDict[str, Any]:
    return OrderedDict(*args)

assert_type(xml.parse('<root/>', dict_constructor=make_mapping), OrderedDict[str, Any])

def depth_from_config() -> int:
    return 2

assert_type(xml.parse('<root/>', item_depth=depth_from_config()), Optional[dict[Any, Any]])
assert_type(xml.parse('<root/>', item_depth=2, dict_constructor=make_mapping), Optional[OrderedDict[str, Any]])

def process(path: list[tuple[str, Optional[MutableMapping[str, Any]]]],
            key: str, value: Any) -> Optional[tuple[Any, Any]]:
    return key, value

assert_type(xml.parse('<root/>', postprocessor=process), Optional[dict[Any, Any]])
xml.parse('<r/>', encoding='utf-8', process_namespaces=True,
          namespace_separator=':', disable_entities=True, process_comments=True,
          item_depth=1, item_callback=lambda path, item: True,
          xml_attribs=True, attr_prefix='@', cdata_key='#text',
          force_cdata=lambda path, key, value: key == 'r', cdata_separator='',
          postprocessor=process, dict_constructor=make_mapping,
          strip_whitespace=False, namespaces={'urn:test': None},
          force_list=('r',), comment_key='#comment')
xml.parse('<r/>', force_cdata=('r',), force_list=True)
xml.parse('<r/>', force_list=lambda path, key, value: bool(value))
assert_type(xml.unparse({'r': None}), str)
assert_type(xml.unparse({'r': None}, StringIO()), None)
assert_type(xml.unparse({'r': None}, BytesIO()), None)

def maybe_output(output: Optional[StringIO]) -> None:
    assert_type(xml.unparse({'r': None}, output), Optional[str])

xml.unparse({'r': None}, encoding='utf-8', full_document=True,
            short_empty_elements=True, comment_key='#comment',
            attr_prefix='@', cdata_key='#text', depth=0,
            preprocessor=lambda key, value: (key, value), pretty=True,
            newl='\n', indent=2, namespace_separator=':',
            namespaces={'urn:test': 't'}, expand_iter='item', bytes_errors='strict')
error: Exception = xml.ParsingInterrupted()
version: str = xml.__version__

class NamedDict(dict[str, Any]):
    pass
assert_type(xml.parse('<root/>', dict_constructor=NamedDict), NamedDict)
assert_type(xml.parse('<root/>', dict_constructor=NamedDict, item_depth=2), Optional[NamedDict])
class Reader:
    def read(self, size: int) -> bytes:
        return b''
class Writer:
    def write(self, data: bytes) -> int:
        return len(data)
assert_type(xml.parse(Reader()), dict[str, Any])
assert_type(xml.unparse({'r': None}, Writer()), None)
xml.parse('<r/>', postprocessor=lambda path, key, value: (17, value), force_list=(17,))
