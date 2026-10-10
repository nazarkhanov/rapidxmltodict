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
    Ref(Ref&& other) noexcept : p(other.release()) {}
    Ref& operator=(Ref&& other) noexcept {
        if (this != &other) { Py_XDECREF(p); p = other.release(); }
        return *this;
    }
    PyObject* release() { PyObject* x = p; p = nullptr; return x; }
};
struct PythonError {};
PyObject* checked(PyObject* p) { if (!p) throw PythonError{}; return p; }


// Raw spans are validated by RapidXML. Only final Python Unicode storage is
// allocated for normalization; there is no mutable input or transformed C++ copy.
struct ValueSpan { const char* data = nullptr; size_t size = 0; unsigned flags = 0; };
template<class Emit> void visit_value(ValueSpan span, Emit emit) {
    const char* p=span.data; const char* end=p+span.size;
    while(p!=end) {
        uint32_t cp=static_cast<unsigned char>(*p++);
        if(cp=='&' && (span.flags & rapidxml::value_has_references)) {
            const char* start=p;
            while(p!=end && *p!=';') ++p;
            if(p==end) { PyErr_SetString(PyExc_RuntimeError,"invalid validated reference"); throw PythonError{}; }
            if(*start=='#') {
                ++start; unsigned base=10; if(start!=p && *start=='x'){base=16;++start;}
                cp=0; for(;start!=p;++start) { unsigned c=static_cast<unsigned char>(*start); cp=cp*base+(c<='9'?c-'0':(c<='F'?c-'A'+10:c-'a'+10)); }
            } else {
                std::string_view key(start,p-start);
                cp=key=="amp"?'&':key=="lt"?'<':key=="gt"?'>':key=="quot"?'"':'\'';
            }
            ++p;
        } else if(cp=='\r' && (span.flags & rapidxml::value_normalize_lines)) {
            if(p!=end && *p=='\n') ++p;
            cp=(span.flags & rapidxml::value_attribute)?' ':'\n';
        } else if((cp=='\n'||cp=='\t') && (span.flags & rapidxml::value_attribute)) cp=' ';
        else if(cp>=0x80) {
            --p; const char* error=nullptr;
            int width=rapidxml::lexical::decode(p,end,cp,error);
            if(width<0) { PyErr_SetString(PyExc_RuntimeError,"invalid validated UTF-8 span"); throw PythonError{}; }
            p+=width;
        }
        emit(cp);
    }
}
PyObject* decode_value(ValueSpan first, const std::vector<ValueSpan>& rest, bool strip) {
    // Common unchanged ASCII values need only one final allocation/copy.
    if(rest.empty() && !(first.flags & (rapidxml::value_has_references | rapidxml::value_normalize_lines | rapidxml::value_non_ascii))) {
        const char* data=first.data; size_t n=first.size;
        if(strip) { while(n && Py_UNICODE_ISSPACE(static_cast<unsigned char>(*data))){++data;--n;}
                    while(n && Py_UNICODE_ISSPACE(static_cast<unsigned char>(data[n-1])))--n; }
        if(strip && !n){Py_INCREF(Py_None);return Py_None;}
        return checked(PyUnicode_FromStringAndSize(data,static_cast<Py_ssize_t>(n)));
    }
    size_t count=0, begin=0, finish=0; uint32_t maximum=0, final_maximum=0; bool started=!strip;
    auto inspect=[&](uint32_t cp) {
        if(!started && !Py_UNICODE_ISSPACE(cp)){started=true;begin=count;}
        if(started) maximum=std::max(maximum,cp);
        ++count;
        if(!strip || !Py_UNICODE_ISSPACE(cp)){finish=count;final_maximum=maximum;}
    };
    visit_value(first,inspect); for(auto span:rest) visit_value(span,inspect);
    if(strip && !started){Py_INCREF(Py_None);return Py_None;}
    if(finish-begin>static_cast<size_t>(PY_SSIZE_T_MAX)){PyErr_NoMemory();throw PythonError{};}
    Ref result(checked(PyUnicode_New(static_cast<Py_ssize_t>(finish-begin),final_maximum)));
    const int kind=PyUnicode_KIND(result.p); void* out=PyUnicode_DATA(result.p); size_t index=0;
    auto write=[&](uint32_t cp) { if(index>=begin && index<finish) PyUnicode_WRITE(kind,out,index-begin,cp); ++index; };
    visit_value(first,write); for(auto span:rest) visit_value(span,write);
    return result.release();
}

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
            // A collection during list allocation can run user GC callbacks.
            // Keep the looked-up value alive even if a callback changes dict.
            Py_INCREF(old); Ref old_owner(old);
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
    struct Frame {
        rapidxml::xml_node<char>* node;
        rapidxml::xml_node<char>* child;
        Ref dict;
        ValueSpan first;
        std::vector<ValueSpan> rest;
        Frame(Builder& owner, rapidxml::xml_node<char>* value)
            : node(value), child(value->first_node()),
              first{owner.compact && value->value_size() ? value->value() : nullptr,
                    owner.compact ? value->value_size() : 0, value->value_flags()} {
            for (auto* a = node->first_attribute(); a; a = a->next_attribute()) {
                if (!dict.p) dict.p = checked(PyDict_New());
                Ref text(decode_value({a->value(),a->value_size(),a->value_flags()}, {}, false));
                if (PyDict_SetItem(dict.p, owner.key(a->name(), a->name_size(), true), text.p) < 0)
                    throw PythonError{};
            }
        }
        void append_text(rapidxml::xml_node<char>* value) {
            ValueSpan span{value->value(),value->value_size(),value->value_flags()};
            if (!first.data) first=span; else rest.push_back(span);
        }
        PyObject* finish(Builder& owner) {
            Ref value;
            if (first.data) {
                value.p=decode_value(first,rest,true);
                if(value.p==Py_None){Py_DECREF(value.p);value.p=nullptr;}
            }
            if (dict.p) {
                if (value.p && PyDict_SetItem(dict.p, owner.text_key.p, value.p) < 0) throw PythonError{};
                return dict.release();
            }
            if (value.p) return value.release();
            Py_INCREF(Py_None);
            return Py_None;
        }
    };
    PyObject* build(rapidxml::xml_node<char>* node) {
        // Each frame owns only its completed children. C++ control flow remains
        // iterative at arbitrary XML depth; CPython owns result destruction.
        std::vector<Frame> stack;
        stack.reserve(32);
        stack.emplace_back(*this, node);
        while (!stack.empty()) {
            Frame& frame = stack.back();
            if (frame.child) {
                auto* child = frame.child;
                frame.child = child->next_sibling();
                if (child->type() == rapidxml::node_element) {
                    if (!frame.dict.p) frame.dict.p = checked(PyDict_New());
                    stack.emplace_back(*this, child);
                } else if (child->type() == rapidxml::node_data || child->type() == rapidxml::node_cdata) {
                    frame.append_text(child);
                }
                continue;
            }
            auto* completed_node = frame.node;
            Ref value(frame.finish(*this));
            stack.pop_back();
            if (stack.empty()) return value.release();
            put(stack.back().dict.p, element_key(completed_node), value.p);
        }
        PyErr_SetString(PyExc_RuntimeError, "empty native conversion stack");
        throw PythonError{};
    }
};

#include "native_events_binding.hpp"
#include "native_mapping.hpp"

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
    Py_ssize_t input_size=0;
    const char* source=nullptr;
    if(PyBytes_Check(input)){source=PyBytes_AS_STRING(input);input_size=PyBytes_GET_SIZE(input);}
    else if(PyUnicode_Check(input)){source=PyUnicode_AsUTF8AndSize(input,&input_size);if(!source)return nullptr;}
    else {PyErr_SetString(PyExc_TypeError,"internal converter requires str or bytes");return nullptr;}
    const size_t size=static_cast<size_t>(input_size);
    // The borrowed input argument owns every DOM span throughout conversion.
    try {
        // Strict checks execute during RapidXML token consumption. Validated
        // raw spans are normalized directly into final Python strings below.
        // The bounded parser distinguishes embedded NUL from EOF.
        auto doc = std::make_unique<rapidxml::xml_document<char>>();
        doc->parse_readonly<rapidxml::parse_strict | rapidxml::parse_no_string_terminators |
                   rapidxml::parse_compact_data>(source, size);
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
          set_dom_error(error.what(), error.code, source, size, source, error.where<char>());
          return nullptr;
      }
      catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
      catch (const rapidxml::parse_error& error) {
          set_dom_error(error.what(), 4, source, size, source, error.where<char>());
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
    if (add_event_parser(result) < 0 || add_mapping_parser(result) < 0) { Py_DECREF(result); return nullptr; }
    return result;
}
