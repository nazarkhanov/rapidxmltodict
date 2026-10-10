// CPython bridge for the incremental RapidXML events.
// Included by native.cpp inside its implementation namespace.
PyObject* native_parse_error = nullptr;

void set_positioned_parse_error(const char* text, int code, size_t line, size_t column, size_t byte_index) {
    // This runs inside a C++ catch handler: do not allocate C++ strings here,
    // since a second bad_alloc would escape the Python C entry point.
    Ref message(PyUnicode_FromFormat("%s: line %zu, column %zu",
                                     text, line, column));
    if (!message.p) return;
    Ref exception(PyObject_CallOneArg(native_parse_error, message.p));
    if (!exception.p) return;
    const std::pair<const char*, size_t> fields[] = {
        {"code", static_cast<size_t>(code)}, {"lineno", line},
        {"offset", column}, {"byte_index", byte_index},
    };
    for (const auto& field : fields) {
        Ref value(PyLong_FromSize_t(field.second));
        if (!value.p || PyObject_SetAttrString(exception.p, field.first, value.p) < 0) return;
    }
    PyErr_SetObject(native_parse_error, exception.p);
}

void set_event_error(const rapidxml_events::Error& error) {
    set_positioned_parse_error(error.what(), error.code, error.line, error.column, error.byte_index);
}

struct PythonEventSink : rapidxml_events::Sink {
    PyObject* handler; // Owned and GC-traversed by PyEventParser.
    // XML vocabulary belongs to one parser, just like its element stack. Reuse
    // Unicode names across events without growing Python's global intern table.
    std::unordered_map<std::string, PyObject*> names;
    enum Method { Start, End, Text, Comment };
    PyObject* method_names[4] = {nullptr, nullptr, nullptr, nullptr};
    explicit PythonEventSink(PyObject* value) : handler(value) {}
    ~PythonEventSink() override {
        for (const auto& entry : names) Py_DECREF(entry.second);
        for (PyObject* method : method_names) Py_XDECREF(method);
    }
    int traverse(visitproc visit, void* arg) {
        for (const auto& entry : names) Py_VISIT(entry.second);
        for (PyObject* method : method_names) Py_VISIT(method);
        return 0;
    }
    PyObject* cached_name(const std::string& value) {
        auto found = names.find(value);
        if (found != names.end()) { Py_INCREF(found->second); return found->second; }
        Ref name(unicode(value));
        names.emplace(value, name.p);
        PyObject* result = name.release(); // The cache owns the original reference.
        Py_INCREF(result); // Return a separate owned reference to the event.
        return result;
    }
    void invoke(Method method, PyObject* first, PyObject* second = nullptr) {
        static const char* identifiers[] = {"start", "end", "text", "comment"};
        PyObject*& identifier = method_names[method];
        if (!identifier) identifier = checked(PyUnicode_FromString(identifiers[method]));
        PyObject* arguments[] = {handler, first, second};
        // Resolve the method on every event, preserving custom dynamic lookup
        // and callback changes, while avoiding temporary argument tuples and
        // bound methods for normal Python methods (public API since Python 3.9).
        Ref result(checked(PyObject_VectorcallMethod(identifier, arguments, second ? 3 : 2, nullptr)));
    }
    static PyObject* unicode(const std::string& text) {
        return checked(PyUnicode_DecodeUTF8(text.data(), static_cast<Py_ssize_t>(text.size()), "strict"));
    }
    void start(const std::string& name, const std::vector<std::pair<std::string, std::string>>& attrs) override {
        Ref py_name(cached_name(name));
        Ref py_attrs(checked(PyList_New(static_cast<Py_ssize_t>(attrs.size()))));
        for (size_t i = 0; i < attrs.size(); ++i) {
            Ref key(cached_name(attrs[i].first)), value(unicode(attrs[i].second));
            PyObject* pair = checked(PyTuple_Pack(2, key.p, value.p));
            PyList_SET_ITEM(py_attrs.p, static_cast<Py_ssize_t>(i), pair);
        }
        invoke(Start, py_name.p, py_attrs.p);
    }
    void one(Method method, const std::string& value) {
        Ref text(unicode(value));
        invoke(method, text.p);
    }
    void end(const std::string& name) override {
        Ref py_name(cached_name(name));
        invoke(End, py_name.p);
    }
    void text(const std::string& value) override { one(Text, value); }
    void comment(const std::string& value) override { one(Comment, value); }
};

struct NullEventSink : rapidxml_events::Sink {
    void start(const std::string&, const std::vector<std::pair<std::string, std::string>>&) override {}
    void end(const std::string&) override {}
    void text(const std::string&) override {}
    void comment(const std::string&) override {}
};

struct PyEventParser {
    PyObject_HEAD
    PyObject* handler;
    PythonEventSink* sink;
    rapidxml_events::Parser* parser;
    bool running;
};

int event_parser_traverse(PyEventParser* self, visitproc visit, void* arg) {
    Py_VISIT(self->handler);
    return self->sink ? self->sink->traverse(visit, arg) : 0;
}
int event_parser_clear(PyEventParser* self) {
    delete self->parser; self->parser = nullptr;
    delete self->sink; self->sink = nullptr;
    Py_CLEAR(self->handler);
    return 0;
}
void event_parser_dealloc(PyEventParser* self) {
    PyObject_GC_UnTrack(self);
    event_parser_clear(self);
    Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}
int event_parser_init(PyEventParser* self, PyObject* args, PyObject* kwargs) {
    PyObject* handler;
    int disable_entities = 1, process_comments = 0;
    static const char* names[] = {"sink", "disable_entities", "process_comments", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|pp:NativeParser", const_cast<char**>(names),
                                    &handler, &disable_entities, &process_comments)) return -1;
    if (self->running) { PyErr_SetString(PyExc_RuntimeError, "parser is already processing input"); return -1; }
    event_parser_clear(self);
    Py_INCREF(handler); self->handler = handler;
    try {
        self->sink = new PythonEventSink(handler);
        self->parser = new rapidxml_events::Parser(*self->sink, disable_entities != 0, process_comments != 0);
        return 0;
    } catch (const std::bad_alloc&) { PyErr_NoMemory(); }
      catch (const std::exception& e) { PyErr_SetString(PyExc_RuntimeError, e.what()); }
    event_parser_clear(self);
    return -1;
}
PyObject* event_parser_feed(PyEventParser* self, PyObject* args, PyObject* kwargs) {
    PyObject* input;
    int final = 0; Py_ssize_t undecoded_bytes = 0;
    static const char* names[] = {"data", "final", "undecoded_bytes", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|pn:feed", const_cast<char**>(names), &input, &final, &undecoded_bytes)) return nullptr;
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
        self->running = false;
        Py_RETURN_NONE;
    } catch (const PythonError&) {}
      catch (const rapidxml_events::EntitiesDisabled& e) { PyErr_SetString(PyExc_ValueError, e.what()); }
      catch (const rapidxml_events::Error& e) { set_event_error(e); }
      catch (const std::bad_alloc&) { PyErr_NoMemory(); }
      catch (const std::exception& e) { PyErr_SetString(PyExc_RuntimeError, e.what()); }
    self->running = false;
    return nullptr;
}
PyObject* event_parser_line(PyEventParser* self, void*) {
    return PyLong_FromSize_t(self->parser ? self->parser->line() : 1);
}
PyObject* event_parser_column(PyEventParser* self, void*) {
    return PyLong_FromSize_t(self->parser ? self->parser->column() : 0);
}
PyObject* event_parser_index(PyEventParser* self, void*) {
    return PyLong_FromSize_t(self->parser ? self->parser->byte_index() : 0);
}
PyGetSetDef event_parser_getset[] = {
    {const_cast<char*>("lineno"), reinterpret_cast<getter>(event_parser_line), nullptr, nullptr, nullptr},
    {const_cast<char*>("offset"), reinterpret_cast<getter>(event_parser_column), nullptr, nullptr, nullptr},
    {const_cast<char*>("byte_index"), reinterpret_cast<getter>(event_parser_index), nullptr, nullptr, nullptr},
    {nullptr, nullptr, nullptr, nullptr, nullptr}
};
PyObject* event_parser_source_encoding(PyEventParser* self, PyObject* value) {
    if (!self->parser) { PyErr_SetString(PyExc_RuntimeError, "parser is not initialized"); return nullptr; }
    const char* mode = PyUnicode_AsUTF8(value);
    if (!mode) return nullptr;
    int width;
    if (std::strcmp(mode, "utf8") == 0) width = 0;
    else if (std::strcmp(mode, "singlebyte") == 0) width = 1;
    else if (std::strcmp(mode, "utf16") == 0) width = 2;
    else { PyErr_SetString(PyExc_ValueError, "unknown source encoding metric"); return nullptr; }
    self->parser->set_source_encoding(width);
    Py_RETURN_NONE;
}
PyMethodDef event_parser_methods[] = {
    {"set_source_encoding", reinterpret_cast<PyCFunction>(event_parser_source_encoding), METH_O, "Set original UTF-16 input units for incremental buffering."},
    {"feed", reinterpret_cast<PyCFunction>(event_parser_feed), METH_VARARGS | METH_KEYWORDS, "Feed decoded UTF-8 input; callbacks run synchronously."},
    {nullptr, nullptr, 0, nullptr}
};
PyTypeObject event_parser_type = { PyVarObject_HEAD_INIT(nullptr, 0) };

PyObject* validate_xml(PyObject*, PyObject* args, PyObject* kwargs) {
    const char* data; Py_ssize_t size; int disable_entities = 1;
    static const char* names[] = {"data", "disable_entities", nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "y#|p:validate", const_cast<char**>(names), &data, &size, &disable_entities)) return nullptr;
    try {
        NullEventSink sink;
        rapidxml_events::Parser parser(sink, disable_entities != 0, false, true);
        parser.feed(data, static_cast<size_t>(size), true);
        Py_RETURN_NONE;
    } catch (const rapidxml_events::EntitiesDisabled& e) { PyErr_SetString(PyExc_ValueError, e.what()); }
      catch (const rapidxml_events::Error& e) { set_event_error(e); }
      catch (const std::bad_alloc&) { PyErr_NoMemory(); }
      catch (const std::exception& e) { PyErr_SetString(PyExc_RuntimeError, e.what()); }
    return nullptr;
}

int add_event_parser(PyObject* module) {
    event_parser_type.tp_name = "rapidxmltodict._native.NativeParser";
    event_parser_type.tp_basicsize = sizeof(PyEventParser);
    event_parser_type.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC;
    event_parser_type.tp_new = PyType_GenericNew;
    event_parser_type.tp_init = reinterpret_cast<initproc>(event_parser_init);
    event_parser_type.tp_dealloc = reinterpret_cast<destructor>(event_parser_dealloc);
    event_parser_type.tp_traverse = reinterpret_cast<traverseproc>(event_parser_traverse);
    event_parser_type.tp_clear = reinterpret_cast<inquiry>(event_parser_clear);
    event_parser_type.tp_methods = event_parser_methods;
    event_parser_type.tp_getset = event_parser_getset;
    if (PyType_Ready(&event_parser_type) < 0) return -1;
    Py_INCREF(&event_parser_type);
    if (PyModule_AddObject(module, "NativeParser", reinterpret_cast<PyObject*>(&event_parser_type)) < 0) {
        Py_DECREF(&event_parser_type); return -1;
    }
    native_parse_error = PyErr_NewException("rapidxmltodict.ParseError", PyExc_Exception, nullptr);
    if (!native_parse_error) return -1;
    // Keep one native reference as well as the module's reference: parser
    // instances may outlive deletion of the Python module dictionary.
    Py_INCREF(native_parse_error);
    if (PyModule_AddObject(module, "ParseError", native_parse_error) < 0) {
        Py_DECREF(native_parse_error); Py_CLEAR(native_parse_error); return -1;
    }
    return 0;
}
