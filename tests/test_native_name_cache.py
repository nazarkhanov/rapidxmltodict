"""Parser-local XML vocabulary caching and its object lifetime."""
import gc
import io
import sys

import rapidxmltodict
from rapidxmltodict import _native


class RecordingSink:
    def __init__(self):
        self.starts = []
        self.ends = []
        self.attributes = []

    def start(self, name, attrs):
        self.starts.append(name)
        self.attributes.extend(key for key, value in attrs)

    def end(self, name):
        self.ends.append(name)

    def text(self, value):
        pass

    def comment(self, value):
        pass


def test_native_names_reused_across_start_end_and_attributes():
    sink = RecordingSink()
    parser = _native.NativeParser(sink)
    parser.feed('<container><repeated_name repeated_attribute="one"/>')
    parser.feed('<repeated_name repeated_attribute="two"/></container>', True)
    assert sink.starts[1] is sink.starts[2]
    assert sink.ends[0] is sink.starts[1]
    assert sink.ends[1] is sink.starts[1]
    assert sink.attributes[0] is sink.attributes[1]


def test_vocabulary_cache_belongs_to_each_parser():
    one, two = RecordingSink(), RecordingSink()
    first, second = _native.NativeParser(one), _native.NativeParser(two)
    first.feed('<a_deliberately_long_uncached_xml_name/>', True)
    second.feed('<a_deliberately_long_uncached_xml_name/>', True)
    assert one.starts[0] == two.starts[0]
    assert one.starts[0] is not two.starts[0]
    retained = one.starts[0]
    before = sys.getrefcount(retained)
    del first
    gc.collect()
    assert sys.getrefcount(retained) < before
    assert retained == 'a_deliberately_long_uncached_xml_name'


def test_file_results_share_repeated_element_name_objects():
    document = ('<container>' + '<record><repeated_key>value</repeated_key></record>' * 100
                + '</container>').encode()
    records = rapidxmltodict.parse(io.BytesIO(document))['container']['record']
    keys = [next(iter(record)) for record in records]
    assert len({id(key) for key in keys}) == 1
    gc.collect()
    assert records == [{'repeated_key': 'value'}] * 100


def test_event_dispatch_observes_method_replacement():
    class ReplacingSink(RecordingSink):
        def start(self, name, attrs):
            self.starts.append(('original', name))
            self.start = lambda next_name, next_attrs: self.starts.append(('replacement', next_name))
    sink = ReplacingSink()
    parser = _native.NativeParser(sink)
    parser.feed('<root><child/></root>', True)
    assert sink.starts == [('original', 'root'), ('replacement', 'child')]


def test_event_dispatch_preserves_custom_attribute_lookup():
    class DynamicSink(RecordingSink):
        def __init__(self):
            super().__init__()
            self.lookups = []

        def __getattribute__(self, name):
            if name in ('start', 'end', 'text', 'comment'):
                object.__getattribute__(self, 'lookups').append(name)
            return object.__getattribute__(self, name)
    sink = DynamicSink()
    parser = _native.NativeParser(sink, process_comments=True)
    parser.feed('<root>text<!--comment--><child/></root>', True)
    assert sink.lookups == ['start', 'text', 'comment', 'start', 'end', 'end']
