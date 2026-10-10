#ifndef RAPIDXMLTODICT_EVENTS_HPP
#define RAPIDXMLTODICT_EVENTS_HPP

// Source-compatible binding aliases. XML grammar and incremental state live in
// RapidXML; this adapter contains no scanner, validator, or synthetic DOM parse.
#include <rapidxml/rapidxml_stream.hpp>
namespace rapidxml_events {
using Attributes = rapidxml::stream::Attributes;
using Error = rapidxml::stream::Error;
using EntitiesDisabled = rapidxml::stream::EntitiesDisabled;
using Sink = rapidxml::stream::Sink;
using Parser = rapidxml::stream::Parser;
}
#endif
