// Batch-2 probe: A-class (control-token pollution / bare-word header / nested wrapper / CDATA)
// and E-class (case drift / invalid-name intended_function) with safety negatives.
#include "models/qwen3_5/frontend/tool_call_parser.h"

#include <nlohmann/json.hpp>

#include <iostream>
#include <span>
#include <string>
#include <vector>

using Json = nlohmann::json;
namespace fi = ninfer::models::qwen3_5::frontend;

static std::string tool_definition(const std::string& tool_name, Json properties,
                                   Json required = Json::array()) {
    Json parameters{{"type", "object"}, {"properties", std::move(properties)}};
    if (!required.empty()) { parameters["required"] = std::move(required); }
    return Json{{"type", "function"},
                {"function", Json{{"name", tool_name}, {"parameters", std::move(parameters)}}}}
        .dump();
}

static fi::ToolCallOutputContract contract_for(const std::string& name, Json props) {
    const std::vector<std::string> defs = {tool_definition(name, std::move(props))};
    return *fi::build_tool_call_output_contract(
        std::span<const std::string>(defs.data(), defs.size()), true);
}

static std::string clip(const std::string& text, std::size_t limit = 170) {
    const std::string escaped = Json(text).dump();
    return escaped.size() <= limit ? escaped : escaped.substr(0, limit) + "...";
}

static void report(const char* label, const std::string& text,
                   const fi::ToolCallOutputContract& contract, std::size_t max_len = 64) {
    const auto parsed = fi::parse_qwen_tool_call_output(text, max_len, contract);
    std::cout << "=== " << label << "\n";
    std::cout << "  calls=" << parsed.tool_calls.size() << " content=" << clip(parsed.content, 90)
              << "\n";
    for (const auto& call : parsed.tool_calls) {
        std::cout << "    call name=" << call.name << " args=" << clip(call.arguments_json, 150)
                  << "\n";
    }
    const auto& d = parsed.diagnostics;
    std::cout << "  reason=" << ninfer::tool_call_parse_fallback_reason_name(d.fallback_reason)
              << " marker_seen=" << d.marker_seen << " recovered=" << d.recovered
              << " malformed_reported=" << d.malformed_call_reported << "\n";
}

int main() {
    const auto bash    = contract_for("bash", Json{{"command", Json{{"type", "string"}}}});
    const auto weather = contract_for("get_weather", Json{{"city", Json{{"type", "string"}}}});

    report("A1 im_start before function (complete body)",
           "<tool_call>\n<|im_start|>function=get_weather>\n<parameter=city>\nParis\n</parameter>\n"
           "</function>\n</tool_call>",
           weather);
    report("A2 im_start same line",
           "<tool_call><|im_start|>function=get_weather>\n<parameter=city>\nParis\n</parameter>\n"
           "</function>\n</tool_call>",
           weather);
    report("A3 im_start standalone line",
           "<tool_call>\n<|im_start|>\n<function=get_weather>\n<parameter=city>\nParis\n"
           "</parameter>\n</function>\n</tool_call>",
           weather);
    report("A4 bare im_start function, no wrapper",
           "<|im_start|>function=get_weather>\n<parameter=city>\nParis\n</parameter>\n</function>",
           weather);
    report("A5 bare-word function header (space, no =)",
           "<tool_call>\n<function bash>\n<parameter=command>ls</parameter>\n</function>\n"
           "</tool_call>",
           bash);
    report("A6 tool_call nested in function_calls",
           "<function_calls>\n<tool_call>\n<function=bash>\n<parameter=command>ls</parameter>\n"
           "</function>\n</tool_call>\n</function_calls>",
           bash);
    report("A8 CDATA-wrapped parameter value",
           "<tool_call>\n<function=bash>\n<parameter=command><![CDATA[ls -la]]></parameter>\n"
           "</function>\n</tool_call>",
           bash);
    report("E1 case-drift call (declared bash, called BaSh)",
           "<tool_call>\n<function=BaSh>\n<parameter=command>ls</parameter>\n</function>\n"
           "</tool_call>",
           bash);
    report("E2 invalid name -> intended_function present",
           "<tool_call>\n<function=bad name!>\n<parameter=command>ls</parameter>\n</function>\n"
           "</tool_call>",
           bash);

    // ---- safety negatives: must produce NO call ----
    report("N1 undeclared name in repaired form must NOT call",
           "<tool_call>\n<|im_start|>function=evil_tool>\n<parameter=x>1</parameter>\n</function>\n"
           "</tool_call>",
           bash);
    report("N2 prose mentioning im_start and function= must NOT call",
           "The control token <|im_start|> precedes a function= field in the template.",
           bash);
    return 0;
}
