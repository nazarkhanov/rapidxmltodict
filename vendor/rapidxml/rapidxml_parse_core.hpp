#ifndef RAPIDXML_PARSE_CORE_HPP_INCLUDED
#define RAPIDXML_PARSE_CORE_HPP_INCLUDED

// Project extension for rapidxmltodict; Copyright (c) 2026 Alisher Nazarkhanov.
// Distributed under the repository's MIT license (see ../../LICENSE).
// Consuming XML element-header grammar shared by xml_document and xml_stream.
// Offsets, rather than pointers, survive an incremental input buffer growing.
// Receivers materialize either in-place DOM attributes or owned event values;
// neither receiver scans an attribute again to validate or decode it.
#include "rapidxml_lexical.hpp"
#include <array>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>

namespace rapidxml { namespace internal {
struct header_error : std::runtime_error {
    int code;
    size_t offset;
    header_error(const char* m, int c, size_t at) : std::runtime_error(m), code(c), offset(at) {}
};
inline bool xml_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
inline size_t encode_scalar(char* out, uint32_t c) {
    if (c < 0x80) { out[0] = static_cast<char>(c); return 1; }
    if (c < 0x800) { out[0] = static_cast<char>(0xc0 | (c >> 6)); out[1] = static_cast<char>(0x80 | (c & 63)); return 2; }
    if (c < 0x10000) { out[0] = static_cast<char>(0xe0 | (c >> 12)); out[1] = static_cast<char>(0x80 | ((c >> 6) & 63)); out[2] = static_cast<char>(0x80 | (c & 63)); return 3; }
    out[0] = static_cast<char>(0xf0 | (c >> 18)); out[1] = static_cast<char>(0x80 | ((c >> 12) & 63)); out[2] = static_cast<char>(0x80 | ((c >> 6) & 63)); out[3] = static_cast<char>(0x80 | (c & 63)); return 4;
}
inline bool builtin_reference(std::string_view ref, char& value) {
    if (ref == "amp") value = '&';
    else if (ref == "lt") value = '<';
    else if (ref == "gt") value = '>';
    else if (ref == "apos") value = '\'';
    else if (ref == "quot") value = '"';
    else return false;
    return true;
}

// The parser consumes a header once, including partial UTF-8, attribute values
// and references. parse() receives the same token prefix followed by new bytes.
// A receiver must not retain views across calls. No document node is allocated
// here and no user callback is invoked before the complete header is accepted.
class element_header_parser {
    enum stage { initial, element_name_start, element_name, between_attributes,
                 attribute_name_start, attribute_name, equals, quote, value,
                 reference_start, reference_name, reference_digits_start,
                 reference_digits, empty_end, done } stage_ = initial;
    struct span { size_t begin, length; };
    size_t at_ = 0, start_ = 0, reference_ = 0, attributes_ = 0;
    std::array<span, 8> names_{};
    std::unordered_set<std::string> many_names_;
    bool closing_ = false, empty_ = false, separated_ = false, previous_cr_ = false;
    char quote_ = 0;
    uint32_t reference_value_ = 0;
    unsigned reference_base_ = 10;
    size_t reference_digits_ = 0;
    std::string pending_message_;
    int pending_code_ = 0;
    size_t pending_offset_ = 0;

    [[noreturn]] static void invalid(size_t at = 0) { throw header_error("not well-formed (invalid token)", 4, at); }
    size_t scalar(std::string_view s, uint32_t& cp, bool final) const {
        const char* error;
        const int n = lexical::decode(s.data() + at_, s.data() + s.size(), cp, error);
        if (n == -6 && !final) return 0;
        if (n < 0) throw header_error(n == -6 ? "partial character" : "not well-formed (invalid token)", -n, static_cast<size_t>(error - s.data()));
        return static_cast<size_t>(n);
    }
    void duplicate(std::string_view s) {
        const auto name = s.substr(start_, at_ - start_);
        if (attributes_ < names_.size()) {
            for (size_t j = 0; j < attributes_; ++j)
                if (s.substr(names_[j].begin, names_[j].length) == name)
                    throw header_error("duplicate attribute", 8, start_);
            names_[attributes_] = {start_, at_ - start_};
        } else {
            if (attributes_ == names_.size())
                for (const auto& old : names_) many_names_.emplace(s.substr(old.begin, old.length));
            if (!many_names_.emplace(name).second) throw header_error("duplicate attribute", 8, start_);
        }
        ++attributes_;
    }
    bool recover(std::string_view s, bool final) {
        // Preserve complete-token error timing for incremental callers. Only
        // malformed input takes this recovery path; valid tokens never rescan.
        while (at_ < s.size()) {
            char c = s[at_++];
            if (quote_) { if (c == quote_) quote_ = 0; }
            else if (c == '\'' || c == '"') quote_ = c;
            else if (c == '>') { stage_ = done; throw header_error(pending_message_.c_str(), pending_code_, pending_offset_); }
        }
        if (final) throw header_error("unclosed token", 5, 0);
        return false;
    }
public:
    size_t consumed() const noexcept { return at_; }
    bool self_closing() const noexcept { return empty_; }
    bool closing() const noexcept { return closing_; }
    bool complete() const noexcept { return stage_ == done; }
    void reset() { *this = element_header_parser(); }

    template<class Receiver>
    bool parse(std::string_view s, bool final, Receiver& receiver, bool defer_errors = false) {
        if (!pending_message_.empty()) return recover(s, final);
        try {
            while (at_ < s.size()) {
                switch (stage_) {
                case initial:
                    if (s[at_] != '<') invalid(at_);
                    if (s.size() - at_ < 2) { if (final) throw header_error("unclosed token", 5, 0); return false; }
                    closing_ = s[at_ + 1] == '/';
                    at_ += closing_ ? 2 : 1; stage_ = element_name_start; break;
                case element_name_start:
                case attribute_name_start: {
                    uint32_t cp; size_t n = scalar(s, cp, final); if (!n) return false;
                    if (!lexical::name_start(cp)) invalid(at_);
                    start_ = at_; at_ += n;
                    stage_ = stage_ == element_name_start ? element_name : attribute_name;
                    break;
                }
                case element_name:
                case attribute_name: {
                    uint32_t cp; size_t n = scalar(s, cp, final); if (!n) return false;
                    if (lexical::name_char(cp)) { at_ += n; break; }
                    if (stage_ == element_name) {
                        receiver.element_name(s.substr(start_, at_ - start_), start_);
                        separated_ = false; stage_ = between_attributes;
                    } else {
                        duplicate(s); receiver.attribute_name(s.substr(start_, at_ - start_), start_);
                        stage_ = equals;
                    }
                    break;
                }
                case between_attributes:
                    if (xml_space(s[at_])) { separated_ = true; ++at_; break; }
                    if (s[at_] == '>') { ++at_; stage_ = done; return true; }
                    if (!closing_ && s[at_] == '/') { ++at_; stage_ = empty_end; break; }
                    if (closing_ || !separated_) invalid(at_);
                    stage_ = attribute_name_start; break;
                case equals:
                    if (xml_space(s[at_])) { ++at_; break; }
                    if (s[at_] != '=') invalid(at_ + 1);
                    ++at_; stage_ = quote; break;
                case quote:
                    if (xml_space(s[at_])) { ++at_; break; }
                    if (s[at_] != '\'' && s[at_] != '"') invalid(at_);
                    quote_ = s[at_++]; previous_cr_ = false; receiver.attribute_begin(at_); stage_ = value; break;
                case value: {
                    if (s[at_] == quote_) {
                        ++at_; quote_ = 0; receiver.attribute_end(); separated_ = false; stage_ = between_attributes; break;
                    }
                    if (s[at_] == '<') invalid();
                    if (s[at_] == '&') { reference_ = ++at_; previous_cr_ = false; stage_ = reference_start; break; }
                    // Copy an ordinary ASCII run once. Its lexical checks
                    // happen here, in the same consuming grammar as UTF-8.
                    const size_t run = at_;
                    while (at_ < s.size()) {
                        const unsigned char c = static_cast<unsigned char>(s[at_]);
                        if (c < 0x20 || c >= 0x80 || c == '&' || c == '<' || c == static_cast<unsigned char>(quote_)) break;
                        ++at_;
                    }
                    if (at_ != run) {
                        receiver.attribute_character(s.data() + run, at_ - run); previous_cr_ = false; break;
                    }
                    uint32_t cp; const size_t n = scalar(s, cp, final); if (!n) return false;
                    if (cp == '\r' || cp == '\n' || cp == '\t') {
                        if (!(cp == '\n' && previous_cr_)) receiver.attribute_character(" ", 1);
                        previous_cr_ = cp == '\r';
                    } else { receiver.attribute_character(s.data() + at_, n); previous_cr_ = false; }
                    at_ += n; break;
                }
                case reference_start:
                    if (s[at_] == '#') { ++at_; reference_value_ = 0; reference_base_ = 10; reference_digits_ = 0; stage_ = reference_digits_start; }
                    else {
                        uint32_t cp; const size_t n = scalar(s, cp, final); if (!n) return false;
                        if (!lexical::name_start(cp)) invalid();
                        at_ += n; stage_ = reference_name;
                    }
                    break;
                case reference_name:
                    if (s[at_] == ';') {
                        const auto ref = s.substr(reference_, at_ - reference_); char builtin;
                        if (builtin_reference(ref, builtin)) receiver.attribute_character(&builtin, 1);
                        else receiver.attribute_reference(ref, reference_ - 1);
                        ++at_; stage_ = value;
                    } else {
                        uint32_t cp; const size_t n = scalar(s, cp, final); if (!n) return false;
                        if (!lexical::name_char(cp)) invalid();
                        at_ += n;
                    }
                    break;
                case reference_digits_start:
                    if (s[at_] == 'x') { reference_base_ = 16; ++at_; }
                    stage_ = reference_digits; break;
                case reference_digits: {
                    if (s[at_] == ';') {
                        if (!reference_digits_) invalid();
                        if (!lexical::xml_char(reference_value_)) throw header_error("reference to invalid character number", 14, 0);
                        char encoded[4]; const size_t n = encode_scalar(encoded, reference_value_);
                        receiver.attribute_character(encoded, n); ++at_; stage_ = value; break;
                    }
                    const char c = s[at_]; unsigned digit;
                    if (c >= '0' && c <= '9') digit = static_cast<unsigned>(c - '0');
                    else if (reference_base_ == 16 && c >= 'a' && c <= 'f') digit = static_cast<unsigned>(c - 'a' + 10);
                    else if (reference_base_ == 16 && c >= 'A' && c <= 'F') digit = static_cast<unsigned>(c - 'A' + 10);
                    else invalid();
                    if (reference_value_ > (0x10ffff - digit) / reference_base_) throw header_error("reference to invalid character number", 14, 0);
                    reference_value_ = reference_value_ * reference_base_ + digit; ++reference_digits_; ++at_; break;
                }
                case empty_end:
                    if (s[at_] != '>') invalid(at_);
                    ++at_; empty_ = true; stage_ = done; return true;
                case done: return true;
                }
            }
            if (final) throw header_error("unclosed token", 5, 0);
            return false;
        } catch (const header_error& error) {
            if (!defer_errors || error.code == 5) throw;
            pending_message_ = error.what(); pending_code_ = error.code; pending_offset_ = error.offset;
            return recover(s, final);
        }
    }
};
} } // namespace rapidxml::internal
#endif
