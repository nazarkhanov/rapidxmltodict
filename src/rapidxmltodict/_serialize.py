"""Standalone dictionary-to-XML serialization compatible with xmltodict 1.0.4.

The implementation is adapted from xmltodict v1.0.4, under its MIT license:
https://github.com/martinblech/xmltodict/blob/v1.0.4/xmltodict.py

Only standard-library SAX *output* helpers are used. No parser, xmltodict,
or Expat backend is imported or called.
"""

# Copyright (C) 2012 Martin Blech and individual contributors.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#

import codecs
from io import StringIO
from xml.sax.saxutils import XMLGenerator, escape
from xml.sax.xmlreader import AttributesImpl


def _convert_value_to_string(value, encoding='utf-8', bytes_errors='replace'):
    """Convert a value to its string representation for XML output.

    Handles boolean values consistently by converting them to lowercase.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode(encoding, errors=bytes_errors)
    return str(value)


def _validate_name(value, kind):
    """Validate an element/attribute name for XML safety.

    Raises ValueError with a specific reason when invalid.

    kind: 'element' or 'attribute' (used in error messages)
    """
    if not isinstance(value, str):
        raise ValueError(f"{kind} name must be a string")
    if value.startswith("?") or value.startswith("!"):
        raise ValueError(f'Invalid {kind} name: cannot start with "?" or "!"')
    if "<" in value or ">" in value:
        raise ValueError(f'Invalid {kind} name: "<" or ">" not allowed')
    if "/" in value:
        raise ValueError(f'Invalid {kind} name: "/" not allowed')
    if '"' in value or "'" in value:
        raise ValueError(f"Invalid {kind} name: quotes not allowed")
    if "=" in value:
        raise ValueError(f'Invalid {kind} name: "=" not allowed')
    if any(ch.isspace() for ch in value):
        raise ValueError(f"Invalid {kind} name: whitespace not allowed")


def _validate_comment(value):
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Comment text must be valid UTF-8") from exc
    if not isinstance(value, str):
        raise ValueError("Comment text must be a string")
    if "--" in value:
        raise ValueError("Comment text cannot contain '--'")
    if value.endswith("-"):
        raise ValueError("Comment text cannot end with '-'")
    return value


def _process_namespace(name, namespaces, ns_sep=':', attr_prefix='@'):
    if not isinstance(name, str):
        return name
    if not namespaces:
        return name
    try:
        ns, name = name.rsplit(ns_sep, 1)
    except ValueError:
        pass
    else:
        ns_res = namespaces.get(ns.strip(attr_prefix))
        name = '{}{}{}{}'.format(
            attr_prefix if ns.startswith(attr_prefix) else '',
            ns_res, ns_sep, name) if ns_res else name
    return name


def _emit(key, value, content_handler,
          attr_prefix='@',
          cdata_key='#text',
          depth=0,
          preprocessor=None,
          pretty=False,
          newl='\n',
          indent='\t',
          namespace_separator=':',
          namespaces=None,
          full_document=True,
          expand_iter=None,
          encoding='utf-8',
          bytes_errors='replace',
          comment_key='#comment'):
    if isinstance(key, str) and key == comment_key:
        comments_list = value if isinstance(value, list) else [value]
        if isinstance(indent, int):
            indent = " " * indent
        for comment_text in comments_list:
            if comment_text is None:
                continue
            comment_text = _convert_value_to_string(
                comment_text, encoding=encoding, bytes_errors=bytes_errors
            )
            if not comment_text:
                continue
            if pretty:
                content_handler.ignorableWhitespace(depth * indent)
            content_handler.comment(comment_text)
            if pretty:
                content_handler.ignorableWhitespace(newl)
        return

    key = _process_namespace(key, namespaces, namespace_separator, attr_prefix)
    if preprocessor is not None:
        result = preprocessor(key, value)
        if result is None:
            return
        key, value = result
    # Minimal validation to avoid breaking out of tag context
    _validate_name(key, "element")
    if not hasattr(value, '__iter__') or isinstance(value, (str, bytes, bytearray, memoryview, dict)):
        value = [value]
    for index, v in enumerate(value):
        if full_document and depth == 0 and index > 0:
            raise ValueError('document with multiple roots')
        if v is None:
            v = {}
        elif not isinstance(v, (dict, str)):
            if expand_iter and hasattr(v, '__iter__') and not isinstance(v, (bytes, bytearray, memoryview)):
                v = {expand_iter: v}
            else:
                v = _convert_value_to_string(v, encoding=encoding, bytes_errors=bytes_errors)
        if isinstance(v, str):
            v = {cdata_key: v}
        cdata = None
        attrs = {}
        children = []
        for ik, iv in v.items():
            if ik == cdata_key:
                if iv is None:
                    cdata = None
                else:
                    cdata = _convert_value_to_string(iv, encoding=encoding, bytes_errors=bytes_errors)
                continue
            if isinstance(ik, str) and ik.startswith(attr_prefix):
                ik = _process_namespace(ik, namespaces, namespace_separator,
                                        attr_prefix)
                if ik == '@xmlns' and isinstance(iv, dict):
                    for k, v in iv.items():
                        _validate_name(k, "attribute")
                        attr = 'xmlns{}'.format(f':{k}' if k else '')
                        attrs[attr] = '' if v is None else _convert_value_to_string(
                            v, encoding=encoding, bytes_errors=bytes_errors
                        )
                    continue
                if iv is None:
                    iv = ''
                elif not isinstance(iv, str):
                    iv = _convert_value_to_string(iv, encoding=encoding, bytes_errors=bytes_errors)
                attr_name = ik[len(attr_prefix) :]
                _validate_name(attr_name, "attribute")
                attrs[attr_name] = iv
                continue
            if isinstance(iv, list) and not iv:
                continue # Skip empty lists to avoid creating empty child elements
            children.append((ik, iv))
        if isinstance(indent, int):
            indent = ' ' * indent
        if pretty:
            content_handler.ignorableWhitespace(depth * indent)
        content_handler.startElement(key, AttributesImpl(attrs))
        if pretty and children:
            content_handler.ignorableWhitespace(newl)
        for child_key, child_value in children:
            _emit(child_key, child_value, content_handler,
                  attr_prefix, cdata_key, depth+1, preprocessor,
                  pretty, newl, indent, namespaces=namespaces,
                  namespace_separator=namespace_separator,
                  expand_iter=expand_iter, encoding=encoding,
                  bytes_errors=bytes_errors, comment_key=comment_key)
        if cdata is not None:
            content_handler.characters(cdata)
        if pretty and children:
            content_handler.ignorableWhitespace(depth * indent)
        content_handler.endElement(key)
        if pretty and depth:
            content_handler.ignorableWhitespace(newl)


class _XMLGenerator(XMLGenerator):
    def comment(self, text):
        text = _validate_comment(text)
        self._write(f"<!--{escape(text)}-->")


def unparse(input_dict, output=None, encoding='utf-8', full_document=True,
            short_empty_elements=False, comment_key='#comment',
            **kwargs):
    """Emit an XML document for the given `input_dict` (reverse of `parse`).

    The resulting XML document is returned as a string, but if `output` (a
    file-like object) is specified, it is written there instead.

    Dictionary keys prefixed with `attr_prefix` (default=`'@'`) are interpreted
    as XML node attributes, whereas keys equal to `cdata_key`
    (default=`'#text'`) are treated as character data.

    Empty lists are omitted entirely: ``{"a": []}`` produces no ``<a>`` element.
    Provide a placeholder entry (for example ``{"a": [""]}``) when an explicit
    empty container element must be emitted.

    The `pretty` parameter (default=`False`) enables pretty-printing. In this
    mode, lines are terminated with `'\n'` and indented with `'\t'`, but this
    can be customized with the `newl` and `indent` parameters.
    The `bytes_errors` parameter controls decoding errors for byte values and
    defaults to `'replace'`.

    """
    bytes_errors = kwargs.pop('bytes_errors', 'replace')
    try:
        codecs.lookup_error(bytes_errors)
    except LookupError as exc:
        raise ValueError(f"Invalid bytes_errors handler: {bytes_errors}") from exc

    must_return = False
    if output is None:
        output = StringIO()
        must_return = True
    if short_empty_elements:
        content_handler = _XMLGenerator(output, encoding, True)
    else:
        content_handler = _XMLGenerator(output, encoding)
    if full_document:
        content_handler.startDocument()
    seen_root = False
    for key, value in input_dict.items():
        if key != comment_key and full_document and seen_root:
            raise ValueError("Document must have exactly one root.")
        _emit(
            key,
            value,
            content_handler,
            full_document=full_document,
            encoding=encoding,
            bytes_errors=bytes_errors,
            comment_key=comment_key,
            **kwargs,
        )
        if key != comment_key:
            seen_root = True
    if full_document and not seen_root:
        raise ValueError("Document must have exactly one root.")
    if full_document:
        content_handler.endDocument()
    if must_return:
        value = output.getvalue()
        try:  # pragma no cover
            value = value.decode(encoding)
        except AttributeError:  # pragma no cover
            pass
        return value


