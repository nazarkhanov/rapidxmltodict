#ifndef RAPIDXMLTODICT_ASCII_HPP
#define RAPIDXMLTODICT_ASCII_HPP

// Allocation-light validator for the common ASCII subset. A false result means
// the complete incremental validator must run; it does not mean invalid XML.
// In particular, no unsupported declaration, entity, or Unicode input is ever
// accepted here. This validates syntax only; conversion still uses RapidXML.
#include <array>
#include <cstdint>
#include <cstring>
#include <string_view>
#include <vector>

namespace rapidxml_fast {
namespace ascii_detail {
inline bool space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
inline bool literal(unsigned char c) { return (c >= 0x20 && c < 0x80) || c == 9 || c == 10 || c == 13; }
inline bool initial(unsigned char c) { return c == ':' || c == '_' || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); }
inline bool subsequent(unsigned char c) { return initial(c) || (c >= '0' && c <= '9') || c == '-' || c == '.'; }
inline size_t whitespace(std::string_view s, size_t i) { while (i < s.size() && space(s[i])) ++i; return i; }
inline std::string_view name(std::string_view s, size_t& i) {
    const size_t start = i;
    if (i == s.size() || !initial(static_cast<unsigned char>(s[i]))) return {};
    do { ++i; } while (i < s.size() && subsequent(static_cast<unsigned char>(s[i])));
    return s.substr(start, i - start);
}
inline bool reference(std::string_view s, size_t& i) {
    const size_t start = ++i;
    if (i < s.size() && s[i] == '#') {
        ++i; uint32_t value = 0, base = 10;
        if (i < s.size() && s[i] == 'x') { ++i; base = 16; }
        const size_t digits = i;
        for (; i < s.size() && s[i] != ';'; ++i) {
            const unsigned char c = static_cast<unsigned char>(s[i]); unsigned digit;
            if (c >= '0' && c <= '9') digit = c - '0';
            else if (base == 16 && c >= 'a' && c <= 'f') digit = c - 'a' + 10;
            else if (base == 16 && c >= 'A' && c <= 'F') digit = c - 'A' + 10;
            else return false;
            if (value > (0x10ffff - digit) / base) return false;
            value = value * base + digit;
        }
        if (i == digits || i == s.size()) return false;
        if (!(value == 9 || value == 10 || value == 13 || (value >= 0x20 && value <= 0xd7ff) || (value >= 0xe000 && value <= 0xfffd) || (value >= 0x10000 && value <= 0x10ffff))) return false;
    } else {
        while (i < s.size() && s[i] != ';' && i - start <= 4) ++i;
        if (i == s.size() || s[i] != ';') return false;
        auto key = s.substr(start, i - start);
        if (key != "amp" && key != "lt" && key != "gt" && key != "apos" && key != "quot") return false;
    }
    ++i; return true;
}
inline bool declaration(std::string_view s, size_t begin, size_t end) {
    size_t i = begin; int stage = 0;
    while (i < end) {
        size_t next = whitespace(s, i); if (next == i) return false; i = next;
        if (i == end) break;
        auto key = name(s, i); if (key.empty()) return false;
        i = whitespace(s, i); if (i >= end || s[i++] != '=') return false;
        i = whitespace(s, i); if (i >= end || (s[i] != '\'' && s[i] != '"')) return false;
        char quote = s[i++]; size_t start = i;
        while (i < end && s[i] != quote) ++i;
        if (i == end) return false;
        auto value = s.substr(start, i++ - start);
        if (stage == 0 && key == "version") {
            if (value.empty()) return false;
            for (unsigned char c : value) if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return false;
            stage = 1;
        } else if (stage == 1 && key == "encoding") {
            if (value.empty() || !((value[0] >= 'A' && value[0] <= 'Z') || (value[0] >= 'a' && value[0] <= 'z'))) return false;
            for (unsigned char c : value) if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return false;
            stage = 2;
        } else if ((stage == 1 || stage == 2) && key == "standalone" && (value == "yes" || value == "no")) stage = 3;
        else return false;
    }
    return stage != 0;
}
} // namespace ascii_detail

inline bool validate_ascii_subset(const char* input, size_t length) {
    using namespace ascii_detail;
    const std::string_view s(input, length);
    std::vector<std::string_view> stack;
    stack.reserve(32);
    bool root = false;
    size_t i = 0;
    while (i < length) {
        if (s[i] != '<') {
            while (i < length && s[i] != '<') {
                const unsigned char c = static_cast<unsigned char>(s[i]);
                if (!literal(c)) return false;
                if (stack.empty()) { if (!space(static_cast<char>(c))) return false; ++i; continue; }
                if (c == '&') { if (!reference(s, i)) return false; }
                else { if (c == ']' && s.substr(i, 3) == "]]>") return false; ++i; }
            }
            continue;
        }
        const size_t markup = i;
        if (s.substr(i, 4) == "<!--") {
            i += 4;
            while (i < length && s.substr(i, 2) != "--") { if (!literal(static_cast<unsigned char>(s[i]))) return false; ++i; }
            if (s.substr(i, 3) != "-->") return false;
            i += 3; continue;
        }
        if (s.substr(i, 9) == "<![CDATA[") {
            if (stack.empty()) return false;
            i += 9;
            while (i < length && s.substr(i, 3) != "]]>") { if (!literal(static_cast<unsigned char>(s[i]))) return false; ++i; }
            if (i == length) return false;
            i += 3; continue;
        }
        if (s.substr(i, 2) == "<?") {
            i += 2; auto target = name(s, i); if (target.empty()) return false;
            if (s.substr(i, 2) != "?>" && (i == length || !space(s[i]))) return false;
            const size_t value = i;
            while (i < length && s.substr(i, 2) != "?>") { if (!literal(static_cast<unsigned char>(s[i]))) return false; ++i; }
            if (i == length) return false;
            const bool reserved = target.size() == 3 && (target[0] == 'x' || target[0] == 'X') && (target[1] == 'm' || target[1] == 'M') && (target[2] == 'l' || target[2] == 'L');
            if (reserved && (target != "xml" || markup != 0 || !declaration(s, value, i))) return false;
            i += 2; continue;
        }
        if (s.substr(i, 2) == "</") {
            i += 2; auto tag = name(s, i); if (tag.empty() || stack.empty() || stack.back() != tag) return false;
            i = whitespace(s, i); if (i == length || s[i++] != '>') return false;
            stack.pop_back(); continue;
        }
        ++i; auto tag = name(s, i); if (tag.empty()) return false;
        if (stack.empty()) { if (root) return false; root = true; }
        std::array<std::string_view, 8> names;
        size_t attributes = 0;
        bool empty = false;
        for (;;) {
            const size_t before = i; i = whitespace(s, i);
            if (i == length) return false;
            if (s[i] == '>') { ++i; break; }
            if (s.substr(i, 2) == "/>") { i += 2; empty = true; break; }
            if (i == before || attributes == names.size()) return false;
            auto key = name(s, i); if (key.empty()) return false;
            for (size_t j = 0; j < attributes; ++j) if (names[j] == key) return false;
            names[attributes++] = key;
            i = whitespace(s, i); if (i == length || s[i++] != '=') return false;
            i = whitespace(s, i); if (i == length || (s[i] != '\'' && s[i] != '"')) return false;
            const char quote = s[i++];
            while (i < length && s[i] != quote) {
                const unsigned char c = static_cast<unsigned char>(s[i]);
                if (!literal(c) || c == '<') return false;
                if (c == '&') { if (!reference(s, i)) return false; }
                else ++i;
            }
            if (i == length) return false;
            ++i;
        }
        if (!empty) stack.push_back(tag);
    }
    return root && stack.empty();
}
} // namespace rapidxml_fast
#endif
