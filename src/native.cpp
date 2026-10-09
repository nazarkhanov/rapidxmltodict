#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <rapidxml/rapidxml.hpp>
#include "rapidxml_events.hpp"
#include <cstring>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
#include <memory>

namespace {
struct Ref {
    PyObject* p;
    explicit Ref(PyObject* x = nullptr) : p(x) {}
    ~Ref() { Py_XDECREF(p); }
    Ref(const Ref&) = delete;
    Ref& operator=(const Ref&) = delete;
    PyObject* release() { PyObject* x = p; p = nullptr; return x; }
};
struct PythonError {};
PyObject* checked(PyObject* p) { if (!p) throw PythonError{}; return p; }

struct Builder {
    bool compact;
    explicit Builder(bool c) : compact(c) {}
    using Cache = std::unordered_map<std::string_view, PyObject*>;
    Cache elements, attributes;
    Ref text_key{checked(PyUnicode_FromString("#text"))};
    ~Builder() {
        for(auto& kv:elements) Py_DECREF(kv.second);
        for(auto& kv:attributes) Py_DECREF(kv.second);
    }
    PyObject* key(const char* s, size_t n, bool attr=false) {
        auto& cache=attr ? attributes : elements;
        std::string_view v(s,n);
        auto it=cache.find(v);
        if(it!=cache.end()) return it->second;
        Ref name;
        if(attr) {
            std::string prefixed("@"); prefixed.append(s,n);
            name.p=checked(PyUnicode_DecodeUTF8(prefixed.data(),static_cast<Py_ssize_t>(prefixed.size()),"strict"));
        } else name.p=checked(PyUnicode_DecodeUTF8(s,static_cast<Py_ssize_t>(n),"strict"));
        cache.emplace(v,name.p);
        return name.release();
    }
    PyObject* element_key(rapidxml::xml_node<char>* node) {
        return key(node->name(), node->name_size());
    }
    void put(PyObject* dict,PyObject* k,PyObject* value) {
        PyObject* old=PyDict_GetItemWithError(dict,k);
        if(old) {
            if(PyList_CheckExact(old)) {
                if(PyList_Append(old,value)<0) throw PythonError{};
            } else {
                Ref list(checked(PyList_New(2)));
                Py_INCREF(old); PyList_SET_ITEM(list.p,0,old);
                Py_INCREF(value); PyList_SET_ITEM(list.p,1,value);
                if(PyDict_SetItem(dict,k,list.p)<0) throw PythonError{};
            }
        } else {
            if(PyErr_Occurred() || PyDict_SetItem(dict,k,value)<0) throw PythonError{};
        }
    }
    PyObject* build(rapidxml::xml_node<char>* node) {
        Ref dict;
        for(auto* a=node->first_attribute();a;a=a->next_attribute()) {
            if(!dict.p) dict.p=checked(PyDict_New());
            Ref value(checked(PyUnicode_DecodeUTF8(a->value(),a->value_size(),"strict")));
            if(PyDict_SetItem(dict.p,key(a->name(),a->name_size(),true),value.p)<0) throw PythonError{};
        }
        const char* first=compact && node->value_size() ? node->value() : nullptr;
        size_t len=first ? node->value_size() : 0;
        std::string joined; bool multiple=false;
        for(auto* child=node->first_node();child;child=child->next_sibling()) {
            if(child->type()==rapidxml::node_element) {
                if(!dict.p) dict.p=checked(PyDict_New());
                Ref value(build(child)); put(dict.p,element_key(child),value.p);
            } else if(child->type()==rapidxml::node_data || child->type()==rapidxml::node_cdata) {
                if(!first) {first=child->value();len=child->value_size();}
                else {
                    if(!multiple) {joined.assign(first,len);multiple=true;}
                    joined.append(child->value(),child->value_size());
                }
            }
        }
        Ref value;
        if(first) {
            const char* s=multiple?joined.data():first;
            size_t size=multiple?joined.size():len;
            Ref raw(checked(PyUnicode_DecodeUTF8(s,size,"strict")));
            // CPython's Unicode whitespace semantics match str.strip exactly.
            Py_ssize_t start=0,end=PyUnicode_GET_LENGTH(raw.p);
            int kind=PyUnicode_KIND(raw.p); void* data=PyUnicode_DATA(raw.p);
            while(start<end && Py_UNICODE_ISSPACE(PyUnicode_READ(kind,data,start))) ++start;
            while(end>start && Py_UNICODE_ISSPACE(PyUnicode_READ(kind,data,end-1))) --end;
            if(end>start) value.p=checked(PyUnicode_Substring(raw.p,start,end));
        }
        if(dict.p) {
            if(value.p && PyDict_SetItem(dict.p,text_key.p,value.p)<0) throw PythonError{};
            return dict.release();
        }
        if(value.p) return value.release();
        Py_INCREF(Py_None); return Py_None;
    }
};

#include "native_events_binding.hpp"

// Locations are computed from immutable input only on the error path. Parsing
// and in-place normalization therefore do not require a whole-input prepass.
void set_dom_error(const char* message, int code, const char* source, size_t size,
                   const char* buffer, const char* where) {
    // RapidXML's memory-pool failure uses parse_error with a null location.
    if (!where || !buffer) { PyErr_NoMemory(); return; }
    size_t offset = static_cast<size_t>(where - buffer);
    if (offset > size) offset = size;
    size_t line = 1, column = 0;
    bool carriage_return = false;
    for (size_t i = 0; i < offset; ++i) {
        const unsigned char c = static_cast<unsigned char>(source[i]);
        if (c == '\r') { ++line; column = 0; carriage_return = true; }
        else if (c == '\n') { if (!carriage_return) ++line; column = 0; carriage_return = false; }
        else {
            carriage_return = false;
            if ((c & 0xc0) != 0x80) ++column;
        }
    }
    set_positioned_parse_error(message, code, line, column, offset);
}

PyObject* convert(PyObject*, PyObject* input) {
    if (!PyBytes_Check(input)) { PyErr_SetString(PyExc_TypeError, "internal converter requires bytes"); return nullptr; }
    const char* source = PyBytes_AS_STRING(input);
    const size_t size = static_cast<size_t>(PyBytes_GET_SIZE(input));
    std::vector<char> buffer;
    try {
        buffer.assign(source, source + size);
        buffer.push_back('\0');
        // Strict checks and XML normalization execute inside RapidXML's token
        // consumption. The bounded parser distinguishes embedded NUL from EOF.
        auto doc = std::make_unique<rapidxml::xml_document<char>>();
        doc->parse<rapidxml::parse_strict | rapidxml::parse_no_string_terminators |
                   rapidxml::parse_compact_data>(buffer.data(), size);
        Builder builder(true);
        Ref result(checked(PyDict_New()));
        for (auto* node = doc->first_node(); node; node = node->next_sibling()) {
            if (node->type() != rapidxml::node_element) continue;
            Ref value(builder.build(node));
            builder.put(result.p, builder.element_key(node), value.p);
        }
        return result.release();
    } catch (const PythonError&) { return nullptr; }
      catch (const rapidxml::strict_unsupported&) { Py_INCREF(Py_NotImplemented); return Py_NotImplemented; }
      catch (const rapidxml::strict_parse_error& error) {
          set_dom_error(error.what(), error.code, source, size, buffer.data(), error.where<char>());
          return nullptr;
      }
      catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
      catch (const rapidxml::parse_error& error) {
          set_dom_error(error.what(), 4, source, size, buffer.data(), error.where<char>());
          return nullptr;
      }
      catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); return nullptr; }
}

PyMethodDef methods[]={{"validate", reinterpret_cast<PyCFunction>(validate_xml), METH_VARARGS | METH_KEYWORDS, "Validate XML with the native incremental parser."},{"convert",convert,METH_O,"Strict RapidXML parsing and dictionary conversion in one consuming parse."},{nullptr,nullptr,0,nullptr}};
PyModuleDef module={PyModuleDef_HEAD_INIT,"_native",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
}
PyMODINIT_FUNC PyInit__native() {
    PyObject* result = PyModule_Create(&module);
    if (!result) return nullptr;
    if (add_event_parser(result) < 0) { Py_DECREF(result); return nullptr; }
    return result;
}
