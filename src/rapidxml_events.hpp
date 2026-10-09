#ifndef RAPIDXMLTODICT_EVENTS_HPP
#define RAPIDXMLTODICT_EVENTS_HPP

// Incremental XML 1.0 event adapter for the vendored RapidXML tokenizer.
// Only a single opening-tag token is made into a RapidXML DOM. Completed input
// is discarded after each feed; element names and DTD declarations are retained.
#include <rapidxml/rapidxml.hpp>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace rapidxml_events {
using Attributes = std::vector<std::pair<std::string, std::string>>;
struct Error : std::runtime_error {
    int code;
    size_t line, column, byte_index;
    Error(const char* message, int c, size_t l, size_t col, size_t index)
        : std::runtime_error(message), code(c), line(l), column(col), byte_index(index) {}
};
struct EntitiesDisabled : std::runtime_error {
    EntitiesDisabled() : std::runtime_error("entities are disabled") {}
};
struct Sink {
    virtual ~Sink() = default;
    virtual void start(const std::string&, const Attributes&) = 0;
    virtual void end(const std::string&) = 0;
    virtual void text(const std::string&) = 0;
    virtual void comment(const std::string&) = 0;
};

class Parser {
    struct Entity { std::string value; bool external = false, unparsed = false; };
    struct AttributeDecl { std::string name, value; bool has_default = false, tokenized = false; };
    Sink& sink_;
    bool disable_entities_, process_comments_, validation_only_, final_ = false;
    std::unique_ptr<rapidxml::xml_document<char>> token_document_;
    bool root_seen_ = false, doctype_seen_ = false, declaration_allowed_ = true;
    bool external_subset_ = false, unread_parameter_ = false, standalone_ = false;
    bool in_entity_ = false, cdata_mode_ = false;
    size_t retry_after_ = 0;
    int source_width_ = 0;
    size_t previous_undecoded_ = 0;
    int dtd_mode_ = 0; // 1: header, 2: internal subset, 3: closing delimiter
    std::string dtd_token_;
    std::string buffer_, text_;
    size_t pos_ = 0, line_ = 1, column_ = 0, byte_index_ = 0;
    size_t source_bytes_ = 0, expanded_bytes_ = 0;
    bool previous_cr_ = false;
    std::vector<std::string> stack_, entity_stack_;
    struct EntityFrame { std::string input; size_t position, depth, line, column, byte_index; bool was_entity, previous_cr; };
    std::vector<EntityFrame> entity_frames_;
    std::unordered_map<std::string, Entity> entities_;
    std::unordered_map<std::string, std::vector<AttributeDecl>> attribute_decls_;
    static constexpr size_t text_buffer_size = 8192;

    [[noreturn]] void fail(const char* message, int code = 4, size_t relative = 0) const {
        size_t l = line_, col = column_, index = byte_index_;
        bool cr = previous_cr_;
        const size_t finish = std::min(buffer_.size(), pos_ + relative);
        for (size_t i = pos_; i < finish; ++i) {
            unsigned char ch = static_cast<unsigned char>(buffer_[i]);
            ++index;
            if (ch == '\r') { ++l; col = 0; cr = true; }
            else if (ch == '\n') { if (!cr) ++l; col = 0; cr = false; }
            else { if ((ch & 0xc0) != 0x80) ++col; cr = false; }
        }
        throw Error(message, code, l, col, index);
    }
    static bool space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
    static bool xml_char(uint32_t c) {
        return c == 9 || c == 10 || c == 13 || (c >= 0x20 && c <= 0xd7ff) ||
               (c >= 0xe000 && c <= 0xfffd) || (c >= 0x10000 && c <= 0x10ffff);
    }
    // XML 1.0 fourth-edition Name productions, also used by xmltodict's
    // reference parser. Static ranges are verified by test-only oracle checks.
    struct NameRange { uint16_t low, high; };
    template<size_t N> static bool in_ranges(uint32_t cp, const NameRange (&ranges)[N]) {
        size_t low = 0, high = N;
        while (low < high) { size_t mid = low + (high - low) / 2;
            if (cp < ranges[mid].low) high = mid;
            else if (cp > ranges[mid].high) low = mid + 1;
            else return true;
        }
        return false;
    }
    static bool name_start(uint32_t c) {
        if (c < 0x80) return c == ':' || c == '_' || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
        static constexpr NameRange ranges[] = {
            {0x003a,0x003a}, {0x0041,0x005a}, {0x005f,0x005f}, {0x0061,0x007a}, {0x00c0,0x00d6}, {0x00d8,0x00f6},
            {0x00f8,0x0131}, {0x0134,0x013e}, {0x0141,0x0148}, {0x014a,0x017e}, {0x0180,0x01c3}, {0x01cd,0x01f0},
            {0x01f4,0x01f5}, {0x01fa,0x0217}, {0x0250,0x02a8}, {0x02bb,0x02c1}, {0x0386,0x0386}, {0x0388,0x038a},
            {0x038c,0x038c}, {0x038e,0x03a1}, {0x03a3,0x03ce}, {0x03d0,0x03d6}, {0x03da,0x03da}, {0x03dc,0x03dc},
            {0x03de,0x03de}, {0x03e0,0x03e0}, {0x03e2,0x03f3}, {0x0401,0x040c}, {0x040e,0x044f}, {0x0451,0x045c},
            {0x045e,0x0481}, {0x0490,0x04c4}, {0x04c7,0x04c8}, {0x04cb,0x04cc}, {0x04d0,0x04eb}, {0x04ee,0x04f5},
            {0x04f8,0x04f9}, {0x0531,0x0556}, {0x0559,0x0559}, {0x0561,0x0586}, {0x05d0,0x05ea}, {0x05f0,0x05f2},
            {0x0621,0x063a}, {0x0641,0x064a}, {0x0671,0x06b7}, {0x06ba,0x06be}, {0x06c0,0x06ce}, {0x06d0,0x06d3},
            {0x06d5,0x06d5}, {0x06e5,0x06e6}, {0x0905,0x0939}, {0x093d,0x093d}, {0x0958,0x0961}, {0x0985,0x098c},
            {0x098f,0x0990}, {0x0993,0x09a8}, {0x09aa,0x09b0}, {0x09b2,0x09b2}, {0x09b6,0x09b9}, {0x09dc,0x09dd},
            {0x09df,0x09e1}, {0x09f0,0x09f1}, {0x0a05,0x0a0a}, {0x0a0f,0x0a10}, {0x0a13,0x0a28}, {0x0a2a,0x0a30},
            {0x0a32,0x0a33}, {0x0a35,0x0a36}, {0x0a38,0x0a39}, {0x0a59,0x0a5c}, {0x0a5e,0x0a5e}, {0x0a72,0x0a74},
            {0x0a85,0x0a8b}, {0x0a8d,0x0a8d}, {0x0a8f,0x0a91}, {0x0a93,0x0aa8}, {0x0aaa,0x0ab0}, {0x0ab2,0x0ab3},
            {0x0ab5,0x0ab9}, {0x0abd,0x0abd}, {0x0ae0,0x0ae0}, {0x0b05,0x0b0c}, {0x0b0f,0x0b10}, {0x0b13,0x0b28},
            {0x0b2a,0x0b30}, {0x0b32,0x0b33}, {0x0b36,0x0b39}, {0x0b3d,0x0b3d}, {0x0b5c,0x0b5d}, {0x0b5f,0x0b61},
            {0x0b85,0x0b8a}, {0x0b8e,0x0b90}, {0x0b92,0x0b95}, {0x0b99,0x0b9a}, {0x0b9c,0x0b9c}, {0x0b9e,0x0b9f},
            {0x0ba3,0x0ba4}, {0x0ba8,0x0baa}, {0x0bae,0x0bb5}, {0x0bb7,0x0bb9}, {0x0c05,0x0c0c}, {0x0c0e,0x0c10},
            {0x0c12,0x0c28}, {0x0c2a,0x0c33}, {0x0c35,0x0c39}, {0x0c60,0x0c61}, {0x0c85,0x0c8c}, {0x0c8e,0x0c90},
            {0x0c92,0x0ca8}, {0x0caa,0x0cb3}, {0x0cb5,0x0cb9}, {0x0cde,0x0cde}, {0x0ce0,0x0ce1}, {0x0d05,0x0d0c},
            {0x0d0e,0x0d10}, {0x0d12,0x0d28}, {0x0d2a,0x0d39}, {0x0d60,0x0d61}, {0x0e01,0x0e2e}, {0x0e30,0x0e30},
            {0x0e32,0x0e33}, {0x0e40,0x0e45}, {0x0e81,0x0e82}, {0x0e84,0x0e84}, {0x0e87,0x0e88}, {0x0e8a,0x0e8a},
            {0x0e8d,0x0e8d}, {0x0e94,0x0e97}, {0x0e99,0x0e9f}, {0x0ea1,0x0ea3}, {0x0ea5,0x0ea5}, {0x0ea7,0x0ea7},
            {0x0eaa,0x0eab}, {0x0ead,0x0eae}, {0x0eb0,0x0eb0}, {0x0eb2,0x0eb3}, {0x0ebd,0x0ebd}, {0x0ec0,0x0ec4},
            {0x0f40,0x0f47}, {0x0f49,0x0f69}, {0x10a0,0x10c5}, {0x10d0,0x10f6}, {0x1100,0x1100}, {0x1102,0x1103},
            {0x1105,0x1107}, {0x1109,0x1109}, {0x110b,0x110c}, {0x110e,0x1112}, {0x113c,0x113c}, {0x113e,0x113e},
            {0x1140,0x1140}, {0x114c,0x114c}, {0x114e,0x114e}, {0x1150,0x1150}, {0x1154,0x1155}, {0x1159,0x1159},
            {0x115f,0x1161}, {0x1163,0x1163}, {0x1165,0x1165}, {0x1167,0x1167}, {0x1169,0x1169}, {0x116d,0x116e},
            {0x1172,0x1173}, {0x1175,0x1175}, {0x119e,0x119e}, {0x11a8,0x11a8}, {0x11ab,0x11ab}, {0x11ae,0x11af},
            {0x11b7,0x11b8}, {0x11ba,0x11ba}, {0x11bc,0x11c2}, {0x11eb,0x11eb}, {0x11f0,0x11f0}, {0x11f9,0x11f9},
            {0x1e00,0x1e9b}, {0x1ea0,0x1ef9}, {0x1f00,0x1f15}, {0x1f18,0x1f1d}, {0x1f20,0x1f45}, {0x1f48,0x1f4d},
            {0x1f50,0x1f57}, {0x1f59,0x1f59}, {0x1f5b,0x1f5b}, {0x1f5d,0x1f5d}, {0x1f5f,0x1f7d}, {0x1f80,0x1fb4},
            {0x1fb6,0x1fbc}, {0x1fbe,0x1fbe}, {0x1fc2,0x1fc4}, {0x1fc6,0x1fcc}, {0x1fd0,0x1fd3}, {0x1fd6,0x1fdb},
            {0x1fe0,0x1fec}, {0x1ff2,0x1ff4}, {0x1ff6,0x1ffc}, {0x2126,0x2126}, {0x212a,0x212b}, {0x212e,0x212e},
            {0x2180,0x2182}, {0x3007,0x3007}, {0x3021,0x3029}, {0x3041,0x3094}, {0x30a1,0x30fa}, {0x3105,0x312c},
            {0x4e00,0x9fa5}, {0xac00,0xd7a3},
        };
        return in_ranges(c, ranges);
    }
    static bool name_char(uint32_t c) {
        if (c < 0x80) return c == ':' || c == '_' || c == '-' || c == '.' || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
        static constexpr NameRange ranges[] = {
            {0x002d,0x002e}, {0x0030,0x003a}, {0x0041,0x005a}, {0x005f,0x005f}, {0x0061,0x007a}, {0x00b7,0x00b7},
            {0x00c0,0x00d6}, {0x00d8,0x00f6}, {0x00f8,0x0131}, {0x0134,0x013e}, {0x0141,0x0148}, {0x014a,0x017e},
            {0x0180,0x01c3}, {0x01cd,0x01f0}, {0x01f4,0x01f5}, {0x01fa,0x0217}, {0x0250,0x02a8}, {0x02bb,0x02c1},
            {0x02d0,0x02d1}, {0x0300,0x0345}, {0x0360,0x0361}, {0x0386,0x038a}, {0x038c,0x038c}, {0x038e,0x03a1},
            {0x03a3,0x03ce}, {0x03d0,0x03d6}, {0x03da,0x03da}, {0x03dc,0x03dc}, {0x03de,0x03de}, {0x03e0,0x03e0},
            {0x03e2,0x03f3}, {0x0401,0x040c}, {0x040e,0x044f}, {0x0451,0x045c}, {0x045e,0x0481}, {0x0483,0x0486},
            {0x0490,0x04c4}, {0x04c7,0x04c8}, {0x04cb,0x04cc}, {0x04d0,0x04eb}, {0x04ee,0x04f5}, {0x04f8,0x04f9},
            {0x0531,0x0556}, {0x0559,0x0559}, {0x0561,0x0586}, {0x0591,0x05a1}, {0x05a3,0x05b9}, {0x05bb,0x05bd},
            {0x05bf,0x05bf}, {0x05c1,0x05c2}, {0x05c4,0x05c4}, {0x05d0,0x05ea}, {0x05f0,0x05f2}, {0x0621,0x063a},
            {0x0640,0x0652}, {0x0660,0x0669}, {0x0670,0x06b7}, {0x06ba,0x06be}, {0x06c0,0x06ce}, {0x06d0,0x06d3},
            {0x06d5,0x06e8}, {0x06ea,0x06ed}, {0x06f0,0x06f9}, {0x0901,0x0903}, {0x0905,0x0939}, {0x093c,0x094d},
            {0x0951,0x0954}, {0x0958,0x0963}, {0x0966,0x096f}, {0x0981,0x0983}, {0x0985,0x098c}, {0x098f,0x0990},
            {0x0993,0x09a8}, {0x09aa,0x09b0}, {0x09b2,0x09b2}, {0x09b6,0x09b9}, {0x09bc,0x09bc}, {0x09be,0x09c4},
            {0x09c7,0x09c8}, {0x09cb,0x09cd}, {0x09d7,0x09d7}, {0x09dc,0x09dd}, {0x09df,0x09e3}, {0x09e6,0x09f1},
            {0x0a02,0x0a02}, {0x0a05,0x0a0a}, {0x0a0f,0x0a10}, {0x0a13,0x0a28}, {0x0a2a,0x0a30}, {0x0a32,0x0a33},
            {0x0a35,0x0a36}, {0x0a38,0x0a39}, {0x0a3c,0x0a3c}, {0x0a3e,0x0a42}, {0x0a47,0x0a48}, {0x0a4b,0x0a4d},
            {0x0a59,0x0a5c}, {0x0a5e,0x0a5e}, {0x0a66,0x0a74}, {0x0a81,0x0a83}, {0x0a85,0x0a8b}, {0x0a8d,0x0a8d},
            {0x0a8f,0x0a91}, {0x0a93,0x0aa8}, {0x0aaa,0x0ab0}, {0x0ab2,0x0ab3}, {0x0ab5,0x0ab9}, {0x0abc,0x0ac5},
            {0x0ac7,0x0ac9}, {0x0acb,0x0acd}, {0x0ae0,0x0ae0}, {0x0ae6,0x0aef}, {0x0b01,0x0b03}, {0x0b05,0x0b0c},
            {0x0b0f,0x0b10}, {0x0b13,0x0b28}, {0x0b2a,0x0b30}, {0x0b32,0x0b33}, {0x0b36,0x0b39}, {0x0b3c,0x0b43},
            {0x0b47,0x0b48}, {0x0b4b,0x0b4d}, {0x0b56,0x0b57}, {0x0b5c,0x0b5d}, {0x0b5f,0x0b61}, {0x0b66,0x0b6f},
            {0x0b82,0x0b83}, {0x0b85,0x0b8a}, {0x0b8e,0x0b90}, {0x0b92,0x0b95}, {0x0b99,0x0b9a}, {0x0b9c,0x0b9c},
            {0x0b9e,0x0b9f}, {0x0ba3,0x0ba4}, {0x0ba8,0x0baa}, {0x0bae,0x0bb5}, {0x0bb7,0x0bb9}, {0x0bbe,0x0bc2},
            {0x0bc6,0x0bc8}, {0x0bca,0x0bcd}, {0x0bd7,0x0bd7}, {0x0be7,0x0bef}, {0x0c01,0x0c03}, {0x0c05,0x0c0c},
            {0x0c0e,0x0c10}, {0x0c12,0x0c28}, {0x0c2a,0x0c33}, {0x0c35,0x0c39}, {0x0c3e,0x0c44}, {0x0c46,0x0c48},
            {0x0c4a,0x0c4d}, {0x0c55,0x0c56}, {0x0c60,0x0c61}, {0x0c66,0x0c6f}, {0x0c82,0x0c83}, {0x0c85,0x0c8c},
            {0x0c8e,0x0c90}, {0x0c92,0x0ca8}, {0x0caa,0x0cb3}, {0x0cb5,0x0cb9}, {0x0cbe,0x0cc4}, {0x0cc6,0x0cc8},
            {0x0cca,0x0ccd}, {0x0cd5,0x0cd6}, {0x0cde,0x0cde}, {0x0ce0,0x0ce1}, {0x0ce6,0x0cef}, {0x0d02,0x0d03},
            {0x0d05,0x0d0c}, {0x0d0e,0x0d10}, {0x0d12,0x0d28}, {0x0d2a,0x0d39}, {0x0d3e,0x0d43}, {0x0d46,0x0d48},
            {0x0d4a,0x0d4d}, {0x0d57,0x0d57}, {0x0d60,0x0d61}, {0x0d66,0x0d6f}, {0x0e01,0x0e2e}, {0x0e30,0x0e3a},
            {0x0e40,0x0e4e}, {0x0e50,0x0e59}, {0x0e81,0x0e82}, {0x0e84,0x0e84}, {0x0e87,0x0e88}, {0x0e8a,0x0e8a},
            {0x0e8d,0x0e8d}, {0x0e94,0x0e97}, {0x0e99,0x0e9f}, {0x0ea1,0x0ea3}, {0x0ea5,0x0ea5}, {0x0ea7,0x0ea7},
            {0x0eaa,0x0eab}, {0x0ead,0x0eae}, {0x0eb0,0x0eb9}, {0x0ebb,0x0ebd}, {0x0ec0,0x0ec4}, {0x0ec6,0x0ec6},
            {0x0ec8,0x0ecd}, {0x0ed0,0x0ed9}, {0x0f18,0x0f19}, {0x0f20,0x0f29}, {0x0f35,0x0f35}, {0x0f37,0x0f37},
            {0x0f39,0x0f39}, {0x0f3e,0x0f47}, {0x0f49,0x0f69}, {0x0f71,0x0f84}, {0x0f86,0x0f8b}, {0x0f90,0x0f95},
            {0x0f97,0x0f97}, {0x0f99,0x0fad}, {0x0fb1,0x0fb7}, {0x0fb9,0x0fb9}, {0x10a0,0x10c5}, {0x10d0,0x10f6},
            {0x1100,0x1100}, {0x1102,0x1103}, {0x1105,0x1107}, {0x1109,0x1109}, {0x110b,0x110c}, {0x110e,0x1112},
            {0x113c,0x113c}, {0x113e,0x113e}, {0x1140,0x1140}, {0x114c,0x114c}, {0x114e,0x114e}, {0x1150,0x1150},
            {0x1154,0x1155}, {0x1159,0x1159}, {0x115f,0x1161}, {0x1163,0x1163}, {0x1165,0x1165}, {0x1167,0x1167},
            {0x1169,0x1169}, {0x116d,0x116e}, {0x1172,0x1173}, {0x1175,0x1175}, {0x119e,0x119e}, {0x11a8,0x11a8},
            {0x11ab,0x11ab}, {0x11ae,0x11af}, {0x11b7,0x11b8}, {0x11ba,0x11ba}, {0x11bc,0x11c2}, {0x11eb,0x11eb},
            {0x11f0,0x11f0}, {0x11f9,0x11f9}, {0x1e00,0x1e9b}, {0x1ea0,0x1ef9}, {0x1f00,0x1f15}, {0x1f18,0x1f1d},
            {0x1f20,0x1f45}, {0x1f48,0x1f4d}, {0x1f50,0x1f57}, {0x1f59,0x1f59}, {0x1f5b,0x1f5b}, {0x1f5d,0x1f5d},
            {0x1f5f,0x1f7d}, {0x1f80,0x1fb4}, {0x1fb6,0x1fbc}, {0x1fbe,0x1fbe}, {0x1fc2,0x1fc4}, {0x1fc6,0x1fcc},
            {0x1fd0,0x1fd3}, {0x1fd6,0x1fdb}, {0x1fe0,0x1fec}, {0x1ff2,0x1ff4}, {0x1ff6,0x1ffc}, {0x20d0,0x20dc},
            {0x20e1,0x20e1}, {0x2126,0x2126}, {0x212a,0x212b}, {0x212e,0x212e}, {0x2180,0x2182}, {0x3005,0x3005},
            {0x3007,0x3007}, {0x3021,0x302f}, {0x3031,0x3035}, {0x3041,0x3094}, {0x3099,0x309a}, {0x309d,0x309e},
            {0x30a1,0x30fa}, {0x30fc,0x30fe}, {0x3105,0x312c}, {0x4e00,0x9fa5}, {0xac00,0xd7a3},
        };
        return in_ranges(c, ranges);
    }
    // Returns zero for an incomplete sequence when final is false.
    size_t scalar(std::string_view s, size_t at, uint32_t& cp, bool final = true) const {
        const auto b = static_cast<unsigned char>(s[at]);
        size_t n;
        if (b < 0x80) { cp = b; n = 1; }
        else if (b >= 0xc2 && b <= 0xdf) { cp = b & 31; n = 2; }
        else if (b >= 0xe0 && b <= 0xef) { cp = b & 15; n = 3; }
        else if (b >= 0xf0 && b <= 0xf4) { cp = b & 7; n = 4; }
        else fail("not well-formed (invalid token)", 4, at);
        if (s.size() - at < n) {
            if (!final) return 0;
            fail("partial character", 6, at);
        }
        for (size_t j = 1; j < n; ++j) {
            unsigned char v = static_cast<unsigned char>(s[at + j]);
            if ((v & 0xc0) != 0x80) fail("not well-formed (invalid token)", 4, at + j);
            cp = (cp << 6) | (v & 63);
        }
        if ((n == 2 && cp < 0x80) || (n == 3 && cp < 0x800) || (n == 4 && cp < 0x10000) || !xml_char(cp))
            fail("not well-formed (invalid token)", 4, at);
        return n;
    }
    void validate(std::string_view s) const {
        for (size_t i = 0; i < s.size();) { uint32_t c; i += scalar(s, i, c); }
    }
    static void utf8(std::string& s, uint32_t c) {
        if (c < 0x80) s.push_back(static_cast<char>(c));
        else if (c < 0x800) { s.push_back(static_cast<char>(0xc0 | (c >> 6))); s.push_back(static_cast<char>(0x80 | (c & 63))); }
        else if (c < 0x10000) { s.push_back(static_cast<char>(0xe0 | (c >> 12))); s.push_back(static_cast<char>(0x80 | ((c >> 6) & 63))); s.push_back(static_cast<char>(0x80 | (c & 63))); }
        else { s.push_back(static_cast<char>(0xf0 | (c >> 18))); s.push_back(static_cast<char>(0x80 | ((c >> 12) & 63))); s.push_back(static_cast<char>(0x80 | ((c >> 6) & 63))); s.push_back(static_cast<char>(0x80 | (c & 63))); }
    }
    void consume(size_t count) {
        if (!in_entity_) {
            for (size_t i = pos_; i < pos_ + count; ++i) {
                unsigned char c = static_cast<unsigned char>(buffer_[i]);
                ++byte_index_;
                if (c == '\r') { ++line_; column_ = 0; previous_cr_ = true; }
                else if (c == '\n') { if (!previous_cr_) ++line_; column_ = 0; previous_cr_ = false; }
                else { if ((c & 0xc0) != 0x80) ++column_; previous_cr_ = false; }
            }
        }
        pos_ += count;
    }
    static size_t skip_space(std::string_view s, size_t i) { while (i < s.size() && space(s[i])) ++i; return i; }
    size_t require_space(std::string_view s, size_t i) const {
        size_t j = skip_space(s, i); if (j == i) fail("syntax error", 2, i); return j;
    }
    std::string name(std::string_view s, size_t& i, bool nmtoken = false) const {
        const size_t start = i;
        if (i == s.size()) fail("syntax error", 2, i);
        uint32_t c; size_t n = scalar(s, i, c);
        if (!(nmtoken ? name_char(c) : name_start(c))) fail("not well-formed (invalid token)", 4, i);
        i += n;
        while (i < s.size()) {
            n = scalar(s, i, c);
            if (!name_char(c)) break;
            i += n;
        }
        return std::string(s.substr(start, i - start));
    }
    std::string quoted(std::string_view s, size_t& i) const {
        if (i >= s.size() || (s[i] != '\'' && s[i] != '"')) fail("syntax error", 2, i);
        const char q = s[i++]; size_t start = i;
        while (i < s.size() && s[i] != q) ++i;
        if (i == s.size()) fail("unclosed token", 5, start);
        std::string value(s.substr(start, i - start)); ++i; validate(value); return value;
    }
    static std::string normalize(std::string_view s, bool attribute = false) {
        std::string result; result.reserve(s.size());
        for (size_t i = 0; i < s.size(); ++i) {
            char c = s[i];
            if (c == '\r') { if (i + 1 < s.size() && s[i + 1] == '\n') ++i; c = '\n'; }
            if (attribute && (c == '\n' || c == '\t')) c = ' ';
            result.push_back(c);
        }
        return result;
    }
    static void collapse_spaces(std::string& value) {
        size_t w = 0; bool pending = false;
        for (char c : value) {
            if (c == ' ') pending = w != 0;
            else { if (pending) value[w++] = ' '; pending = false; value[w++] = c; }
        }
        value.resize(w);
    }
    void flush_text() {
        if (!text_.empty()) { std::string value; value.swap(text_); sink_.text(value); }
    }
    void append_text(std::string_view value) {
        if (value.empty() || validation_only_) return;
        if (text_.size() + value.size() > text_buffer_size) flush_text();
        if (value.size() > text_buffer_size) sink_.text(std::string(value));
        else text_.append(value.data(), value.size());
    }
    void emit_literal(std::string_view value) {
        if (validation_only_ || value.empty()) return;
        auto piece = [&](std::string_view part) {
            if (!source_width_ || in_entity_) { append_text(part); return; }
            // Non-UTF8 source encodings produce bounded transcoding fragments.
            // Keep complete UTF8 scalars together before applying text buffering.
            while (!part.empty()) {
                size_t length = std::min<size_t>(1024, part.size());
                if (length < part.size()) while (length && (static_cast<unsigned char>(part[length]) & 0xc0) == 0x80) --length;
                append_text(part.substr(0, length)); part.remove_prefix(length);
            }
        };
        size_t start = 0;
        for (size_t i = 0; i < value.size(); ++i) {
            if (value[i] != '\n' && (value[i] != '\r' || in_entity_)) continue;
            piece(value.substr(start, i - start));
            if (in_entity_) append_text(value.substr(i, 1));
            else {
                if (value[i] == '\r' && i + 1 < value.size() && value[i + 1] == '\n') ++i;
                append_text("\n");
            }
            start = i + 1;
        }
        piece(value.substr(start));
    }
    uint32_t character_reference(std::string_view ref) const {
        size_t i = 1; unsigned base = 10;
        if (i < ref.size() && ref[i] == 'x') { ++i; base = 16; }
        if (i == ref.size()) fail("not well-formed (invalid token)");
        uint32_t result = 0;
        for (; i < ref.size(); ++i) {
            unsigned char c = static_cast<unsigned char>(ref[i]); unsigned digit;
            if (c >= '0' && c <= '9') digit = c - '0';
            else if (base == 16 && c >= 'a' && c <= 'f') digit = c - 'a' + 10;
            else if (base == 16 && c >= 'A' && c <= 'F') digit = c - 'A' + 10;
            else fail("not well-formed (invalid token)");
            if (result > (0x10ffff - digit) / base) fail("reference to invalid character number", 14);
            result = result * base + digit;
        }
        if (!xml_char(result)) fail("reference to invalid character number", 14);
        return result;
    }
    static bool builtin(std::string_view name, std::string& out) {
        if (name == "amp") out = "&";
        else if (name == "lt") out = "<";
        else if (name == "gt") out = ">";
        else if (name == "quot") out = "\"";
        else if (name == "apos") out = "'";
        else return false;
        return true;
    }
    void account_expansion(size_t bytes) {
        expanded_bytes_ += bytes;
        if (expanded_bytes_ > 8 * 1024 * 1024 && expanded_bytes_ / 100 > source_bytes_)
            fail("limit on input amplification factor (from DTD and entities) breached", 43);
    }
    void enter_entity(const std::string& key) {
        if (std::find(entity_stack_.begin(), entity_stack_.end(), key) != entity_stack_.end()) fail("recursive entity reference", 12);
        entity_stack_.push_back(key);
    }
    const Entity* entity(const std::string& key, bool attribute) {
        auto it = entities_.find(key);
        if (it == entities_.end()) {
            if ((external_subset_ || unread_parameter_) && !standalone_) return nullptr;
            fail("undefined entity", 11);
        }
        if (it->second.unparsed) fail("reference to binary entity", 15);
        if (attribute && it->second.external) fail("reference to external entity in attribute", 16);
        return &it->second;
    }
    std::string attribute_value(std::string_view input, bool replacement = false) {
        struct Frame { std::string_view input; size_t pos; bool replacement; std::string entity; };
        std::vector<Frame> frames; frames.push_back({input, 0, replacement, {}});
        std::string out;
        while (!frames.empty()) {
            auto& f = frames.back();
            if (f.pos == f.input.size()) {
                if (!f.entity.empty()) entity_stack_.pop_back();
                frames.pop_back(); continue;
            }
            size_t i = f.pos;
            if (f.input[i] == '<') fail("not well-formed (invalid token)");
            if (f.input[i] != '&') {
                size_t end = f.input.find_first_of("&<", i); if (end == std::string_view::npos) end = f.input.size();
                auto part = f.input.substr(i, end - i); validate(part);
                if (!f.replacement) out += normalize(part, true);
                else for (char c : part) out.push_back(space(c) ? ' ' : c);
                f.pos = end; continue;
            }
            size_t end = f.input.find(';', i + 1);
            if (end == std::string_view::npos) fail("not well-formed (invalid token)");
            std::string ref(f.input.substr(i + 1, end - i - 1)), value;
            f.pos = end + 1;
            if (!ref.empty() && ref[0] == '#') utf8(value, character_reference(ref));
            else if (!builtin(ref, value)) {
                size_t at = 0; name(ref, at); if (at != ref.size()) fail("not well-formed (invalid token)");
                const Entity* e = entity(ref, true);
                if (e) { enter_entity(ref); account_expansion(e->value.size()); frames.push_back({e->value, 0, true, ref}); }
            }
            out += value;
        }
        return out;
    }
    void content_entity(const std::string& key, size_t reference_line, size_t reference_column, size_t reference_index) {
        const Entity* e = entity(key, false);
        if (!e || e->external) return;
        enter_entity(key); account_expansion(e->value.size());
        EntityFrame frame; frame.input.swap(buffer_); frame.position = pos_;
        frame.depth = stack_.size(); frame.was_entity = in_entity_;
        frame.line = line_; frame.column = column_; frame.byte_index = byte_index_; frame.previous_cr = previous_cr_;
        entity_frames_.push_back(std::move(frame));
        buffer_ = e->value; pos_ = 0; in_entity_ = true;
        line_ = reference_line; column_ = reference_column; byte_index_ = reference_index;
    }
    void validate_simple_attribute(std::string_view value) {
        for (size_t i = 0; i < value.size();) {
            if (value[i] == '<') fail("not well-formed (invalid token)");
            if (value[i] == '&') {
                size_t end = value.find(';', i + 1);
                if (end == std::string_view::npos) fail("not well-formed (invalid token)");
                auto ref = value.substr(i + 1, end - i - 1);
                if (!ref.empty() && ref[0] == '#') character_reference(ref);
                else if (ref != "amp" && ref != "lt" && ref != "gt" && ref != "quot" && ref != "apos") {
                    size_t at = 0; name(ref, at);
                    if (at != ref.size()) fail("not well-formed (invalid token)");
                    fail("undefined entity", 11);
                }
                i = end + 1;
            } else { uint32_t cp; i += scalar(value, i, cp); }
        }
    }
    void opening(std::string_view token) {
        if (stack_.empty()) {
            if (root_seen_) fail("junk after document element", 9);
            root_seen_ = true;
        }
        declaration_allowed_ = false;
        size_t i = 1; std::string element = name(token, i);
        Attributes attrs;
        std::array<std::string_view, 8> small_names;
        size_t attribute_count = 0;
        std::unordered_set<std::string_view> many_names;
        const bool simple_validation = validation_only_ && attribute_decls_.empty() && entities_.empty() && !external_subset_ && !unread_parameter_;
        bool selfclose = false;
        while (i < token.size()) {
            size_t before = i; i = skip_space(token, i);
            if (i < token.size() && token[i] == '>') { ++i; break; }
            if (i + 1 < token.size() && token[i] == '/' && token[i + 1] == '>') { i += 2; selfclose = true; break; }
            if (i == before) fail("not well-formed (invalid token)", 4, i);
            const size_t attribute_start = i;
            std::string key = name(token, i);
            auto key_view = token.substr(attribute_start, i - attribute_start);
            if (attribute_count < small_names.size()) {
                for (size_t j = 0; j < attribute_count; ++j) if (small_names[j] == key_view) fail("duplicate attribute", 8, attribute_start);
                small_names[attribute_count] = key_view;
            } else {
                if (attribute_count == small_names.size()) many_names.insert(small_names.begin(), small_names.end());
                if (!many_names.insert(key_view).second) fail("duplicate attribute", 8, attribute_start);
            }
            ++attribute_count;
            i = skip_space(token, i);
            if (i == token.size() || token[i++] != '=') fail("not well-formed (invalid token)", 4, i);
            i = skip_space(token, i);
            if (simple_validation) {
                if (i >= token.size() || (token[i] != '\'' && token[i] != '"')) fail("not well-formed (invalid token)", 4, i);
                const char quote = token[i++]; const size_t start = i;
                while (i < token.size() && token[i] != quote) ++i;
                if (i == token.size()) fail("unclosed token", 5, start);
                validate_simple_attribute(token.substr(start, i - start)); ++i;
            } else {
                std::string raw = quoted(token, i);
                attrs.emplace_back(std::move(key), attribute_value(raw));
            }
        }
        if (i != token.size()) fail("not well-formed (invalid token)", 4, i);
        // RapidXML tokenizes the validated bounded opening tag. Parsing this
        // synthetic empty element never recurses through document descendants.
        if (!validation_only_) {
            std::string bounded(token);
            if (!selfclose) bounded.insert(bounded.size() - 1, 1, '/');
            bounded.push_back('\0');
            if (!token_document_) token_document_ = std::make_unique<rapidxml::xml_document<char>>();
            else token_document_->clear();
            try {
                token_document_->parse<rapidxml::parse_no_entity_translation | rapidxml::parse_no_string_terminators | rapidxml::parse_no_data_nodes>(bounded.data());
            } catch (const rapidxml::parse_error&) { fail("not well-formed (invalid token)"); }
            auto* node = token_document_->first_node();
            if (!node || node->type() != rapidxml::node_element) fail("not well-formed (invalid token)");
            element.assign(node->name(), node->name_size());
        }
        auto decls = attribute_decls_.find(element);
        if (decls != attribute_decls_.end()) {
            for (const auto& declaration : decls->second) {
                auto found = std::find_if(attrs.begin(), attrs.end(), [&](const auto& p) { return p.first == declaration.name; });
                if (found != attrs.end()) { if (declaration.tokenized) collapse_spaces(found->second); }
                else if (declaration.has_default) attrs.emplace_back(declaration.name, declaration.value);
            }
        }
        flush_text(); stack_.push_back(element); if (!validation_only_) sink_.start(element, attrs);
        if (selfclose) { if (!validation_only_) sink_.end(element); stack_.pop_back(); }
    }
    void closing(std::string_view token) {
        size_t i = 2; std::string element = name(token, i); i = skip_space(token, i);
        if (i + 1 != token.size() || token[i] != '>') fail("not well-formed (invalid token)", 4, i);
        if (!entity_frames_.empty() && stack_.size() <= entity_frames_.back().depth) fail("asynchronous entity", 13);
        if (stack_.empty() || stack_.back() != element) fail("mismatched tag", 7, 2);
        flush_text(); if (!validation_only_) sink_.end(element); stack_.pop_back();
    }
    void processing_instruction(std::string_view token) {
        size_t i = 2; std::string target = name(token, i);
        if (i != token.size() - 2 && !space(token[i])) fail("not well-formed (invalid token)", 4, i);
        std::string lower(target); for (char& c : lower) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (lower == "xml") {
            if (target != "xml" || !declaration_allowed_ || in_entity_) fail("XML or text declaration not at start of entity", 17);
            i = require_space(token, i); int stage = 0;
            while (i < token.size() - 2) {
                std::string key = name(token, i); i = skip_space(token, i);
                if (i == token.size() || token[i++] != '=') fail("XML declaration not well-formed", 30);
                i = skip_space(token, i); std::string value = quoted(token, i);
                if (stage == 0 && key == "version") {
                    if (value.empty() || value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") != std::string::npos) fail("XML declaration not well-formed", 30);
                    stage = 1;
                } else if (stage == 1 && key == "encoding") {
                    if (value.empty() || !((value[0] >= 'A' && value[0] <= 'Z') || (value[0] >= 'a' && value[0] <= 'z'))) fail("XML declaration not well-formed", 30);
                    for (char c : value) if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) fail("XML declaration not well-formed", 30);
                    stage = 2;
                } else if ((stage == 1 || stage == 2) && key == "standalone") {
                    if (value != "yes" && value != "no") fail("XML declaration not well-formed", 30);
                    standalone_ = value == "yes"; stage = 3;
                } else fail("XML declaration not well-formed", 30);
                size_t next = skip_space(token, i);
                if (next == i && i < token.size() - 2) fail("XML declaration not well-formed", 30);
                i = next;
            }
            if (!stage) fail("XML declaration not well-formed", 30);
        }
        declaration_allowed_ = false; validate(token);
    }
    static bool word(std::string_view s, size_t i, std::string_view w) {
        return s.substr(i, w.size()) == w && (i + w.size() == s.size() || !((s[i + w.size()] >= 'A' && s[i + w.size()] <= 'Z') || (s[i + w.size()] >= 'a' && s[i + w.size()] <= 'z') || (s[i + w.size()] >= '0' && s[i + w.size()] <= '9') || s[i + w.size()] == '_' || s[i + w.size()] == ':' || s[i + w.size()] == '-'));
    }
    static bool pubid_char(char c) {
        return c == ' ' || c == '\r' || c == '\n' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || std::strchr("-'()+,./:=?;!*#@$_%", c) != nullptr;
    }
    void external_id(std::string_view s, size_t& i, bool public_only = false) {
        if (word(s, i, "SYSTEM")) {
            i = require_space(s, i + 6); quoted(s, i);
        } else if (word(s, i, "PUBLIC")) {
            i = require_space(s, i + 6); std::string id = quoted(s, i);
            for (char c : id) if (!pubid_char(c)) fail("illegal character(s) in public id", 32);
            size_t next = skip_space(s, i);
            if (public_only && (next == s.size() || s[next] == '>')) { i = next; return; }
            if (next == i) fail("syntax error", 2, i);
            i = next; quoted(s, i);
        } else fail("syntax error", 2, i);
    }
    std::string declaration_entity_value(std::string_view value) {
        std::string normalized = normalize(value); value = normalized;
        std::string out;
        for (size_t i = 0; i < value.size();) {
            if (value[i] == '%') fail("illegal parameter entity reference", 10);
            if (value[i] != '&') { out.push_back(value[i++]); continue; }
            size_t end = value.find(';', i + 1);
            if (end == std::string_view::npos) fail("not well-formed (invalid token)");
            auto ref = value.substr(i + 1, end - i - 1);
            if (!ref.empty() && ref[0] == '#') utf8(out, character_reference(ref));
            else { size_t at = 0; name(ref, at); if (at != ref.size()) fail("not well-formed (invalid token)"); out.append(value.substr(i, end - i + 1)); }
            i = end + 1;
        }
        return out;
    }
    void entity_declaration(std::string_view s) {
        size_t i = require_space(s, 8); bool parameter = false;
        if (i < s.size() && s[i] == '%') { parameter = true; i = require_space(s, i + 1); }
        std::string key = name(s, i); i = require_space(s, i); Entity e;
        if (i < s.size() && (s[i] == '\'' || s[i] == '"')) e.value = declaration_entity_value(quoted(s, i));
        else {
            e.external = true; external_id(s, i);
            size_t next = skip_space(s, i);
            if (!parameter && word(s, next, "NDATA")) {
                if (next == i) fail("syntax error", 2, i);
                i = require_space(s, next + 5); name(s, i); e.unparsed = true;
            }
        }
        i = skip_space(s, i);
        if (i + 1 != s.size() || s[i] != '>') fail("syntax error", 2, i);
        if (unread_parameter_ && !standalone_) return;
        std::string predefined;
        if (!parameter && builtin(key, predefined)) return;
        if (disable_entities_) throw EntitiesDisabled();
        if (!parameter) entities_.emplace(std::move(key), std::move(e));
    }
    void enumeration(std::string_view s, size_t& i, bool names) {
        if (i == s.size() || s[i++] != '(') fail("syntax error", 2, i);
        i = skip_space(s, i); name(s, i, !names); i = skip_space(s, i);
        while (i < s.size() && s[i] == '|') { i = skip_space(s, i + 1); name(s, i, !names); i = skip_space(s, i); }
        if (i == s.size() || s[i++] != ')') fail("syntax error", 2, i);
    }
    void attlist_declaration(std::string_view s) {
        size_t i = require_space(s, 9); std::string element = name(s, i);
        for (;;) {
            size_t next = skip_space(s, i);
            if (next + 1 == s.size() && s[next] == '>') return;
            if (next == i) fail("syntax error", 2, i);
            i = next; AttributeDecl declaration; declaration.name = name(s, i); i = require_space(s, i);
            if (word(s, i, "CDATA")) i += 5;
            else {
                declaration.tokenized = true;
                if (i < s.size() && s[i] == '(') enumeration(s, i, false);
                else if (word(s, i, "NOTATION")) { i = require_space(s, i + 8); enumeration(s, i, true); }
                else {
                    std::string type = name(s, i);
                    if (type != "ID" && type != "IDREF" && type != "IDREFS" && type != "ENTITY" && type != "ENTITIES" && type != "NMTOKEN" && type != "NMTOKENS") fail("syntax error", 2, i);
                }
            }
            i = require_space(s, i);
            if (word(s, i, "#REQUIRED")) i += 9;
            else if (word(s, i, "#IMPLIED")) i += 8;
            else {
                if (word(s, i, "#FIXED")) i = require_space(s, i + 6);
                declaration.has_default = true; declaration.value = attribute_value(quoted(s, i));
                if (declaration.tokenized) collapse_spaces(declaration.value);
            }
            if (!(unread_parameter_ && !standalone_)) {
                auto& declarations = attribute_decls_[element];
                if (std::none_of(declarations.begin(), declarations.end(), [&](const auto& a) { return a.name == declaration.name; })) declarations.push_back(std::move(declaration));
            }
        }
    }
    void element_declaration(std::string_view s) {
        size_t i = require_space(s, 9); name(s, i); i = require_space(s, i);
        if (word(s, i, "EMPTY")) i += 5;
        else if (word(s, i, "ANY")) i += 3;
        else if (i < s.size() && s[i] == '(') {
            // Parse children content models iteratively, avoiding native stack
            // growth even when a DTD contains a deeply nested grammar.
            struct Group { char separator = 0; bool expect = true; size_t count = 0; };
            if (s.substr(skip_space(s, i + 1), 7) == "#PCDATA") {
                i = skip_space(s, i + 1) + 7; i = skip_space(s, i); size_t count = 0;
                while (i < s.size() && s[i] == '|') { i = skip_space(s, i + 1); name(s, i); ++count; i = skip_space(s, i); }
                if (i == s.size() || s[i++] != ')') fail("syntax error", 2, i);
                if (count) { if (i == s.size() || s[i++] != '*') fail("syntax error", 2, i); }
                else if (i < s.size() && s[i] == '*') ++i;
            } else {
                std::vector<Group> groups(1); ++i;
                while (!groups.empty()) {
                    i = skip_space(s, i); if (i == s.size()) fail("syntax error", 2, i);
                    if (groups.back().expect) {
                        if (s[i] == '(') { groups.push_back(Group{}); ++i; continue; }
                        name(s, i); if (i < s.size() && (s[i] == '?' || s[i] == '*' || s[i] == '+')) ++i;
                        groups.back().expect = false; ++groups.back().count;
                    } else if (s[i] == ',' || s[i] == '|') {
                        if (groups.back().separator && groups.back().separator != s[i]) fail("syntax error", 2, i);
                        groups.back().separator = s[i++]; groups.back().expect = true;
                    } else if (s[i] == ')') {
                        groups.pop_back(); ++i; if (i < s.size() && (s[i] == '?' || s[i] == '*' || s[i] == '+')) ++i;
                        if (!groups.empty()) { groups.back().expect = false; ++groups.back().count; }
                    } else fail("syntax error", 2, i);
                }
            }
        } else fail("syntax error", 2, i);
        i = skip_space(s, i); if (i + 1 != s.size() || s[i] != '>') fail("syntax error", 2, i);
    }
    void notation_declaration(std::string_view s) {
        size_t i = require_space(s, 10); name(s, i); i = require_space(s, i); external_id(s, i, true);
        i = skip_space(s, i); if (i + 1 != s.size() || s[i] != '>') fail("syntax error", 2, i);
    }
    void comment_token(std::string_view token, bool dtd = false) {
        auto value = token.substr(4, token.size() - 7);
        if (value.find("--") != std::string_view::npos || (!value.empty() && value.back() == '-')) fail("not well-formed (invalid token)");
        validate(value); declaration_allowed_ = false;
        if (process_comments_) { if (!dtd) flush_text(); sink_.comment(normalize(value)); }
    }
    void doctype(std::string_view token) {
        if (doctype_seen_ || root_seen_ || in_entity_) fail("syntax error", 2);
        doctype_seen_ = true; declaration_allowed_ = false;
        size_t i = require_space(token, 9); name(token, i);
        size_t next = skip_space(token, i);
        if (word(token, next, "SYSTEM") || word(token, next, "PUBLIC")) {
            if (next == i) fail("syntax error", 2, i);
            i = next; external_id(token, i); external_subset_ = true; next = skip_space(token, i);
        }
        i = next;
        if (i < token.size() && token[i] == '[') {
            ++i;
            for (;;) {
                i = skip_space(token, i); if (i == token.size()) fail("unclosed token", 5);
                if (token[i] == ']') { ++i; break; }
                if (token[i] == '%') {
                    ++i; name(token, i); if (i == token.size() || token[i++] != ';') fail("syntax error", 2, i);
                    unread_parameter_ = true; continue;
                }
                if (token.substr(i, 4) == "<!--") {
                    size_t end = token.find("-->", i + 4); if (end == std::string_view::npos) fail("unclosed token", 5, i);
                    comment_token(token.substr(i, end + 3 - i), true); i = end + 3; continue;
                }
                if (token.substr(i, 2) == "<?") {
                    size_t end = token.find("?>", i + 2); if (end == std::string_view::npos) fail("unclosed token", 5, i);
                    processing_instruction(token.substr(i, end + 2 - i)); i = end + 2; continue;
                }
                size_t end = i; char quote = 0;
                for (; end < token.size(); ++end) {
                    char c = token[end];
                    if (quote) { if (c == quote) quote = 0; }
                    else if (c == '\'' || c == '"') quote = c;
                    else if (c == '>') break;
                    else if (c == '%' && token.substr(i, 8) != "<!ENTITY") fail("illegal parameter entity reference", 10, end);
                }
                if (end == token.size()) fail("unclosed token", 5, i);
                auto declaration = token.substr(i, end + 1 - i);
                if (declaration.substr(0, 8) == "<!ENTITY") entity_declaration(declaration);
                else if (declaration.substr(0, 9) == "<!ATTLIST") attlist_declaration(declaration);
                else if (declaration.substr(0, 9) == "<!ELEMENT") element_declaration(declaration);
                else if (declaration.substr(0, 10) == "<!NOTATION") notation_declaration(declaration);
                else fail("syntax error", 2, i);
                i = end + 1;
            }
        }
        i = skip_space(token, i); if (i + 1 != token.size() || token[i] != '>') fail("syntax error", 2, i);
        validate(token);
    }
    size_t dtd_lexeme(bool final) {
        std::string_view s(buffer_.data() + pos_, buffer_.size() - pos_);
        if (s.empty()) return 0;
        size_t i = 0;
        if (space(s[0])) {
            i = skip_space(s, 0);
            if (i == s.size() && !final && s[i - 1] == '\r') --i;
            return i;
        }
        if (s[0] == '\'' || s[0] == '"') {
            i = s.find(s[0], 1);
            if (i != std::string_view::npos) {
                // A following delimiter distinguishes a complete DTD literal
                // from an incomplete token at a feed boundary.
                if (i + 1 == s.size() && !final) return 0;
                return i + 1;
            }
        } else if (s[0] == '<') {
            if (s.substr(0, 4) == "<!--") {
                i = s.find("-->", 4); if (i != std::string_view::npos) return i + 3;
            } else if (s.substr(0, 2) == "<?") {
                i = s.find("?>", 2); if (i != std::string_view::npos) return i + 2;
            } else {
                const char* declarations[] = {"<!DOCTYPE", "<!ENTITY", "<!ATTLIST", "<!ELEMENT", "<!NOTATION"};
                bool partial = false;
                for (const char* declaration : declarations) {
                    size_t length = std::strlen(declaration);
                    if (s.size() <= length && std::string_view(declaration, s.size()) == s) partial = true;
                    if (s.size() > length && s.substr(0, length) == declaration && space(s[length])) return length;
                }
                if (!partial && s.size() >= 4) fail("syntax error", 2);
            }
        } else if (s[0] == '%') {
            if (s.size() > 1 && space(s[1])) return 1;
            i = s.find(';', 1); if (i != std::string_view::npos) return i + 1;
        } else if (s[0] == ']' || s[0] == ')') {
            if (s.size() == 1 && !final) return 0;
            if (s[0] == ')' && s.size() > 1 && (s[1] == '*' || s[1] == '+' || s[1] == '?')) return 2;
            return 1;
        } else if (std::strchr("[>(|,?*+", s[0])) return 1;
        else {
            i = s[0] == '#' ? 1 : 0;
            for (; i < s.size();) {
                uint32_t cp; size_t n = scalar(s, i, cp, final);
                if (!n) break;
                if (!name_char(cp)) break;
                i += n;
            }
            if (i < s.size()) {
                if (!i) fail("syntax error", 2);
                if (s[0] != '#' && (s[i] == '+' || s[i] == '*' || s[i] == '?')) ++i;
                return i;
            }
        }
        if (final) fail("unclosed token", 5);
        return 0;
    }
    bool dtd_step(bool final) {
        size_t length = dtd_lexeme(final); if (!length) return false;
        std::string_view lexeme(buffer_.data() + pos_, length);
        if (dtd_mode_ == 3) {
            if (lexeme == ">") dtd_mode_ = 0;
            else for (char c : lexeme) if (!space(c)) fail("syntax error", 2);
        } else if (dtd_mode_ == 1) {
            dtd_token_.append(lexeme.data(), lexeme.size());
            if (lexeme == "[") {
                dtd_token_.back() = '>'; doctype(dtd_token_); dtd_token_.clear(); dtd_mode_ = 2;
            } else if (lexeme == ">") { doctype(dtd_token_); dtd_token_.clear(); dtd_mode_ = 0; }
        } else if (dtd_token_.empty()) {
            if (lexeme == "]") dtd_mode_ = 3;
            else if (space(lexeme[0])) { /* insignificant DTD whitespace */ }
            else if (lexeme.substr(0, 4) == "<!--") comment_token(lexeme, true);
            else if (lexeme.substr(0, 2) == "<?") processing_instruction(lexeme);
            else if (lexeme[0] == '%') {
                size_t i = 1; name(lexeme, i);
                if (i + 1 != lexeme.size() || lexeme[i] != ';') fail("syntax error", 2);
                unread_parameter_ = true;
            } else if (lexeme == "<!ENTITY" || lexeme == "<!ELEMENT" || lexeme == "<!ATTLIST" || lexeme == "<!NOTATION") dtd_token_.assign(lexeme);
            else fail("syntax error", 2);
        } else {
            dtd_token_.append(lexeme.data(), lexeme.size());
            if (lexeme == ">") {
                std::string_view declaration(dtd_token_);
                if (declaration.substr(0, 8) == "<!ENTITY") entity_declaration(declaration);
                else if (declaration.substr(0, 9) == "<!ATTLIST") attlist_declaration(declaration);
                else if (declaration.substr(0, 9) == "<!ELEMENT") element_declaration(declaration);
                else if (declaration.substr(0, 10) == "<!NOTATION") notation_declaration(declaration);
                else fail("syntax error", 2);
                validate(declaration); dtd_token_.clear();
            }
        }
        consume(length); return true;
    }
    size_t markup_end(bool final) {
        const std::string_view s(buffer_.data() + pos_, buffer_.size() - pos_);
        if (s.substr(0, 4) == "<!--") {
            auto end = s.find("-->", 4); if (end != std::string_view::npos) return end + 3;
        } else if (s.substr(0, 9) == "<![CDATA[") {
            auto end = s.find("]]>", 9); if (end != std::string_view::npos) return end + 3;
        } else if (s.substr(0, 2) == "<?") {
            auto end = s.find("?>", 2); if (end != std::string_view::npos) return end + 2;
        } else {
            char quote = 0; int bracket = 0;
            const bool dtd = s.substr(0, 9) == "<!DOCTYPE";
            for (size_t i = 1; i < s.size(); ++i) {
                char c = s[i];
                if (quote) { if (c == quote) quote = 0; continue; }
                if (dtd && s.substr(i, 4) == "<!--") {
                    auto end = s.find("-->", i + 4); if (end == std::string_view::npos) break; i = end + 2; continue;
                }
                if (dtd && s.substr(i, 2) == "<?") {
                    auto end = s.find("?>", i + 2); if (end == std::string_view::npos) break; i = end + 1; continue;
                }
                if (c == '\'' || c == '"') quote = c;
                else if (dtd && c == '[') ++bracket;
                else if (dtd && c == ']') --bracket;
                else if (c == '>' && !bracket) return i + 1;
            }
        }
        if (final) fail("unclosed token", 5);
        return 0;
    }
    size_t source_units(std::string_view input) const {
        if (!source_width_) return input.size();
        size_t units = 0;
        for (unsigned char c : input) if ((c & 0xc0) != 0x80)
            units += source_width_ == 1 ? 1 : (c >= 0xf0 ? 4 : 2);
        return units;
    }
    void parse_available(bool final) {
        while (pos_ < buffer_.size() || !entity_frames_.empty()) {
            if (pos_ == buffer_.size() && !entity_frames_.empty()) {
                auto& frame = entity_frames_.back();
                if (stack_.size() != frame.depth || cdata_mode_) fail("asynchronous entity", 13);
                buffer_.swap(frame.input); pos_ = frame.position; in_entity_ = frame.was_entity;
                line_ = frame.line; column_ = frame.column; byte_index_ = frame.byte_index; previous_cr_ = frame.previous_cr;
                entity_frames_.pop_back(); entity_stack_.pop_back(); continue;
            }
            const bool complete = final || in_entity_;
            if (dtd_mode_) { if (!dtd_step(complete)) return; continue; }
            if (cdata_mode_) {
                size_t end = buffer_.find("]]>", pos_);
                bool closed = end != std::string::npos;
                if (!closed) end = buffer_.size();
                size_t usable = end;
                if (!closed && !complete) {
                    if (usable > pos_ && buffer_[usable - 1] == '\r') --usable;
                    size_t held = 0; while (usable > pos_ && held < 2 && buffer_[usable - 1] == ']') { --usable; ++held; }
                }
                size_t at = pos_;
                while (at < usable) { uint32_t cp; size_t n = scalar(std::string_view(buffer_.data() + pos_, usable - pos_), at - pos_, cp, closed || complete); if (!n) break; at += n; }
                usable = at;
                auto value = std::string_view(buffer_.data() + pos_, usable - pos_);
                emit_literal(value);
                consume(usable - pos_);
                if (closed && usable == end) { consume(3); cdata_mode_ = false; continue; }
                if (complete) fail("unclosed CDATA section", 20);
                return;
            }
            if (byte_index_ == 0 && !in_entity_ && pos_ == 0 && static_cast<unsigned char>(buffer_[0]) == 0xef) {
                if (buffer_.size() < 3 && !final) { return; }
                if (buffer_.compare(0, 3, "\xef\xbb\xbf") == 0) { consume(3); continue; }
            }
            if (buffer_[pos_] == '<') {
                if (buffer_.size() - pos_ > 9 && buffer_.compare(pos_, 9, "<!DOCTYPE") == 0 && space(buffer_[pos_ + 9])) {
                    if (root_seen_ || doctype_seen_ || in_entity_) fail("syntax error", 2);
                    dtd_mode_ = 1; dtd_token_ = "<!DOCTYPE"; consume(9); continue;
                }
                if (buffer_.compare(pos_, 9, "<![CDATA[") == 0) {
                    if (stack_.empty()) fail("syntax error", 2);
                    consume(9); cdata_mode_ = true; continue;
                }
                size_t length = markup_end(complete); if (!length) { return; }
                std::string_view token(buffer_.data() + pos_, length);
                if (token.substr(0, 4) == "<!--") comment_token(token);
                else if (token.substr(0, 9) == "<![CDATA[") {
                    if (stack_.empty()) fail("syntax error", 2);
                    auto value = token.substr(9, token.size() - 12); validate(value); emit_literal(value);
                } else if (token.substr(0, 2) == "<?") processing_instruction(token);
                else if (token.substr(0, 9) == "<!DOCTYPE") doctype(token);
                else if (token.substr(0, 2) == "</") closing(token);
                else if (token.substr(0, 2) == "<!") fail("not well-formed (invalid token)");
                else opening(token);
                consume(length); continue;
            }
            if (buffer_[pos_] == '&') {
                if (stack_.empty()) fail(root_seen_ ? "junk after document element" : "not well-formed (invalid token)", root_seen_ ? 9 : 4);
                size_t end = buffer_.find(';', pos_ + 1);
                if (end == std::string::npos) {
                    if (buffer_.find_first_of("<& \t\r\n", pos_ + 1) != std::string::npos || complete) fail("not well-formed (invalid token)");
                    return;
                }
                std::string ref(buffer_, pos_ + 1, end - pos_ - 1), value;
                if (!ref.empty() && ref[0] == '#') { utf8(value, character_reference(ref)); append_text(value); }
                else if (builtin(ref, value)) append_text(value);
                else {
                    size_t at = 0; name(ref, at); if (at != ref.size()) fail("not well-formed (invalid token)");
                    entity(ref, false); // Validate at the reference's location.
                    const size_t l = line_, col = column_, index = byte_index_;
                    consume(end - pos_ + 1); content_entity(ref, l, col, index); continue;
                }
                consume(end - pos_ + 1); continue;
            }
            size_t end = buffer_.find_first_of("<&", pos_); if (end == std::string::npos) end = buffer_.size();
            size_t usable = end;
            if (end == buffer_.size() && !complete) {
                if (usable > pos_ && buffer_[usable - 1] == '\r') --usable;
                size_t held = 0; while (usable > pos_ && held < 2 && buffer_[usable - 1] == ']') { --usable; ++held; }
            }
            size_t at = pos_;
            while (at < usable) {
                uint32_t cp; size_t n = scalar(std::string_view(buffer_.data() + pos_, usable - pos_), at - pos_, cp, complete || end < buffer_.size());
                if (!n) break;
                at += n;
            }
            usable = at;
            auto value = std::string_view(buffer_.data() + pos_, usable - pos_);
            if (value.find("]]>") != std::string_view::npos) fail("not well-formed (invalid token)");
            if (stack_.empty()) {
                for (char c : value) if (!space(c)) fail(root_seen_ ? "junk after document element" : "syntax error", root_seen_ ? 9 : 2);
                if (!value.empty()) declaration_allowed_ = false;
            } else emit_literal(value);
            if (usable == pos_) return;
            consume(usable - pos_);
            if (usable < end) return;
        }
    }
public:
    explicit Parser(Sink& sink, bool disable_entities = true, bool process_comments = false, bool validation_only = false)
        : sink_(sink), disable_entities_(disable_entities), process_comments_(process_comments), validation_only_(validation_only) {}
    size_t line() const noexcept { return line_; }
    size_t column() const noexcept { return column_; }
    size_t byte_index() const noexcept { return byte_index_; }
    void set_source_encoding(int width) {
        if (width < 0 || width > 2) throw std::invalid_argument("unsupported source encoding width");
        source_width_ = width;
    }
    void feed(const char* data, size_t length, bool final = false, size_t undecoded_bytes = 0) {
        if (final_) fail("parsing finished", 36);
        source_bytes_ += source_units(std::string_view(data ? data : "", length)) + undecoded_bytes - previous_undecoded_;
        previous_undecoded_ = undecoded_bytes;
        if (length) buffer_.append(data, length);
        const size_t available_units = source_units(buffer_) + undecoded_bytes;
        if (!final && retry_after_ && available_units < retry_after_) return;
        retry_after_ = 0;
        parse_available(final);
        // Defer only when this entire parse attempt made no progress. A
        // completed token followed by a partial one resets the heuristic.
        retry_after_ = !pos_ && !buffer_.empty() ? 2 * available_units : 0;
        flush_text();
        if (pos_) { buffer_.erase(0, pos_); pos_ = 0; }
        if (final) {
            if (cdata_mode_) fail("unclosed CDATA section", 20);
            if (dtd_mode_) fail("unclosed token", 5);
            if (!buffer_.empty()) fail("unclosed token", 5);
            if (!root_seen_) fail("no element found", 3);
            if (!stack_.empty()) fail("no element found", 3);
            final_ = true;
        }
    }
};
} // namespace rapidxml_events
#endif
