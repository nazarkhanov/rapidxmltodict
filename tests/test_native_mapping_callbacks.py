"""Observable Python-object semantics of the direct native event mapper.

The reference remains xmltodict 1.0.4. These deliberately small documents test
callback and custom-object protocols, rather than duplicating the XML corpus.
Both the private event entry point and public dispatch must preserve them.
"""

from collections.abc import MutableMapping
import gc
from inspect import isgenerator
import sys
import weakref

import pytest
import xmltodict

import rapidxmltodict
from rapidxmltodict import _native


def _native_parse(document, **options):
    parser = _native.NativeMappingParser(
        interrupted=rapidxmltodict.ParsingInterrupted, **options
    )
    if isgenerator(document):
        for chunk in document:
            parser.feed(chunk)
        parser.feed(b'', final=True)
    else:
        parser.feed(document, final=True)
    return parser.result


@pytest.fixture(params=['direct', 'public'])
def parse_function(request):
    return _native_parse if request.param == 'direct' else rapidxmltodict.parse


def _snapshot(value):
    """Record values without introducing custom mapping/list method calls."""
    if isinstance(value, dict):
        return (type(value).__name__, tuple(
            (_snapshot(key), _snapshot(item))
            for key, item in dict.items(value)
        ))
    if isinstance(value, MutableMapping):
        return (type(value).__name__, _snapshot(value.storage))
    if isinstance(value, list):
        return (type(value).__name__, tuple(
            _snapshot(list.__getitem__(value, i)) for i in range(list.__len__(value))
        ))
    if isinstance(value, tuple):
        return tuple(_snapshot(item) for item in value)
    return value


def _outcome(parse, document, options):
    try:
        return 'result', _snapshot(parse(document, **options))
    except Exception as error:
        if isinstance(error, (xmltodict.ParsingInterrupted,
                              rapidxmltodict.ParsingInterrupted)):
            return 'error', 'ParsingInterrupted', error.args
        return 'error', type(error).__name__, error.args


def _traced_constructor(events, proxy):
    counter = 0

    class TracedDict(dict):
        def __init__(self, *args):
            nonlocal counter
            self.number = counter
            counter += 1
            entries = list(args[0]) if args else []
            events.append(('construct', self.number,
                           type(args[0]).__name__ if args else None,
                           _snapshot(entries)))
            dict.__init__(self, entries)

        def __bool__(self):
            events.append(('truth', self.number))
            return bool(dict.__len__(self))

        def items(self):
            events.append(('items', self.number))
            return dict.items(self)

        def __getitem__(self, key):
            events.append(('get', self.number, key))
            return dict.__getitem__(self, key)

        def __setitem__(self, key, value):
            events.append(('set', self.number, key, _snapshot(value)))
            dict.__setitem__(self, key, value)

    class TracedProxy(MutableMapping):
        def __init__(self, *args):
            nonlocal counter
            self.number = counter
            counter += 1
            entries = list(args[0]) if args else []
            events.append(('construct', self.number,
                           type(args[0]).__name__ if args else None,
                           _snapshot(entries)))
            self.storage = dict(entries)

        def __bool__(self):
            events.append(('truth', self.number))
            return bool(self.storage)

        def __len__(self):
            events.append(('len', self.number))
            return len(self.storage)

        def __iter__(self):
            events.append(('iter', self.number))
            return iter(self.storage)

        def items(self):
            events.append(('items', self.number))
            return self.storage.items()

        def __getitem__(self, key):
            events.append(('get', self.number, key))
            return self.storage[key]

        def __setitem__(self, key, value):
            events.append(('set', self.number, key, _snapshot(value)))
            self.storage[key] = value

        def __delitem__(self, key):
            del self.storage[key]

    return TracedProxy if proxy else TracedDict


@pytest.mark.parametrize('proxy', [False, True], ids=['dict-subclass', 'mapping-proxy'])
@pytest.mark.parametrize('xml_attribs', [False, True])
def test_custom_mapping_constructor_and_access_trace(parse_function, proxy, xml_attribs):
    document = ('<!-- outer --><r xmlns="urn:r" xmlns:p="urn:p" a="first">'
                '<p:x p:a="value"> one </p:x><p:x/>'
                '<empty xmlns=""/><!-- inner --> tail </r>')

    def run(parse):
        events = []
        options = dict(dict_constructor=_traced_constructor(events, proxy),
                       process_namespaces=True, process_comments=True,
                       namespaces={'urn:r': None, 'urn:p': 'p'},
                       xml_attribs=xml_attribs, force_list=('empty',))
        outcome = _outcome(parse, document, options)
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def test_custom_namespace_lookup_order_and_false_aliases(parse_function):
    document = ('<a:r xmlns:a="urn:one" xmlns:b="urn:two" a:x="1" b:x="2">'
                '<a:x/><b:x/><a:x xmlns:a="urn:three"/></a:r>')

    def run(parse):
        events = []

        class Alias:
            def __bool__(self):
                events.append(('alias-truth',))
                return False

        class Namespaces:
            def __getitem__(self, key):
                events.append(('namespace', key))
                if key == 'urn:one':
                    return Alias()
                if key == 'urn:two':
                    return None
                raise KeyError(key)

        def postprocess(path, key, value):
            events.append(('postprocess', _snapshot(path), key, _snapshot(value)))
            return key, value

        result = _outcome(parse, document, dict(
            process_namespaces=True, namespaces=Namespaces(),
            postprocessor=postprocess, attr_prefix=''))
        return result, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def test_postprocessor_path_is_live_and_force_paths_are_shallow_copies(parse_function):
    document = '<r a="one"><x b="two">text</x><x>again</x></r>'

    def run(parse):
        events = []
        post_paths = []
        force_paths = []

        def postprocess(path, key, value):
            if post_paths:
                assert path is post_paths[0]
            post_paths.append(path)
            events.append(('postprocess', _snapshot(path), key, _snapshot(value)))
            if key == '@a':
                name, attrs = path[0]
                attrs['a'] = 'visible'
                path[0] = ('renamed-' + name, attrs)
            return key, value

        def force(path, key, value):
            assert all(path is not prior for prior in post_paths + force_paths)
            force_paths.append(path)
            events.append(('force', _snapshot(path), key, _snapshot(value)))
            if path:
                path[0][1]['from_force'] = 'shared'
                path.append(('only-the-copy', None))
            return key == 'x'

        result = _outcome(parse, document, dict(
            postprocessor=postprocess, force_list=force, force_cdata=force))
        events.append(('retained-post-paths', _snapshot(post_paths)))
        events.append(('retained-force-paths', _snapshot(force_paths)))
        return result, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def test_false_postprocessor_is_skipped_for_attributes_but_used_for_nodes(parse_function):
    def run(parse):
        events = []

        class Processor:
            def __bool__(self):
                events.append(('processor-truth',))
                return False

            def __call__(self, path, key, value):
                events.append(('postprocess', _snapshot(path), key, _snapshot(value)))
                return key.upper(), value

        outcome = _outcome(parse, '<r a="v"><x/></r>', dict(postprocessor=Processor()))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


@pytest.mark.parametrize('dropped', [None, False, (), []],
                         ids=['none', 'false', 'empty-tuple', 'empty-list'])
@pytest.mark.parametrize('target', ['@a', 'x'])
def test_postprocessor_false_result_has_context_specific_meaning(parse_function, dropped, target):
    def run(parse):
        calls = []

        def postprocess(path, key, value):
            calls.append((key, _snapshot(value)))
            return dropped if key == target else iter((key, value))

        outcome = _outcome(parse, '<r a="v"><x/><y/></r>', dict(postprocessor=postprocess))
        return outcome, calls

    assert run(parse_function) == run(xmltodict.parse)


@pytest.mark.parametrize('option', ['force_list', 'force_cdata'])
@pytest.mark.parametrize('membership', ['true', 'false', 'false-option', 'type-error', 'value-error'])
def test_force_option_membership_precedes_callable_fallback(parse_function, option, membership):
    document = '<r a="v">head<x>one</x><x>two</x><y/>tail</r>'

    def run(parse):
        events = []

        class Decision:
            def __bool__(self):
                events.append(('decision-truth',))
                return True

        class Force:
            def __bool__(self):
                events.append(('option-truth',))
                return membership != 'false-option'

            def __contains__(self, key):
                events.append(('contains', key))
                if membership == 'type-error':
                    raise TypeError('membership requests callable fallback')
                if membership == 'value-error':
                    raise ValueError('membership must propagate this error')
                return membership == 'true'

            def __call__(self, path, key, value):
                events.append(('force-call', _snapshot(path), key, _snapshot(value)))
                return Decision()

        outcome = _outcome(parse, document, {option: Force()})
        return outcome, events

    assert run(parse_function) == run(xmltodict.parse)



@pytest.mark.parametrize('option', ['xml_attribs', 'strip_whitespace'])
def test_nonboolean_mapping_flags_are_evaluated_at_each_use(parse_function, option):
    def run(parse):
        events = []

        class Flag:
            calls = 0

            def __bool__(self):
                self.calls += 1
                events.append(('truth', self.calls))
                return self.calls % 2 == 1

        def postprocess(path, key, value):
            events.append(('postprocess', key, _snapshot(value)))
            return key, value

        outcome = _outcome(parse, '<r a="v"> head <x a="x"> one </x><y a="y"> two </y></r>',
                           {option: Flag(), 'postprocessor': postprocess})
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def test_item_depth_uses_comparisons_without_integer_coercion(parse_function):
    def run(parse):
        events = []

        class Depth:
            def __le__(self, length):
                events.append(('depth-at-start', length))
                return 2 <= length

            def __eq__(self, length):
                events.append(('depth-at-end', length))
                return length == 2

        def callback(path, item):
            events.append(('callback', _snapshot(path), _snapshot(item)))
            return True

        outcome = _outcome(parse, '<r><i a="v"><x>one</x></i><i>two</i></r>',
                           dict(item_depth=Depth(), item_callback=callback))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def test_cdata_separator_join_protocol_receives_original_text_fragments(parse_function):
    def run(parse):
        events = []

        class Separator:
            def join(self, fragments):
                events.append(('join', _snapshot(fragments)))
                return '|'.join(fragments)

        def chunks():
            yield '<r>a'
            yield 'b<x> c </x>d'
            yield 'e</r>'

        outcome = _outcome(parse, chunks(), dict(cdata_separator=Separator()))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected



def test_namespace_separator_subclass_join_is_called_for_each_alias(parse_function):
    document = '<p:r xmlns:p="urn:p" p:a="v"><p:x>one</p:x><p:x/></p:r>'

    def run(parse):
        events = []

        class Name(str):
            pass

        class Separator(str):
            def join(self, names):
                events.append(('join', _snapshot(names)))
                return Name('::'.join(names))

        def postprocess(path, key, value):
            events.append(('postprocess', type(key).__name__, key, _snapshot(path)))
            return key, value

        outcome = _outcome(parse, document, dict(
            process_namespaces=True, namespace_separator=Separator(':'),
            namespaces={'urn:p': 'P'}, postprocessor=postprocess))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def test_cdata_join_result_uses_custom_truth_and_strip_methods(parse_function):
    def run(parse):
        events = []

        class Text(str):
            def __bool__(self):
                events.append(('text-truth', str(self)))
                return bool(str.__len__(self))

            def strip(self):
                events.append(('text-strip', str(self)))
                return Text(str.strip(self))

        class Separator:
            def join(self, fragments):
                events.append(('join', _snapshot(fragments)))
                return Text(''.join(fragments))

        outcome = _outcome(parse, '<r a="v"> head <x> one </x><x> </x> tail </r>',
                           dict(cdata_separator=Separator(), force_cdata=True))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected

def test_dtd_default_namespace_attributes_keep_constructor_order(parse_function):
    document = ('<!DOCTYPE p:r ['
                '<!ATTLIST p:r xmlns:p CDATA "urn:p" p:a CDATA "default">'
                '<!ATTLIST p:x a CDATA "child">]>'
                '<p:r explicit="first"><p:x/></p:r>')

    def run(parse):
        events = []
        outcome = _outcome(parse, document, dict(
            process_namespaces=True, dict_constructor=_traced_constructor(events, False)))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected

def test_repeated_values_call_overridden_list_append(parse_function):
    def run(parse):
        events = []

        class Values(list):
            def append(self, value):
                events.append(('append', _snapshot(self), value))
                list.append(self, 'appended:' + value)

        def postprocess(path, key, value):
            if key == 'x' and value == 'first':
                return key, Values([value])
            return key, value

        outcome = _outcome(parse, '<r><x>first</x><x>second</x><x>third</x></r>',
                           dict(postprocessor=postprocess))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[1]
    assert run(parse_function) == expected



def test_list_subclass_append_receives_tuple_value_as_one_argument(parse_function):
    def run(parse):
        events = []

        class Values(list):
            def append(self, value):
                events.append(('append', _snapshot(value)))
                list.append(self, value)

        def postprocess(path, key, value):
            if key == 'x':
                value = Values([value]) if value == 'first' else ('pair', value)
            return key, value

        outcome = _outcome(parse, '<r><x>first</x><x>second</x></r>',
                           dict(postprocessor=postprocess))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


def _exception_chain(error):
    chain = []
    while error is not None:
        chain.append((type(error).__name__, error.args))
        error = error.__context__
    return chain


@pytest.mark.parametrize('option', ['force_list', 'force_cdata'])
@pytest.mark.parametrize('raise_from_callback', [False, True])
def test_force_callbacks_preserve_handled_exception_state_and_context(
        parse_function, option, raise_from_callback):
    def run(parse):
        events = []

        def record(label):
            events.append((label, _exception_chain(sys.exc_info()[1])))

        class Force:
            def __bool__(self):
                record('truth')
                return True

            def __contains__(self, key):
                record('contains')
                raise TypeError('membership requested callback fallback')

            def __call__(self, path, key, value):
                record('callback')
                if raise_from_callback:
                    raise RuntimeError('callback failed during handled exception')
                return True

        try:
            raise ArithmeticError('outer handled exception')
        except ArithmeticError:
            try:
                outcome = ('result', _snapshot(parse('<r><x>one</x></r>', **{option: Force()})))
            except RuntimeError as error:
                assert raise_from_callback
                outcome = ('error', _exception_chain(error))
            record('after-parse')
        assert sys.exc_info()[0] is None
        return outcome, events

    assert run(parse_function) == run(xmltodict.parse)

def test_keyerror_from_repeated_assignment_retries_missing_key_branch(parse_function):
    def run(parse):
        events = []

        class RetryDict(dict):
            def __setitem__(self, key, value):
                events.append(('set', key, _snapshot(value)))
                if key == 'x' and dict.__contains__(self, key) and not hasattr(self, 'retried'):
                    self.retried = True
                    raise KeyError('assignment, rather than lookup, failed')
                dict.__setitem__(self, key, value)

        def force(path, key, value):
            events.append(('force', key, _snapshot(value)))
            return False

        outcome = _outcome(parse, '<r><x>one</x><x>two</x></r>',
                           dict(dict_constructor=RetryDict, force_list=force))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0] == ('result', ('RetryDict', (('r', ('RetryDict', (('x', 'two'),))),)))
    assert run(parse_function) == expected


@pytest.mark.parametrize('stop', [False, True])
def test_streaming_callback_truth_and_generator_timing_trace(parse_function, stop):
    def run(parse):
        events = []
        paths = []

        class Continue:
            def __bool__(self):
                events.append(('callback-result-truth',))
                return not stop

        def chunks():
            events.append(('input', 0))
            yield '<r a="root"><i> untrimmed </i>'
            events.append(('input', 1))
            yield '<i a="child"> discarded text <x> kept </x> tail </i>'
            events.append(('input', 2))
            yield '</r>'

        def callback(path, item):
            paths.append(path)
            events.append(('callback', _snapshot(path), _snapshot(item)))
            return Continue()

        def postprocess(path, key, value):
            events.append(('postprocess', _snapshot(path), key, _snapshot(value)))
            return key, value

        outcome = _outcome(parse, chunks(), dict(
            item_depth=2, item_callback=callback, postprocessor=postprocess,
            force_cdata=True, force_list=True, cdata_separator='|'))
        events.append(('retained-paths', _snapshot(paths)))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == ('error' if stop else 'result')
    assert run(parse_function) == expected


@pytest.mark.parametrize('stage', ['postprocess', 'force-list', 'force-cdata', 'item-callback'])
def test_callback_failure_keeps_exception_identity_and_stops_input(parse_function, stage):
    def run(parse):
        events = []
        marker = LookupError('the callback exception')

        def fail(*args):
            events.append(('callback',))
            raise marker

        def chunks():
            events.append(('input', 0))
            yield '<r><x>one</x>'
            events.append(('input', 1))
            yield '<x>two</x></r>'

        options = {
            'postprocess': {'postprocessor': fail},
            'force-list': {'force_list': fail},
            'force-cdata': {'force_cdata': fail},
            'item-callback': {'item_depth': 2, 'item_callback': fail},
        }[stage]
        with pytest.raises(LookupError) as caught:
            parse(chunks(), **options)
        assert caught.value is marker
        return events

    assert run(parse_function) == run(xmltodict.parse) == [('input', 0), ('callback',)]


@pytest.mark.parametrize('mode', ['result', 'callback-error', 'syntax-error', 'cycle'])
def test_native_mapping_releases_custom_values_and_callback_cycles(mode):
    references = []

    class TrackedDict(dict):
        def __init__(self, *args):
            super().__init__(*args)
            references.append(weakref.ref(self))

    class Processor:
        parser = None

        def __call__(self, path, key, value):
            if mode == 'callback-error':
                raise LookupError('release partial mapping')
            return key, value

    def exercise():
        processor = Processor()
        references.append(weakref.ref(processor))
        parser = _native.NativeMappingParser(
            dict_constructor=TrackedDict, postprocessor=processor,
            interrupted=rapidxmltodict.ParsingInterrupted)
        if mode == 'cycle':
            processor.parser = parser
        document = '<r a="v"><x>one</x>' if mode == 'syntax-error' else '<r a="v"><x>one</x></r>'
        try:
            parser.feed(document, final=True)
        except (LookupError, rapidxmltodict.ParseError):
            assert mode in ('callback-error', 'syntax-error')
        else:
            assert mode in ('result', 'cycle')
            assert parser.result['r']['x'] == 'one'

    exercise()
    gc.collect()
    assert references and all(reference() is None for reference in references)


@pytest.mark.parametrize('case', [
    'success', 'streaming-success', 'syntax-error', 'namespace-error',
    'interrupted', 'callback-error', 'encoding-error', 'encoding-type-error',
    'reader-error', 'generator-error',
])
@pytest.mark.parametrize('entrypoint', ['private', 'public'])
def test_native_wrapper_closes_parser_even_with_retained_traceback(monkeypatch, case, entrypoint):
    from rapidxmltodict import _parse as implementation

    parse = (implementation._parse_native_events if entrypoint == 'private'
             else implementation.parse)
    parser_type = _native.NativeMappingParser
    parsers = []
    hooks = []
    mappings = []

    class Hook:
        parser = None

        def __call__(self, path, key, value):
            return False

    class TrackedDict(dict):
        def __init__(self, *args):
            super().__init__(*args)
            mappings.append(weakref.ref(self))

    def create_parser(**options):
        hook = Hook()
        hooks.append(weakref.ref(hook))
        parser = parser_type(force_list=hook, dict_constructor=TrackedDict, **options)
        hook.parser = parser
        parsers.append(parser)
        return parser

    monkeypatch.setattr(_native, 'NativeMappingParser', create_parser)

    def callback_error(path, item):
        raise RuntimeError('callback failed')

    class Reader:
        def read(self, size):
            raise OSError('reader failed')

    def chunks():
        yield '<r><i>one</i>'
        raise OSError('generator failed')

    document = '<r><i>one</i></r>'
    options = {'process_comments': True}
    error_type = None
    if case == 'streaming-success':
        options.update(item_depth=2)
    elif case == 'syntax-error':
        document = '<r><i>one</wrong>'
        error_type = rapidxmltodict.ParseError
    elif case == 'namespace-error':
        document = '<r><p:i/></r>'
        options['process_namespaces'] = True
        error_type = rapidxmltodict.ParseError
    elif case == 'interrupted':
        options.update(item_depth=2, item_callback=lambda path, item: False)
        error_type = rapidxmltodict.ParsingInterrupted
    elif case == 'callback-error':
        options.update(item_depth=2, item_callback=callback_error)
        error_type = RuntimeError
    elif case == 'encoding-error':
        document = '<r>é</r>'
        options['encoding'] = 'ascii'
        error_type = UnicodeEncodeError
    elif case == 'encoding-type-error':
        document = b'<r/>'
        options['encoding'] = 42
        error_type = TypeError
    elif case == 'reader-error':
        document = Reader()
        error_type = OSError
    elif case == 'generator-error':
        document = chunks()
        error_type = OSError

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        if error_type is not None:
            with pytest.raises(error_type) as captured:
                parse(document, **options)
            assert captured.value.__traceback__ is not None
        else:
            result = parse(document, **options)
            assert result == ({'r': {'i': 'one'}} if case == 'success' else None)
        assert len(parsers) == len(hooks) == 1
        assert parsers[0].result is None
        assert hooks[0]() is None
        with pytest.raises(RuntimeError):
            parsers[0].feed('<another/>', final=True)
        # Exception callback frames legitimately retain their path/item inputs;
        # pure XML/input errors must leave no native-owned partial dictionaries.
        if case in ('syntax-error', 'namespace-error', 'reader-error', 'generator-error'):
            assert all(reference() is None for reference in mappings)
    finally:
        if was_enabled:
            gc.enable()


@pytest.mark.parametrize('finalized', [False, True])
def test_native_close_releases_state_and_is_idempotent(finalized):
    references = []

    class Mapping(dict):
        def __init__(self, *args):
            super().__init__(*args)
            references.append(weakref.ref(self))

    parser = _native.NativeMappingParser(dict_constructor=Mapping)
    parser.feed('<r a="v"><x>one</x>' + ('</r>' if finalized else ''), final=finalized)
    assert references and any(reference() is not None for reference in references)
    parser.close()
    assert parser.result is None
    assert all(reference() is None for reference in references)
    parser.close()
    with pytest.raises(RuntimeError):
        parser.feed('', final=True)
    with pytest.raises(RuntimeError):
        parser.set_source_encoding('utf8')


def test_native_close_rejects_reentrant_callback_and_parser_remains_usable():
    attempts = []
    parser = None

    def postprocess(path, key, value):
        with pytest.raises(RuntimeError) as caught:
            parser.close()
        attempts.append(str(caught.value))
        return key, value

    parser = _native.NativeMappingParser(postprocessor=postprocess)
    parser.feed('<r><x>one</x></r>', final=True)
    assert parser.result == {'r': {'x': 'one'}}
    assert len(attempts) == 2
    parser.close()


@pytest.mark.parametrize('option', ['force_list', 'force_cdata'])
def test_force_option_honors_python_isinstance_bool_protocol(parse_function, option):
    def run(parse):
        events = []

        class Force:
            @property
            def __class__(self):
                events.append(('class',))
                return bool

            def __bool__(self):
                events.append(('truth',))
                return True

        outcome = _outcome(parse, '<r><x>one</x></r>', {option: Force()})
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    assert run(parse_function) == expected


@pytest.mark.parametrize('fail_at', [1, 3], ids=['initialization', 'event-construction'])
def test_constructor_failure_releases_options_and_partial_mappings(fail_at):
    references = []

    class Mapping(dict):
        def __init__(self, *args):
            super().__init__(*args)
            references.append(weakref.ref(self))

    class Constructor:
        calls = 0

        def __call__(self, *args):
            self.calls += 1
            if self.calls == fail_at:
                raise RuntimeError('constructor failed')
            return Mapping(*args)

    def exercise():
        constructor = Constructor()
        references.append(weakref.ref(constructor))
        parser = _native.NativeMappingParser.__new__(_native.NativeMappingParser)
        try:
            parser.__init__(dict_constructor=constructor)
            parser.feed('<r a="value"><x>text</x></r>', final=True)
        except RuntimeError as error:
            assert str(error) == 'constructor failed'
        else:
            pytest.fail('constructor did not run at the expected boundary')
        parser.close()
        assert parser.result is None
        return parser

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        parser = exercise()
        assert all(reference() is None for reference in references)
        with pytest.raises(RuntimeError):
            parser.feed('<r/>', final=True)
    finally:
        if was_enabled:
            gc.enable()


def test_reinitialization_from_constructor_is_rejected_without_corrupting_parser():
    parser = _native.NativeMappingParser()
    attempts = []

    def constructor(*args):
        with pytest.raises(RuntimeError):
            parser.__init__()
        attempts.append('reinitialization rejected')
        return dict(*args)

    parser.__init__(dict_constructor=constructor)
    parser.feed('<r a="v"><x>one</x></r>', final=True)
    assert attempts
    assert parser.result == {'r': {'@a': 'v', 'x': 'one'}}
    parser.close()


def test_unicode_chunk_failure_preserves_completed_item_callbacks(parse_function):
    def run(parse):
        events = []

        def chunks():
            events.append(('input', 0))
            yield '<r><i>one</i>'
            events.append(('input', 1))
            yield '\ud800'
            events.append(('input', 2))
            yield '</r>'

        def callback(path, item):
            events.append(('callback', _snapshot(path), item))
            return True

        outcome = _outcome(parse, chunks(), dict(
            item_depth=2, item_callback=callback, force_cdata=True))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[0][:2] == ('error', 'UnicodeEncodeError')
    assert expected[1][-1] == ('input', 1)
    assert run(parse_function) == expected


@pytest.mark.parametrize('option', ['process_namespaces', 'process_comments', 'disable_entities'])
def test_top_level_flag_truth_calls_match_reference_initialization_order(option):
    from rapidxmltodict._parse import _parse_native_events

    document = '<!-- note --><p:r xmlns:p="urn:p" a="v"><p:x/></p:r>'

    def run(parse):
        events = []

        class Flag:
            def __bool__(self):
                events.append(('top-level-truth', option))
                return True

        class Processor:
            def __bool__(self):
                events.append(('processor-truth',))
                return False

            def __call__(self, path, key, value):
                events.append(('postprocess', key))
                return key, value

        def constructor(*args):
            events.append(('construct', type(args[0]).__name__ if args else None))
            return dict(*args)

        options = dict(process_namespaces=True, process_comments=True,
                       disable_entities=True, dict_constructor=constructor,
                       postprocessor=Processor())
        options[option] = Flag()
        return _outcome(parse, document, options), events

    expected = run(xmltodict.parse)
    assert expected[0][0] == 'result'
    # Public dispatch must not evaluate custom flag objects while merely
    # checking eligibility for an exact-builtin fast path.
    assert run(_native_parse) == expected
    assert run(_parse_native_events) == expected
    assert run(rapidxmltodict.parse) == expected


def test_custom_existing_key_collision_observes_missing_key_exception_context(parse_function):
    def run(parse):
        events = []

        class Key:
            def __hash__(self):
                return hash('second')

            def __eq__(self, other):
                error_type = sys.exc_info()[0]
                events.append((other, error_type.__name__ if error_type else None))
                return False

        custom_key = Key()

        def postprocess(path, key, value):
            return (custom_key if key == 'first' else key), value

        result = parse('<r><first>a</first><second>b</second></r>',
                       postprocessor=postprocess)
        # Normalize the deliberately unequal custom keys without calling their
        # equality methods again while comparing the returned dictionaries.
        values = [('first-key' if key is custom_key else key, value)
                  for key, value in result['r'].items()]
        return values, events

    expected = run(xmltodict.parse)
    assert ('second', 'KeyError') in expected[1]
    assert run(parse_function) == expected


def test_tuple_postprocessor_key_preserves_nested_keyerror_arguments(parse_function):
    def run(parse):
        events = []

        def postprocess(path, key, value):
            return ('tuple', 'key'), value

        def force(path, key, value):
            events.append(_exception_chain(sys.exc_info()[1]))
            return False

        outcome = _outcome(parse, '<r/>', dict(postprocessor=postprocess, force_list=force))
        return outcome, events

    expected = run(xmltodict.parse)
    assert expected[1][0][-1] == ('KeyError', (('tuple', 'key'),))
    assert run(parse_function) == expected
