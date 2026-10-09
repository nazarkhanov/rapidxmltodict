#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <rapidxml/rapidxml.hpp>
#include "rapidxml_events.hpp"
#include "native_fast_validation.hpp"
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

// Check the nesting limit without recursion, before entering RapidXML's parser.
// Input to this private routine has already been validated by the native validator.
bool xml_space(char c) { return c==' ' || c=='\t' || c=='\r' || c=='\n'; }
bool shallow(const char* s, size_t n, bool& compact) {
    size_t i = 0, depth = 0, data_start = 0;
    bool text[257] = {}, gap[257] = {};
    while (i < n) {
        if (s[i++] != '<') continue;
        // The preserved RapidXML fork drops whitespace-only data segments.
        // They are insignificant in element-only content after xmltodict's
        // strip(), but must not be lost in mixed content: delegate that case.
        if (depth && i-1 > data_start) {
            bool nonspace=false;
            for(size_t j=data_start;j<i-1;++j) if(!xml_space(s[j])) {nonspace=true;break;}
            if(nonspace) { if(text[depth]) compact=false; text[depth]=true; }
            else gap[depth]=true;
            if(text[depth] && gap[depth]) return false;
        }
        if (i + 2 < n && !std::memcmp(s+i, "!--", 3)) {
            const char* e = std::strstr(s+i+3, "-->");
            if (!e) return false;
            i = static_cast<size_t>(e-s)+3; data_start=i; continue;
        }
        if (i + 7 < n && !std::memcmp(s+i, "![CDATA[", 8)) {
            compact=false;  // CDATA and split character data require full DOM nodes.
            const char* e = std::strstr(s+i+8, "]]>");
            if (!e) return false;
            if(depth) {
                for(const char* p=s+i+8;p<e;++p) if(!xml_space(*p)) {text[depth]=true;break;}
                if(text[depth] && gap[depth]) return false;
            }
            i = static_cast<size_t>(e-s)+3; data_start=i; continue;
        }
        if (i < n && s[i] == '?') {
            const char* e = std::strstr(s+i+1, "?>");
            if (!e) return false;
            i = static_cast<size_t>(e-s)+2; data_start=i; continue;
        }
        if (i == n || s[i] == '!') return false;
        bool closing = s[i] == '/';
        char quote = 0;
        size_t end = i;
        for (; end < n; ++end) {
            char c = s[end];
            if (quote) { if (c == quote) quote = 0; }
            else if (c == '\'' || c == '"') quote = c;
            else if (c == '>') break;
        }
        if (end == n) return false;
        if (closing) { if (!depth) return false; --depth; }
        else {
            if (depth + 1 > 256) return false;
            if (end == 0 || s[end-1] != '/') {++depth; text[depth]=gap[depth]=false;}
        }
        i = end+1; data_start=i;
    }
    return depth == 0;
}

// XML 1.0 literal line endings normalize before entity expansion. Attribute
// literals also normalize whitespace, whereas numeric references retain it.
void normalize(std::vector<char>& b) {
    size_t r=0, w=0, n=b.size()-1;
    while (r<n) {
        char c=b[r++];
        if(c=='\r') { if(r<n && b[r]=='\n') ++r; c='\n'; }
        b[w++]=c;
    }
    b[w]=0; b.resize(w+1);
    n=w;
    for(size_t i=0; i<n;) {
        if(b[i++]!='<') continue;
        if(i<n && b[i]=='!') {
            const char* term=(i+7<n && !std::memcmp(b.data()+i,"![CDATA[",8)) ? "]]>" : "-->";
            const char* e=std::strstr(b.data()+i,term);
            if(!e) return;
            i=static_cast<size_t>(e-b.data())+3; continue;
        }
        if(i<n && b[i]=='?') {
            const char* e=std::strstr(b.data()+i,"?>");
            if(!e) return;
            i=static_cast<size_t>(e-b.data())+2; continue;
        }
        char quote=0;
        for(;i<n;++i) {
            char c=b[i];
            if(quote) { if(c==quote) quote=0; else if(c=='\n'||c=='\t') b[i]=' '; }
            else if(c=='\''||c=='"') quote=c;
            else if(c=='>') {++i;break;}
        }
    }
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

PyObject* convert(PyObject*, PyObject* input) {
    if(!PyBytes_Check(input)) {PyErr_SetString(PyExc_TypeError,"internal converter requires bytes");return nullptr;}
    const char* s=PyBytes_AS_STRING(input); const size_t n=PyBytes_GET_SIZE(input);
    bool compact=true;
    if(std::memchr(s,0,n) || !shallow(s,n,compact)) {Py_INCREF(Py_NotImplemented);return Py_NotImplemented;}
    try {
        std::vector<char> buffer(s,s+n+1);
        normalize(buffer);
        // Heap allocate: RapidXML's inline pool is large; never put it on the
        // Python thread stack. Its destructor frees every dynamically grown pool.
        auto doc=std::make_unique<rapidxml::xml_document<char>>();
        // Simple scalar content can use each element's existing value span
        // instead of allocating a separate DOM data node for every leaf.
        if(compact) doc->parse<rapidxml::parse_no_string_terminators | rapidxml::parse_no_data_nodes>(buffer.data());
        else doc->parse<rapidxml::parse_no_string_terminators>(buffer.data());
        Builder builder(compact);
        Ref result(checked(PyDict_New()));
        for(auto* node=doc->first_node();node;node=node->next_sibling()) {
            if(node->type()!=rapidxml::node_element) continue;
            Ref value(builder.build(node));
            builder.put(result.p,builder.element_key(node),value.p);
        }
        return result.release();
    } catch(const PythonError&) {return nullptr;}
      catch(const std::bad_alloc&) {return PyErr_NoMemory();}
      catch(const rapidxml::parse_error& e) {PyErr_SetString(PyExc_ValueError,e.what());return nullptr;}
      catch(const std::exception& e) {PyErr_SetString(PyExc_RuntimeError,e.what());return nullptr;}
}
#include "native_events_binding.hpp"

PyMethodDef methods[]={{"validate", reinterpret_cast<PyCFunction>(validate_xml), METH_VARARGS | METH_KEYWORDS, "Validate XML with the native incremental parser."},{"convert",convert,METH_O,"Private converter; caller must first validate XML with the native validator."},{nullptr,nullptr,0,nullptr}};
PyModuleDef module={PyModuleDef_HEAD_INIT,"_native",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
}
PyMODINIT_FUNC PyInit__native() {
    PyObject* result = PyModule_Create(&module);
    if (!result) return nullptr;
    if (add_event_parser(result) < 0) { Py_DECREF(result); return nullptr; }
    return result;
}
