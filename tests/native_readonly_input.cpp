// Linux read-only input, bounded-span and normalization-metadata regression.
// Project test only; not part of the runtime package.
#include <rapidxml/rapidxml.hpp>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <sys/mman.h>
#include <unistd.h>

using namespace rapidxml;
std::string_view value(xml_base<char>* node) { return {node->value(), node->value_size()}; }
void run(const std::string& input) {
    const size_t pagesize = size_t(sysconf(_SC_PAGESIZE));
    const size_t usable = ((input.size()+pagesize-1)/pagesize)*pagesize;
    void* mem = mmap(nullptr, usable+pagesize, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    assert(mem != MAP_FAILED);
    char* start = static_cast<char*>(mem) + usable - input.size();
    std::memcpy(start,input.data(),input.size());
    assert(mprotect(mem,usable,PROT_READ)==0);
    assert(mprotect(static_cast<char*>(mem)+usable,pagesize,PROT_NONE)==0);
    xml_document<> doc;
    doc.parse_readonly<parse_compact_data|parse_comment_nodes|parse_pi_nodes|parse_declaration_node>(start,input.size());
    assert(std::memcmp(start,input.data(),input.size())==0);
    munmap(mem,usable+pagesize);
}
int main() {
    static_assert(sizeof(xml_base<>) == 5*sizeof(void*));
    static_assert(sizeof(xml_node<>) == 96);
    static_assert(sizeof(xml_attribute<>) == 56);
    const char* input = "<?xml version='1.0'?><r a='x\r\n\t&#13;&amp;&#x1F642;'>one&amp;two\r\n<![CDATA[x&foo;\r\ny]]><q/>tail&#xE9;<!--c&\r\nx--><?pi x&\r\ny?></r>";
    xml_document<> doc;
    doc.parse_readonly<parse_compact_data|parse_comment_nodes|parse_pi_nodes|parse_declaration_node>(input,std::strlen(input));
    auto* root=doc.first_node()->next_sibling();
    assert(root->type()==node_element);
    assert(value(root)=="one&amp;two\r\n");
    assert(root->value_flags()==(value_has_references|value_normalize_lines));
    auto* a=root->first_attribute();
    assert(value(a)=="x\r\n\t&#13;&amp;&#x1F642;");
    assert(a->value_flags()==15);
    auto* c=root->first_node();
    assert(c->type()==node_cdata);
    assert(value(c)=="x&foo;\r\ny");
    assert(c->value_flags()==value_normalize_lines);
    c=c->next_sibling()->next_sibling();
    assert(value(c)=="tail&#xE9;");
    assert(c->value_flags()==(value_has_references|value_non_ascii));
    c=c->next_sibling();
    assert(value(c)=="c&\r\nx" && c->value_flags()==value_normalize_lines);
    c=c->next_sibling();
    assert(value(c)=="x&\r\ny" && c->value_flags()==value_normalize_lines);
    run(input);
    for (std::string s : {"<r/>", "<r>é</r>", "<r a=''/>", "<r><![CDATA[&amp;]]>&lt;</r>", "<r><!--x\r\ny--></r>", "<?xml version='1.0'?><r/>"}) run(s);
    std::string deep;
    for (int i=0;i<12000;++i) deep += "<r a='&#x100;'>x\r\n";
    for (int i=0;i<12000;++i) deep += "</r>";
    run(deep);
    std::string mut(input);
    xml_document<> mutable_doc;
    mutable_doc.parse<parse_strict|parse_compact_data|parse_no_string_terminators>(mut.data(),mut.size());
    assert(value(mutable_doc.first_node())=="one&two\n");
    assert(value(mutable_doc.first_node()->first_attribute())=="x  \r&🙂");
    assert(mutable_doc.first_node()->value_flags()==0);
    std::cout << "Read-only, guard-page, deep, metadata, and mutable checks passed\n";
}
