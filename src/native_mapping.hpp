// Direct CPython-object construction from RapidXML's incremental event stream.
// No DOM, Python SAX handler, or per-tag Python method dispatch is involved.
// Mapping semantics follow xmltodict 1.0.4; user-supplied hooks remain Python
// calls, and every owned Python reference participates in cyclic GC.
// Included by native.cpp after native_events_binding.hpp.
// Copyright (C) 2012 Martin Blech and individual contributors.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
// of the Software, and to permit persons to whom the Software is furnished to
// do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.


PyObject* mapping_owned(PyObject* object) { Py_INCREF(object); return object; }
void mapping_replace(PyObject*& destination, PyObject* owned) {
    PyObject* previous = destination;
    destination = owned;
    Py_XDECREF(previous);
}
bool mapping_truth(PyObject* value) {
    const int result = PyObject_IsTrue(value);
    if (result < 0) throw PythonError{};
    return result != 0;
}
void mapping_checked(int result) { if (result < 0) throw PythonError{}; }

// Match Python's handled-exception scope when a user hook runs inside an
// except clause, including sys.exc_info() and newly raised __context__ links.
struct MappingHandledError {
    PyObject* previous_type = nullptr;
    PyObject* previous_value = nullptr;
    PyObject* previous_traceback = nullptr;
    MappingHandledError() {
        PyErr_GetExcInfo(&previous_type, &previous_value, &previous_traceback);
        PyObject* type = nullptr; PyObject* value = nullptr; PyObject* traceback = nullptr;
        PyErr_Fetch(&type, &value, &traceback);
        PyErr_NormalizeException(&type, &value, &traceback);
        if (value && traceback) PyException_SetTraceback(value, traceback);
        PyErr_SetExcInfo(type, value, traceback); // Steals all three references.
    }
    ~MappingHandledError() {
        PyErr_SetExcInfo(previous_type, previous_value, previous_traceback);
    }
    MappingHandledError(const MappingHandledError&) = delete;
    MappingHandledError& operator=(const MappingHandledError&) = delete;
};

struct NativeMappingSink : rapidxml_events::Sink {
    enum Option {
        Depth, Callback, XmlAttribs, AttrPrefix, CdataKey, ForceCdata,
        CdataSeparator, Postprocessor, Constructor, StripWhitespace,
        NamespaceSeparator, Namespaces, ForceList, CommentKey, Interrupted,
        OptionCount
    };
    std::array<PyObject*, OptionCount> options{};
    PyObject* path = nullptr;
    PyObject* item = nullptr;
    PyObject* data = nullptr;
    PyObject* namespace_declarations = nullptr;
    rapidxml_events::Parser* parser = nullptr; // Non-owning; PyMappingParser owns it.
    bool process_namespaces = false;
    bool process_comments = false;
    std::string separator;
    bool integer_depth = false;
    Py_ssize_t depth = 0;
    // The representation choice is immutable. Reading .result only revokes
    // trusted built-in writes, since callers can then inject custom objects.
    bool fast_mapping = false;
    bool builtin_objects_only = false;
    std::unordered_map<std::string, PyObject*> names, attribute_names;
    using Bindings = std::unordered_map<std::string, std::string>;
    std::shared_ptr<Bindings> bindings;
    std::vector<std::shared_ptr<Bindings>> scopes;
    static constexpr const char* xml_namespace = "http://www.w3.org/XML/1998/namespace";
    static constexpr const char* xmlns_namespace = "http://www.w3.org/2000/xmlns/";

    struct Frame {
        PyObject* item;
        PyObject* data;
        Frame(PyObject* value, PyObject* text)
            : item(mapping_owned(value)), data(mapping_owned(text)) {}
        Frame(const Frame&) = delete;
        Frame& operator=(const Frame&) = delete;
        Frame(Frame&& other) noexcept : item(other.item), data(other.data) {
            other.item = other.data = nullptr;
        }
        ~Frame() { Py_XDECREF(item); Py_XDECREF(data); }
    };
    std::vector<Frame> stack;

    ~NativeMappingSink() override {
        for (PyObject* option : options) Py_XDECREF(option);
        for (const auto& name : names) Py_DECREF(name.second);
        for (const auto& name : attribute_names) Py_DECREF(name.second);
        Py_XDECREF(path); Py_XDECREF(item); Py_XDECREF(data);
        Py_XDECREF(namespace_declarations);
    }
    int traverse(visitproc visit, void* arg) {
        for (PyObject* option : options) Py_VISIT(option);
        Py_VISIT(path); Py_VISIT(item); Py_VISIT(data); Py_VISIT(namespace_declarations);
        for (const auto& frame : stack) { Py_VISIT(frame.item); Py_VISIT(frame.data); }
        for (const auto& name : names) Py_VISIT(name.second);
        for (const auto& name : attribute_names) Py_VISIT(name.second);
        return 0;
    }
    void initialize(const std::array<PyObject*, OptionCount>& values,
                    PyObject* namespace_processing, PyObject* comment_processing) {
        for (size_t i = 0; i < values.size(); ++i)
            options[i] = values[i] ? mapping_owned(values[i]) : nullptr;
        path = checked(PyList_New(0));
        item = mapping_owned(Py_None);
        data = checked(PyList_New(0));
        // The constructor's first call precedes namespace option validation,
        // just as it does in the reference handler's initialization.
        namespace_declarations = new_mapping();
        if (PyLong_CheckExact(options[Depth])) {
            depth = PyLong_AsSsize_t(options[Depth]);
            if (depth == -1 && PyErr_Occurred()) PyErr_Clear();
            else integer_depth = true;
        }
        process_namespaces = mapping_truth(namespace_processing)
            && options[NamespaceSeparator] != Py_None;
        process_comments = mapping_truth(comment_processing);
        if (process_namespaces) {
            if (!PyUnicode_Check(options[NamespaceSeparator])) {
                PyErr_SetString(PyExc_TypeError, "namespace_separator must be str or None");
                throw PythonError{};
            }
            Py_ssize_t length;
            const char* value = PyUnicode_AsUTF8AndSize(options[NamespaceSeparator], &length);
            if (!value) throw PythonError{};
            if (length > 1) {
                PyErr_SetString(PyExc_ValueError, "namespace_separator must be at most one character, omitted, or None");
                throw PythonError{};
            }
            if (length && !value[0]) {
                PyErr_SetString(PyExc_ValueError, "embedded null character");
                throw PythonError{};
            }
            separator.assign(value, static_cast<size_t>(length));
            bindings = std::make_shared<Bindings>();
            bindings->emplace("xml", xml_namespace);
        }
        // Only immutable exact built-ins with the ordinary default mapping
        // qualify. Any observable mapping hook/custom option uses the complete
        // mapper below. Input decoding and XML/entity validation are identical.
        fast_mapping = namespace_processing == Py_False && comment_processing == Py_False &&
            integer_depth && depth == 0 && !options[Callback] &&
            options[Constructor] == reinterpret_cast<PyObject*>(&PyDict_Type) &&
            options[XmlAttribs] == Py_True && options[StripWhitespace] == Py_True &&
            options[Postprocessor] == Py_None && options[Namespaces] == Py_None &&
            (options[ForceList] == Py_None || options[ForceList] == Py_False) &&
            (options[ForceCdata] == Py_None || options[ForceCdata] == Py_False) &&
            default_string(options[AttrPrefix], "@") && default_string(options[CdataKey], "#text") &&
            default_string(options[CdataSeparator], "") && default_string(options[CommentKey], "#comment") &&
            default_string(options[NamespaceSeparator], ":");
        builtin_objects_only = fast_mapping;
        if (fast_mapping) mapping_replace(data, mapping_owned(Py_None));
    }
    static bool default_string(PyObject* value, const char* expected) {
        return PyUnicode_CheckExact(value) && PyUnicode_CompareWithASCIIString(value, expected) == 0;
    }
    bool at_depth(int comparison) {
        const Py_ssize_t length = PyList_GET_SIZE(path);
        if (integer_depth) return comparison == Py_EQ ? length == depth : length >= depth;
        Ref py_length(checked(PyLong_FromSsize_t(length)));
        const int result = PyObject_RichCompareBool(py_length.p, options[Depth], comparison);
        if (result < 0) throw PythonError{};
        return result != 0;
    }
    PyObject* new_mapping(PyObject* entries = nullptr) {
        if (options[Constructor] == reinterpret_cast<PyObject*>(&PyDict_Type)) {
            Ref result(checked(PyDict_New()));
            if (entries) mapping_checked(PyDict_MergeFromSeq2(result.p, entries, 1));
            return result.release();
        }
        return checked(entries ? PyObject_CallOneArg(options[Constructor], entries)
                               : PyObject_CallNoArgs(options[Constructor]));
    }
    PyObject* cached_name(const std::string& name) {
        const auto found = names.find(name);
        if (found != names.end()) return mapping_owned(found->second);
        Ref value(PythonEventSink::unicode(name));
        names.emplace(name, value.p);
        return mapping_owned(value.release());
    }
    PyObject* cached_attribute_name(const std::string& name) {
        const auto found = attribute_names.find(name);
        if (found != attribute_names.end()) return mapping_owned(found->second);
        Ref value(PythonEventSink::unicode("@" + name));
        attribute_names.emplace(name, value.p);
        return mapping_owned(value.release());
    }
    PyObject* build_name(PyObject* full_name) {
        if (options[Namespaces] == Py_None) return mapping_owned(full_name);
        // rfind and the one-character split intentionally retain xmltodict's
        // behavior even when namespaces is supplied without namespace parsing.
        Ref index(checked(PyObject_CallMethod(full_name, "rfind", "(O)", options[NamespaceSeparator])));
        Ref uri, local;
        if (PyUnicode_CheckExact(full_name) && PyLong_CheckExact(index.p)) {
            const Py_ssize_t at = PyLong_AsSsize_t(index.p);
            if (at == -1 && PyErr_Occurred()) throw PythonError{};
            if (at == -1) return mapping_owned(full_name);
            uri.p = checked(PyUnicode_Substring(full_name, 0, at));
            local.p = checked(PyUnicode_Substring(full_name, at + 1, PyUnicode_GET_LENGTH(full_name)));
        } else {
            Ref minus_one(checked(PyLong_FromLong(-1)));
            const int absent = PyObject_RichCompareBool(index.p, minus_one.p, Py_EQ);
            if (absent < 0) throw PythonError{};
            if (absent) return mapping_owned(full_name);
            Ref left(checked(PySlice_New(nullptr, index.p, nullptr)));
            uri.p = checked(PyObject_GetItem(full_name, left.p));
            Ref one(checked(PyLong_FromLong(1)));
            Ref after(checked(PyNumber_Add(index.p, one.p)));
            Ref right(checked(PySlice_New(after.p, nullptr, nullptr)));
            local.p = checked(PyObject_GetItem(full_name, right.p));
        }
        Ref short_uri(PyObject_GetItem(options[Namespaces], uri.p));
        if (!short_uri.p) {
            if (!PyErr_ExceptionMatches(PyExc_KeyError)) throw PythonError{};
            PyErr_Clear(); short_uri.p = mapping_owned(uri.p);
        }
        if (!mapping_truth(short_uri.p)) return local.release();
        Ref pair(checked(PyTuple_Pack(2, short_uri.p, local.p)));
        return join(options[NamespaceSeparator], pair.p);
    }
    static PyObject* join(PyObject* delimiter, PyObject* values) {
        if (PyUnicode_CheckExact(delimiter)) return checked(PyUnicode_Join(delimiter, values));
        return checked(PyObject_CallMethod(delimiter, "join", "(O)", values));
    }
    static PyObject* strip(PyObject* value) {
        if (!PyUnicode_CheckExact(value))
            return checked(PyObject_CallMethod(value, "strip", nullptr));
        Py_ssize_t begin = 0, end = PyUnicode_GET_LENGTH(value);
        const int kind = PyUnicode_KIND(value);
        void* chars = PyUnicode_DATA(value);
        while (begin < end && Py_UNICODE_ISSPACE(PyUnicode_READ(kind, chars, begin))) ++begin;
        while (end > begin && Py_UNICODE_ISSPACE(PyUnicode_READ(kind, chars, end - 1))) --end;
        return checked(PyUnicode_Substring(value, begin, end));
    }
    PyObject* joined_data() {
        return PyList_GET_SIZE(data) ? join(options[CdataSeparator], data) : mapping_owned(Py_None);
    }
    bool should_force(Option option, PyObject* key, PyObject* value) {
        PyObject* force = options[option];
        if (!mapping_truth(force)) return false;
        if (PyBool_Check(force)) return force == Py_True;
        const int is_bool = PyObject_IsInstance(force, reinterpret_cast<PyObject*>(&PyBool_Type));
        if (is_bool < 0) throw PythonError{};
        if (is_bool) return mapping_truth(force);
        const int contains = PySequence_Contains(force, key);
        if (contains >= 0) return contains != 0;
        if (!PyErr_ExceptionMatches(PyExc_TypeError)) throw PythonError{};
        Ref result;
        {
            MappingHandledError handled;
            Ref parent_path(checked(PyList_GetSlice(path, 0, PyList_GET_SIZE(path) - 1)));
            result.p = checked(PyObject_CallFunctionObjArgs(force, parent_path.p, key, value, nullptr));
        }
        // The caller tests the returned value after the TypeError handler exits.
        return mapping_truth(result.p);
    }
    static void unpack_two(PyObject* pair, Ref& key, Ref& value) {
        if (PyTuple_CheckExact(pair) || PyList_CheckExact(pair)) {
            const Py_ssize_t size = PySequence_Fast_GET_SIZE(pair);
            if (size != 2) {
                if (size > 2) PyErr_SetString(PyExc_ValueError, "too many values to unpack (expected 2)");
                else PyErr_Format(PyExc_ValueError, "not enough values to unpack (expected 2, got %zd)", size);
                throw PythonError{};
            }
            key.p = mapping_owned(PySequence_Fast_GET_ITEM(pair, 0));
            value.p = mapping_owned(PySequence_Fast_GET_ITEM(pair, 1));
            return;
        }
        Ref iterator(PyObject_GetIter(pair));
        if (!iterator.p) {
            if (PyErr_ExceptionMatches(PyExc_TypeError) && !Py_TYPE(pair)->tp_iter && !PySequence_Check(pair))
                PyErr_Format(PyExc_TypeError, "cannot unpack non-iterable %.200s object", Py_TYPE(pair)->tp_name);
            throw PythonError{};
        }
        key.p = PyIter_Next(iterator.p);
        if (!key.p) {
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "not enough values to unpack (expected 2, got 0)");
            throw PythonError{};
        }
        value.p = PyIter_Next(iterator.p);
        if (!value.p) {
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "not enough values to unpack (expected 2, got 1)");
            throw PythonError{};
        }
        Ref extra(PyIter_Next(iterator.p));
        if (extra.p) { PyErr_SetString(PyExc_ValueError, "too many values to unpack (expected 2)"); throw PythonError{}; }
        if (PyErr_Occurred()) throw PythonError{};
    }
    static void assign(PyObject* mapping, PyObject* key, PyObject* value) {
        mapping_checked(PyDict_CheckExact(mapping) ? PyDict_SetItem(mapping, key, value)
                                                  : PyObject_SetItem(mapping, key, value));
    }
    PyObject* push_data(PyObject* target, PyObject* original_key, PyObject* original_value) {
        Ref key, value;
        if (options[Postprocessor] != Py_None) {
            Ref result(checked(PyObject_CallFunctionObjArgs(options[Postprocessor], path,
                                                           original_key, original_value, nullptr)));
            if (result.p == Py_None) return mapping_owned(target);
            unpack_two(result.p, key, value);
        } else {
            key.p = mapping_owned(original_key); value.p = mapping_owned(original_value);
        }
        Ref result(target == Py_None ? new_mapping() : mapping_owned(target));
        try {
            Ref previous;
            if (PyDict_CheckExact(result.p)) {
                PyObject* borrowed = PyDict_GetItemWithError(result.p, key.p);
                if (borrowed) previous.p = mapping_owned(borrowed);
                else if (PyErr_Occurred()) throw PythonError{};
            } else previous.p = checked(PyObject_GetItem(result.p, key.p));
            if (previous.p) {
                int is_list = PyList_Check(previous.p) ? 1 : PyObject_IsInstance(previous.p, reinterpret_cast<PyObject*>(&PyList_Type));
                if (is_list < 0) throw PythonError{};
                if (is_list) {
                    if (PyList_CheckExact(previous.p)) mapping_checked(PyList_Append(previous.p, value.p));
                    else { Ref ignored(checked(PyObject_CallMethod(previous.p, "append", "(O)", value.p))); }
                } else {
                    Ref values(checked(PyList_New(2)));
                    PyList_SET_ITEM(values.p, 0, mapping_owned(previous.p));
                    PyList_SET_ITEM(values.p, 1, mapping_owned(value.p));
                    assign(result.p, key.p, values.p);
                }
                return result.release();
            }
        } catch (const PythonError&) {
            // The reference catches KeyError around lookup, append and update,
            // including exceptions from user-defined mapping/list subclasses.
            if (!PyErr_ExceptionMatches(PyExc_KeyError)) throw;
            MappingHandledError handled;
            put_new(result.p, key.p, value.p);
            return result.release();
        }
        // An exact-dict miss is ordinary control flow. Preserve its Python
        // KeyError handler without paying for a C++ throw/catch per new key.
        // Keep the handler outside the try block: a KeyError from put_new must
        // propagate rather than retrying the except body a second time.
        Ref arguments(checked(PyTuple_Pack(1, key.p)));
        PyErr_SetObject(PyExc_KeyError, arguments.p);
        MappingHandledError handled;
        put_new(result.p, key.p, value.p);
        return result.release();
    }
    void put_new(PyObject* target, PyObject* key, PyObject* value) {
        if (should_force(ForceList, key, value)) {
            Ref values(checked(PyList_New(1)));
            PyList_SET_ITEM(values.p, 0, mapping_owned(value));
            assign(target, key, values.p);
        } else assign(target, key, value);
    }
    PyObject* attributes_mapping(const rapidxml_events::Attributes& attrs) {
        if (options[Constructor] == reinterpret_cast<PyObject*>(&PyDict_Type)) {
            Ref result(checked(PyDict_New()));
            for (const auto& attribute : attrs) {
                Ref key(cached_name(attribute.first));
                Ref value(PythonEventSink::unicode(attribute.second));
                mapping_checked(PyDict_SetItem(result.p, key.p, value.p));
            }
            return result.release();
        }
        // The custom constructor receives the same zip-of-key/value-lists as
        // _attrs_to_dict, rather than a materialized list or a dict substitute.
        Ref keys(checked(PyList_New(static_cast<Py_ssize_t>(attrs.size()))));
        Ref values(checked(PyList_New(static_cast<Py_ssize_t>(attrs.size()))));
        for (size_t i = 0; i < attrs.size(); ++i) {
            PyList_SET_ITEM(keys.p, static_cast<Py_ssize_t>(i), cached_name(attrs[i].first));
            PyList_SET_ITEM(values.p, static_cast<Py_ssize_t>(i), PythonEventSink::unicode(attrs[i].second));
        }
        Ref entries(checked(PyObject_CallFunctionObjArgs(reinterpret_cast<PyObject*>(&PyZip_Type), keys.p, values.p, nullptr)));
        return new_mapping(entries.p);
    }
    void start_element(const std::string& full_name, const rapidxml_events::Attributes& attributes) {
        Ref raw_name(cached_name(full_name)), name(build_name(raw_name.p));
        Ref attrs(attributes_mapping(attributes));
        if (mapping_truth(namespace_declarations)) {
            if (!mapping_truth(attrs.p)) mapping_replace(attrs.p, new_mapping());
            Ref xmlns(cached_name("xmlns"));
            assign(attrs.p, xmlns.p, namespace_declarations);
            mapping_replace(namespace_declarations, new_mapping());
        }
        Ref path_entry(checked(PyTuple_Pack(2, name.p, mapping_truth(attrs.p) ? attrs.p : Py_None)));
        mapping_checked(PyList_Append(path, path_entry.p));
        if (!at_depth(Py_GE)) return;
        stack.emplace_back(item, data);
        if (mapping_truth(options[XmlAttribs])) {
            Ref entries(checked(PyList_New(0)));
            Ref attribute_items(checked(PyObject_CallMethod(attrs.p, "items", nullptr)));
            Ref iterator(checked(PyObject_GetIter(attribute_items.p)));
            while (true) {
                Ref pair(PyIter_Next(iterator.p));
                if (!pair.p) { if (PyErr_Occurred()) throw PythonError{}; break; }
                Ref original_key, value;
                unpack_two(pair.p, original_key, value);
                Ref built_key(build_name(original_key.p));
                Ref key(checked(PyNumber_Add(options[AttrPrefix], built_key.p)));
                Ref entry;
                if (mapping_truth(options[Postprocessor]))
                    entry.p = checked(PyObject_CallFunctionObjArgs(options[Postprocessor], path, key.p, value.p, nullptr));
                else entry.p = checked(PyTuple_Pack(2, key.p, value.p));
                if (mapping_truth(entry.p)) mapping_checked(PyList_Append(entries.p, entry.p));
            }
            mapping_replace(attrs.p, new_mapping(entries.p));
        } else mapping_replace(attrs.p, mapping_owned(Py_None));
        mapping_replace(item, mapping_owned(mapping_truth(attrs.p) ? attrs.p : Py_None));
        mapping_replace(data, checked(PyList_New(0)));
    }
    void restore_parent() {
        if (stack.empty()) {
            mapping_replace(item, mapping_owned(Py_None));
            mapping_replace(data, checked(PyList_New(0)));
            return;
        }
        Frame& frame = stack.back();
        Ref parent_item(frame.item), parent_data(frame.data);
        frame.item = frame.data = nullptr;
        stack.pop_back();
        // Detach both frame references before any decref can run a finalizer
        // or cyclic GC; traversal must never report two owners for one ref.
        mapping_replace(item, parent_item.release());
        mapping_replace(data, parent_data.release());
    }
    void pop_path() {
        if (!PyList_GET_SIZE(path)) {
            PyErr_SetString(PyExc_IndexError, "pop from empty list"); throw PythonError{};
        }
        mapping_checked(PySequence_DelItem(path, PyList_GET_SIZE(path) - 1));
    }
    void end_element(const std::string& full_name) {
        Ref raw_name(cached_name(full_name)), name(build_name(raw_name.p));
        if (at_depth(Py_EQ)) {
            Ref emitted(item == Py_None ? joined_data() : mapping_owned(item));
            if (options[Callback]) {
                Ref result(checked(PyObject_CallFunctionObjArgs(options[Callback], path, emitted.p, nullptr)));
                if (!mapping_truth(result.p)) {
                    PyErr_SetNone(options[Interrupted]); throw PythonError{};
                }
            }
            restore_parent(); pop_path(); return;
        }
        if (!stack.empty()) {
            Ref text_value(joined_data()), child(mapping_owned(item));
            restore_parent();
            if (mapping_truth(options[StripWhitespace]) && mapping_truth(text_value.p)) {
                mapping_replace(text_value.p, strip(text_value.p));
                if (!mapping_truth(text_value.p)) mapping_replace(text_value.p, mapping_owned(Py_None));
            }
            if (mapping_truth(text_value.p) && should_force(ForceCdata, name.p, text_value.p) && child.p == Py_None)
                mapping_replace(child.p, new_mapping());
            if (child.p != Py_None) {
                if (mapping_truth(text_value.p)) {
                    // push_data's returned mapping is intentionally discarded,
                    // matching the reference's behavior for postprocessor drops.
                    Ref ignored(push_data(child.p, options[CdataKey], text_value.p));
                }
                mapping_replace(item, push_data(item, name.p, child.p));
            } else mapping_replace(item, push_data(item, name.p, text_value.p));
        } else restore_parent();
        pop_path();
    }
    PyObject* fast_put(PyObject* target, PyObject* key, PyObject* value) {
        // A .result read may expose a partially built dictionary. Keep the
        // optimized frame/text representation, but honor arbitrary injected
        // key equality, list.append overrides and handled KeyError contexts.
        if (!builtin_objects_only) return push_data(target, key, value);
        Ref result(target == Py_None ? checked(PyDict_New()) : mapping_owned(target));
        try {
            PyObject* borrowed = PyDict_GetItemWithError(result.p, key);
            // Own the lookup result before list allocation can invoke GC. A
            // finalizer may inspect .result and mutate the original mapping.
            Ref previous(borrowed ? mapping_owned(borrowed) : nullptr);
            if (!previous.p) {
                if (PyErr_Occurred()) throw PythonError{};
                mapping_checked(PyDict_SetItem(result.p, key, value));
            } else if (PyList_CheckExact(previous.p)) {
                mapping_checked(PyList_Append(previous.p, value));
            } else {
                Ref repeated(checked(PyList_New(2)));
                PyList_SET_ITEM(repeated.p, 0, mapping_owned(previous.p));
                PyList_SET_ITEM(repeated.p, 1, mapping_owned(value));
                // GC may revoke builtin_objects_only during list allocation.
                // Keep the original lookup value, as Python does, and use the
                // full KeyError handling below for equality hooks newly added
                // to this dictionary. Later merges use push_data directly.
                mapping_checked(PyDict_SetItem(result.p, key, repeated.p));
            }
        } catch (const PythonError&) {
            if (!PyErr_ExceptionMatches(PyExc_KeyError)) throw;
            MappingHandledError handled;
            put_new(result.p, key, value);
        }
        return result.release();
    }
    void fast_start(const rapidxml_events::Attributes& attributes) {
        stack.emplace_back(item, data);
        Ref child;
        if (!attributes.empty()) {
            child.p = checked(PyDict_New());
            for (const auto& attribute : attributes) {
                Ref key(cached_attribute_name(attribute.first));
                Ref value(PythonEventSink::unicode(attribute.second));
                mapping_checked(PyDict_SetItem(child.p, key.p, value.p));
            }
        } else child.p = mapping_owned(Py_None);
        mapping_replace(item, child.release());
        mapping_replace(data, mapping_owned(Py_None));
    }
    void fast_end(const std::string& full_name) {
        Ref name(cached_name(full_name));
        Ref text_value;
        if (data == Py_None || PyUnicode_CheckExact(data)) text_value.p = mapping_owned(data);
        else text_value.p = checked(PyUnicode_Join(options[CdataSeparator], data));
        Ref child(mapping_owned(item));
        restore_parent();
        if (text_value.p != Py_None) {
            mapping_replace(text_value.p, strip(text_value.p));
            if (!PyUnicode_GET_LENGTH(text_value.p)) mapping_replace(text_value.p, mapping_owned(Py_None));
        }
        if (child.p != Py_None && text_value.p != Py_None) {
            Ref ignored(fast_put(child.p, options[CdataKey], text_value.p));
        }
        mapping_replace(item, fast_put(item, name.p, child.p == Py_None ? text_value.p : child.p));
    }
    void fast_text(PyObject* value) {
        if (data == Py_None) mapping_replace(data, mapping_owned(value));
        else if (PyUnicode_CheckExact(data)) {
            Ref fragments(checked(PyList_New(2)));
            PyList_SET_ITEM(fragments.p, 0, mapping_owned(data));
            PyList_SET_ITEM(fragments.p, 1, mapping_owned(value));
            mapping_replace(data, fragments.release());
        } else mapping_checked(PyList_Append(data, value));
    }
    [[noreturn]] void namespace_error(const char* message, int code = 4) {
        set_positioned_parse_error(message, code, parser ? parser->line() : 1,
                                   parser ? parser->column() : 0, parser ? parser->byte_index() : 0);
        throw PythonError{};
    }
    std::string expanded_name(const std::string& name, bool attribute = false) {
        const size_t colon = name.find(':');
        std::string local, uri;
        if (colon != std::string::npos) {
            if (!colon || colon + 1 == name.size() || name.find(':', colon + 1) != std::string::npos)
                namespace_error("not well-formed (invalid token)");
            const auto found = bindings->find(name.substr(0, colon));
            if (found == bindings->end()) namespace_error("unbound prefix", 27);
            uri = found->second; local = name.substr(colon + 1);
        } else {
            local = name;
            if (!attribute) {
                const auto found = bindings->find("");
                if (found != bindings->end()) uri = found->second;
            }
        }
        return uri.empty() ? local : uri + separator + local;
    }
    void start(const std::string& name, const rapidxml_events::Attributes& attributes) override {
        if (fast_mapping) { fast_start(attributes); return; }
        if (!process_namespaces) { start_element(name, attributes); return; }
        const auto previous = bindings;
        rapidxml_events::Attributes declarations, ordinary;
        for (const auto& attribute : attributes) {
            if (attribute.first == "xmlns") declarations.emplace_back("", attribute.second);
            else if (attribute.first.compare(0, 6, "xmlns:") == 0) {
                const std::string prefix = attribute.first.substr(6);
                if (prefix.empty() || prefix.find(':') != std::string::npos)
                    namespace_error("not well-formed (invalid token)");
                declarations.emplace_back(prefix, attribute.second);
            } else ordinary.push_back(attribute);
        }
        if (!declarations.empty()) bindings = std::make_shared<Bindings>(*previous);
        for (const auto& declaration : declarations) {
            const std::string& prefix = declaration.first;
            const std::string& uri = declaration.second;
            if (prefix == "xmlns") namespace_error("reserved prefix (xmlns) must not be declared or undeclared", 39);
            if (prefix == "xml" && uri != xml_namespace)
                namespace_error("reserved prefix (xml) must not be undeclared or bound to another namespace name", 38);
            if (uri == xmlns_namespace || (uri == xml_namespace && prefix != "xml"))
                namespace_error("prefix must not be bound to one of the reserved namespace names", 40);
            if (!prefix.empty() && uri.empty()) namespace_error("must not undeclare prefix", 28);
            if (!separator.empty() && separator != ":" && uri.find(separator) != std::string::npos)
                namespace_error("syntax error", 2);
            (*bindings)[prefix] = uri;
            Ref py_prefix(cached_name(prefix));
            Ref py_uri(uri.empty() ? mapping_owned(Py_None) : PythonEventSink::unicode(uri));
            assign(namespace_declarations, py_prefix.p, py_uri.p);
        }
        rapidxml_events::Attributes expanded;
        std::unordered_set<std::string> used;
        for (const auto& attribute : ordinary) {
            std::string key = expanded_name(attribute.first, true);
            if (!used.emplace(key).second) namespace_error("duplicate attribute", 8);
            expanded.emplace_back(std::move(key), attribute.second);
        }
        const std::string full_name = expanded_name(name);
        scopes.push_back(previous);
        start_element(full_name, expanded);
    }
    void end(const std::string& name) override {
        if (fast_mapping) { fast_end(name); return; }
        if (!process_namespaces) { end_element(name); return; }
        end_element(expanded_name(name));
        bindings = scopes.back(); scopes.pop_back();
    }
    void text(const std::string& value) override {
        Ref text_value(PythonEventSink::unicode(value));
        if (fast_mapping) fast_text(text_value.p);
        else mapping_checked(PyList_Append(data, text_value.p));
    }
    void comment(const std::string& value) override {
        if (!process_comments) return;
        Ref text_value(PythonEventSink::unicode(value));
        if (mapping_truth(options[StripWhitespace])) mapping_replace(text_value.p, strip(text_value.p));
        mapping_replace(item, push_data(item, options[CommentKey], text_value.p));
    }
};

struct PyMappingParser {
    PyObject_HEAD
    NativeMappingSink* sink;
    rapidxml_events::Parser* parser;
    bool running;
};
int mapping_parser_traverse(PyMappingParser* self, visitproc visit, void* arg) {
    return self->sink ? self->sink->traverse(visit, arg) : 0;
}
int mapping_parser_clear(PyMappingParser* self) {
    auto* parser = self->parser; self->parser = nullptr;
    auto* sink = self->sink; self->sink = nullptr;
    delete parser; delete sink;
    return 0;
}
void mapping_parser_dealloc(PyMappingParser* self) {
    PyObject_GC_UnTrack(self); mapping_parser_clear(self);
    Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}
int mapping_parser_init(PyMappingParser* self, PyObject* args, PyObject* kwargs) {
    if (self->running) { PyErr_SetString(PyExc_RuntimeError, "parser is already processing input"); return -1; }
    self->running = true; // Initialization invokes user constructors as well.
    try {
        Ref separator(checked(PyUnicode_FromString(":")));
        Ref item_depth(checked(PyLong_FromLong(0)));
        Ref prefix(checked(PyUnicode_FromString("@")));
        Ref cdata_key(checked(PyUnicode_FromString("#text")));
        Ref cdata_separator(checked(PyUnicode_FromString("")));
        Ref comment_key(checked(PyUnicode_FromString("#comment")));
        PyObject* disable_entities = Py_True;
        PyObject* process_namespaces = Py_False;
        PyObject* process_comments = Py_False;
        std::array<PyObject*, NativeMappingSink::OptionCount> values = {
            item_depth.p, nullptr, Py_True, prefix.p, cdata_key.p, Py_False,
            cdata_separator.p, Py_None, reinterpret_cast<PyObject*>(&PyDict_Type),
            Py_True, separator.p, Py_None, Py_None, comment_key.p, PyExc_RuntimeError
        };
        using S = NativeMappingSink;
        static const char* names[] = {
            "disable_entities", "process_namespaces", "namespace_separator", "process_comments", "interrupted",
            "item_depth", "item_callback", "xml_attribs", "attr_prefix", "cdata_key", "force_cdata", "cdata_separator",
            "postprocessor", "dict_constructor", "strip_whitespace", "namespaces", "force_list", "comment_key", nullptr
        };
        if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|$OOOOOOOOOOOOOOOOOO:NativeMappingParser", const_cast<char**>(names),
                &disable_entities, &process_namespaces, &values[S::NamespaceSeparator], &process_comments, &values[S::Interrupted],
                &values[S::Depth], &values[S::Callback], &values[S::XmlAttribs], &values[S::AttrPrefix], &values[S::CdataKey],
                &values[S::ForceCdata], &values[S::CdataSeparator], &values[S::Postprocessor], &values[S::Constructor],
                &values[S::StripWhitespace], &values[S::Namespaces], &values[S::ForceList], &values[S::CommentKey])) {
            self->running = false; return -1;
        }
        mapping_parser_clear(self);
        self->sink = new NativeMappingSink();
        self->sink->initialize(values, process_namespaces, process_comments);
        self->parser = new rapidxml_events::Parser(*self->sink, mapping_truth(disable_entities), self->sink->process_comments);
        self->sink->parser = self->parser;
        self->running = false;
        return 0;
    } catch (const PythonError&) {}
      catch (const std::bad_alloc&) { PyErr_NoMemory(); }
      catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); }
    mapping_parser_clear(self);
    self->running = false;
    return -1;
}
PyObject* mapping_parser_feed(PyMappingParser* self, PyObject* args, PyObject* kwargs) {
    PyObject* input; int final = 0; Py_ssize_t undecoded_bytes = 0;
    static const char* names[] = {"data", "final", "undecoded_bytes", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|pn:feed", const_cast<char**>(names),
                                    &input, &final, &undecoded_bytes)) return nullptr;
    if (undecoded_bytes < 0) { PyErr_SetString(PyExc_ValueError, "undecoded_bytes must be nonnegative"); return nullptr; }
    if (!self->parser) { PyErr_SetString(PyExc_RuntimeError, "parser is not initialized"); return nullptr; }
    if (self->running) { PyErr_SetString(PyExc_RuntimeError, "parser is already processing input"); return nullptr; }
    const char* data = nullptr; Py_ssize_t size = 0;
    if (PyUnicode_Check(input)) data = PyUnicode_AsUTF8AndSize(input, &size);
    else if (PyBytes_Check(input)) { data = PyBytes_AS_STRING(input); size = PyBytes_GET_SIZE(input); }
    else { PyErr_SetString(PyExc_TypeError, "feed requires UTF-8 bytes or text"); return nullptr; }
    if (!data) return nullptr;
    self->running = true;
    try {
        self->parser->feed(data, static_cast<size_t>(size), final != 0, static_cast<size_t>(undecoded_bytes));
        self->running = false; Py_RETURN_NONE;
    } catch (const PythonError&) {}
      catch (const rapidxml_events::EntitiesDisabled& error) { PyErr_SetString(PyExc_ValueError, error.what()); }
      catch (const rapidxml_events::Error& error) { set_event_error(error); }
      catch (const std::bad_alloc&) { PyErr_NoMemory(); }
      catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); }
    self->running = false;
    return nullptr;
}
PyObject* mapping_parser_result(PyMappingParser* self, void*) {
    if (self->sink) self->sink->builtin_objects_only = false;
    return mapping_owned(self->sink && self->sink->item ? self->sink->item : Py_None);
}
PyObject* mapping_parser_line(PyMappingParser* self, void*) { return PyLong_FromSize_t(self->parser ? self->parser->line() : 1); }
PyObject* mapping_parser_column(PyMappingParser* self, void*) { return PyLong_FromSize_t(self->parser ? self->parser->column() : 0); }
PyObject* mapping_parser_index(PyMappingParser* self, void*) { return PyLong_FromSize_t(self->parser ? self->parser->byte_index() : 0); }
PyObject* mapping_parser_source_encoding(PyMappingParser* self, PyObject* value) {
    if (!self->parser) { PyErr_SetString(PyExc_RuntimeError, "parser is not initialized"); return nullptr; }
    const char* mode = PyUnicode_AsUTF8(value);
    if (!mode) return nullptr;
    int width;
    if (std::strcmp(mode, "utf8") == 0) width = 0;
    else if (std::strcmp(mode, "singlebyte") == 0) width = 1;
    else if (std::strcmp(mode, "utf16") == 0) width = 2;
    else { PyErr_SetString(PyExc_ValueError, "unknown source encoding metric"); return nullptr; }
    self->parser->set_source_encoding(width); Py_RETURN_NONE;
}
PyObject* mapping_parser_close(PyMappingParser* self, PyObject*) {
    if (self->running) { PyErr_SetString(PyExc_RuntimeError, "parser is already processing input"); return nullptr; }
    self->running = true;
    mapping_parser_clear(self);
    self->running = false;
    Py_RETURN_NONE;
}
PyMethodDef mapping_parser_methods[] = {
    {"close", reinterpret_cast<PyCFunction>(mapping_parser_close), METH_NOARGS, "Release parser buffers, options and mapping state."},
    {"set_source_encoding", reinterpret_cast<PyCFunction>(mapping_parser_source_encoding), METH_O, "Set original source encoding units for incremental buffering."},
    {"feed", reinterpret_cast<PyCFunction>(mapping_parser_feed), METH_VARARGS | METH_KEYWORDS, "Feed decoded UTF-8 input directly into Python mapping construction."},
    {nullptr, nullptr, 0, nullptr}
};
PyGetSetDef mapping_parser_getset[] = {
    {const_cast<char*>("result"), reinterpret_cast<getter>(mapping_parser_result), nullptr, nullptr, nullptr},
    {const_cast<char*>("lineno"), reinterpret_cast<getter>(mapping_parser_line), nullptr, nullptr, nullptr},
    {const_cast<char*>("offset"), reinterpret_cast<getter>(mapping_parser_column), nullptr, nullptr, nullptr},
    {const_cast<char*>("byte_index"), reinterpret_cast<getter>(mapping_parser_index), nullptr, nullptr, nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr}
};
PyTypeObject mapping_parser_type = { PyVarObject_HEAD_INIT(nullptr, 0) };
int add_mapping_parser(PyObject* module) {
    mapping_parser_type.tp_name = "rapidxmltodict._native.NativeMappingParser";
    mapping_parser_type.tp_basicsize = sizeof(PyMappingParser);
    mapping_parser_type.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC;
    mapping_parser_type.tp_new = PyType_GenericNew;
    mapping_parser_type.tp_init = reinterpret_cast<initproc>(mapping_parser_init);
    mapping_parser_type.tp_dealloc = reinterpret_cast<destructor>(mapping_parser_dealloc);
    mapping_parser_type.tp_traverse = reinterpret_cast<traverseproc>(mapping_parser_traverse);
    mapping_parser_type.tp_clear = reinterpret_cast<inquiry>(mapping_parser_clear);
    mapping_parser_type.tp_methods = mapping_parser_methods;
    mapping_parser_type.tp_getset = mapping_parser_getset;
    if (PyType_Ready(&mapping_parser_type) < 0) return -1;
    Py_INCREF(&mapping_parser_type);
    if (PyModule_AddObject(module, "NativeMappingParser", reinterpret_cast<PyObject*>(&mapping_parser_type)) < 0) {
        Py_DECREF(&mapping_parser_type); return -1;
    }
    return 0;
}
