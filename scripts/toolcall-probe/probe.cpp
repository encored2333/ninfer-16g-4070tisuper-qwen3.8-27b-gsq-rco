// Gap probe for NInfer's Qwen tool-call parser. Read-only against D:\ninfer\src.
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

static fi::ToolCallOutputContract contract_for_many(const std::vector<std::string>& defs) {
    return *fi::build_tool_call_output_contract(
        std::span<const std::string>(defs.data(), defs.size()), true);
}

static std::string clip(const std::string& text, std::size_t limit = 150) {
    const std::string escaped = Json(text).dump();
    return escaped.size() <= limit ? escaped : escaped.substr(0, limit) + "...";
}

static void report(const char* label, const std::string& text,
                   const fi::ToolCallOutputContract& contract, std::size_t max_len = 64) {
    const auto parsed = fi::parse_qwen_tool_call_output(text, max_len, contract);
    std::cout << "=== " << label << "\n";
    std::cout << "  is_tool_call_response=" << (parsed.is_tool_call_response ? 1 : 0)
              << " content=" << clip(parsed.content) << " content_size=" << parsed.content.size()
              << " calls=" << parsed.tool_calls.size() << "\n";
    for (const auto& call : parsed.tool_calls) {
        std::cout << "    call name=" << call.name << " args=" << clip(call.arguments_json, 260)
                  << "\n";
    }
    const auto& d = parsed.diagnostics;
    std::cout << "  reason=" << ninfer::tool_call_parse_fallback_reason_name(d.fallback_reason)
              << " marker_seen=" << d.marker_seen << " recovered=" << d.recovered
              << " recovered_call_count=" << d.recovered_call_count
              << " malformed_reported=" << d.malformed_call_reported
              << " trailing_dropped=" << d.trailing_content_dropped
              << " structured_count=" << d.structured_call_count
              << " empty_omitted=" << d.empty_arguments_omitted
              << " schema_mismatch=" << d.schema_mismatch_arguments
              << " dup_repaired=" << d.duplicate_parameters_repaired
              << " forced_closed=" << d.forced_call_closed << "\n";
}

int main() {
    const fi::ToolCallOutputContract legacy{};
    const auto weather = contract_for("get_weather", Json{{"city", Json{{"type", "string"}}},
                                                          {"days", Json{{"type", "integer"}}}});
    const auto configure = contract_for("configure", Json{{"value", Json{{"type", "string"}}}});
    const auto bash      = contract_for("bash", Json{{"command", Json{{"type", "string"}}}});
    const auto agent     = contract_for("agent", Json{{"task", Json{{"type", "string"}}},
                                                     {"mode", Json{{"type", "string"}}}});
    const auto task      = contract_for("TaskCreate", Json{{"description", Json{{"type", "string"}}}});
    const auto case_pair = contract_for_many(
        {tool_definition("Bash", Json{{"command", Json{{"type", "string"}}}}),
         tool_definition("bash", Json{{"command", Json{{"type", "string"}}}})});
    const auto declared_int =
        contract_for("configure", Json{{"value", Json{{"type", "integer"}}}});

    // 1. chat-template control token between the wrapper and the function tag.
    report("A1 im_start before function, complete body",
           "<tool_call>\n<|im_start|>function=get_weather>\n<parameter=city>\nParis\n"
           "</parameter>\n</function>\n</tool_call>",
           weather);
    report("A2 im_start on the same line, complete body",
           "<tool_call><|im_start|>function=get_weather><parameter=city>Paris</parameter>"
           "</function></tool_call>",
           weather);
    report("A3 im_end/space pollution before function tag",
           "<tool_call>\n<|im_start|>\n <function=get_weather>\n<parameter=city>\nParis\n"
           "</parameter>\n</function>\n</tool_call>",
           weather);
    report("A4 bare function preceded by control token, no wrapper",
           "<|im_start|>function=get_weather><parameter=city>Paris</parameter></function>",
           weather);

    // 2. mismatched / reordered structural closers.
    report("B1 tool_call closed before function",
           "<tool_call>\n<function=configure>\n<parameter=value>\nx\n</parameter>\n"
           "</tool_call>\n</function>",
           configure);
    report("B2 function closed, tool_call tag never emitted",
           "<tool_call>\n<function=configure>\n<parameter=value>\nx\n</parameter>\n</function>",
           configure);
    report("B3 function close missing, tool_call closed",
           "<tool_call>\n<function=configure>\n<parameter=value>\nx\n</parameter>\n</tool_call>",
           configure);
    report("B4 empty wrapper", "<tool_call>\n</tool_call>", configure);
    report("B5 only the wrapper opener", "<tool_call>", configure);
    report("B6 only the wrapper opener plus text", "<tool_call> hi", configure);
    report("B7 truncated function opener without '>'", "<tool_call>\n<function=", configure);
    report("B8 truncated function opener with partial name",
           "<tool_call>\n<function=configure", configure);
    report("B9 truncated parameter opener without '>'",
           "<tool_call>\n<function=configure>\n<parameter=", configure);
    report("B10 empty output", "", configure);
    report("B11 only a marker, nothing else", "<function=configure>", configure);

    // 3. reserved substrings inside parameter values.
    report("C1 value holds </parameter> only", "<tool_call>\n<function=bash>\n<parameter=command>\n"
                                              "echo\n</parameter>\n</function>\n</tool_call>",
           bash);
    report("C2 value holds an unbalanced <function= opener",
           "<tool_call>\n<function=bash>\n<parameter=command>\necho <function=fake> tail\n"
           "</parameter>\n</function>\n</tool_call>",
           bash);
    report("C3 value holds </tool_call> text", "<tool_call>\n<function=bash>\n<parameter=command>\n"
                                              "echo </tool_call> tail\n</parameter>\n</function>\n"
                                              "</tool_call>",
           bash);
    report("C4 legacy contract, value holds <tool_call>",
           "<tool_call>\n<function=bash>\n<parameter=command>\necho <tool_call> tail\n"
           "</parameter>\n</function>\n</tool_call>",
           legacy);
    report("C5 value holds a nested balanced <parameter=..>..</parameter>",
           "<tool_call>\n<function=bash>\n<parameter=command>\npython3 - <<'PY'\n"
           "pattern = r'<parameter=edits>\\n(.*?)\\n</parameter>'\nPY\n</parameter>\n"
           "</function>\n</tool_call>",
           bash);

    // 4. one wrapper, several functions; several wrappers.
    report("D1 two functions inside one tool_call",
           "<tool_call>\n<function=configure>\n<parameter=value>\n1\n</parameter>\n</function>\n"
           "<function=configure>\n<parameter=value>\n2\n</parameter>\n</function>\n</tool_call>",
           configure);
    report("D2 two parameters-less functions inside one tool_call",
           "<tool_call>\n<function=configure></function>\n<function=configure></function>\n"
           "</tool_call>",
           configure);
    report("D3 two wrappers, both complete",
           "<tool_call>\n<function=configure>\n<parameter=value>\n1\n</parameter>\n</function>\n"
           "</tool_call>\n<tool_call>\n<function=configure>\n<parameter=value>\n2\n</parameter>\n"
           "</function>\n</tool_call>",
           configure);
    report("D4 bare functions without any wrapper",
           "<function=configure>\n<parameter=value>\n1\n</parameter>\n</function>\n"
           "<function=configure>\n<parameter=value>\n2\n</parameter>\n</function>",
           configure);

    // 5. escaped / fenced / entity forms.
    report("E1 markdown fence around the call",
           "```\n<tool_call>\n<function=bash>\n<parameter=command>\nls\n</parameter>\n"
           "</function>\n</tool_call>\n```",
           bash);
    report("E2 HTML-escaped marker in prose only",
           "Use &lt;tool_call&gt; to call tools.", bash);
    report("E3 CDATA inside a declared string value",
           "<tool_call>\n<function=agent>\n<parameter=task>\n<![CDATA[keep <parameter=x> raw]]>\n"
           "</parameter>\n</function>\n</tool_call>",
           agent);
    report("E4 XML entities inside a declared string value",
           "<tool_call>\n<function=agent>\n<parameter=task>\na &lt; b &amp;&amp; c &gt; d\n"
           "</parameter>\n</function>\n</tool_call>",
           agent);

    // 6. mixed tag forms.
    report("F1 parameter '=' opener, 'name' attribute opener in one call",
           "<tool_call>\n<function=bash>\n<parameter=command>\nls\n</parameter>\n"
           "<parameter name=\"mode\">\nfast\n</parameter>\n</function>\n</tool_call>",
           bash);
    report("F2 function= opener closed by </invoke>",
           "<tool_call>\n<function=bash>\n<parameter=command>\nls\n</parameter>\n</invoke>\n"
           "</tool_call>",
           bash);
    report("F3 invoke opener closed by </function>",
           "<tool_call>\n<invoke name=\"bash\">\n<parameter name=\"command\">\nls\n</parameter>\n"
           "</function>\n</tool_call>",
           bash);
    report("F4 Qwen function form inside a function_calls container",
           "<function_calls>\n<function=bash>\n<parameter=command>\nls\n</parameter>\n"
           "</function>\n</function_calls>",
           bash);
    report("F5 tool_call wrapper inside function_calls container",
           "<function_calls>\n<tool_call>\n<function=bash>\n<parameter=command>\nls\n"
           "</parameter>\n</function>\n</tool_call>\n</function_calls>",
           bash);
    report("F6 <function NAME> with a space but no '=' or name attribute",
           "<tool_call>\n<function bash>\n<parameter=command>\nls\n</parameter>\n</function>\n"
           "</tool_call>",
           bash);

    // 7. names.
    report("G1 case-different undeclared name (declared Bash and bash, called BASH)",
           "<tool_call>\n<function=BASH>\n<parameter=command>\nls\n</parameter>\n</function>\n"
           "</tool_call>",
           case_pair);
    report("G2 tool name containing a space",
           "<tool_call>\n<function=my tool>\n<parameter=command>\nls\n</parameter>\n</function>\n"
           "</tool_call>",
           bash);
    report("G3 tool name with a slash", "<tool_call>\n<function=my/tool>\n</function>\n</tool_call>",
           bash);
    report("G4 non-ASCII tool name",
           "<tool_call>\n<function=\xE5\xB7\xA5\xE5\x85\xB7>\n</function>\n</tool_call>", bash);
    report("G5 name attribute with extra attributes before it",
           "<tool_call>\n<function filename=\"x\" name=\"bash\">\n<parameter name=\"command\">\nls\n"
           "</parameter>\n</function>\n</tool_call>",
           bash);

    // 8. parameters: missing, extra, reordered, repeated closers.
    report("H1 parameters in an order other than the schema's",
           "<tool_call>\n<function=agent>\n<parameter=mode>\nread\n</parameter>\n"
           "<parameter=task>\ndo it\n</parameter>\n</function>\n</tool_call>",
           agent);
    report("H2 extra undeclared parameter next to declared ones",
           "<tool_call>\n<function=configure>\n<parameter=value>\nx\n</parameter>\n"
           "<parameter=extra>\ny\n</parameter>\n</function>\n</tool_call>",
           configure);
    report("H3 parameter tag without a name",
           "<tool_call>\n<function=configure>\n<parameter=>\nx\n</parameter>\n</function>\n"
           "</tool_call>",
           configure);
    report("H4 duplicate parameter, conflicting values",
           "<tool_call>\n<function=configure>\n<parameter=value>\nfirst\n</parameter>\n"
           "<parameter=value>\nsecond\n</parameter>\n</function>\n</tool_call>",
           configure);
    report("H5 value containing </parameter> then real close (ambiguous closer)",
           "<tool_call>\n<function=configure>\n<parameter=value>\na\n</parameter>\nb\n"
           "</parameter>\n</function>\n</tool_call>",
           configure);

    // 9. legacy vs declared type normalization corner cases.
    report("I1 legacy policy with a JSON object value",
           "<tool_call>\n<function=t>\n<parameter=v>\n{\"x\":1}\n</parameter>\n</function>\n"
           "</tool_call>",
           legacy);
    report("I2 legacy policy with a bare true value",
           "<tool_call>\n<function=t>\n<parameter=v>\ntrue\n</parameter>\n</function>\n"
           "</tool_call>",
           legacy);
    report("I3 legacy policy with a bare null value",
           "<tool_call>\n<function=t>\n<parameter=v>\nnull\n</parameter>\n</function>\n"
           "</tool_call>",
           legacy);
    report("I4 legacy policy with a JSON array value",
           "<tool_call>\n<function=t>\n<parameter=v>\n[\"a\",2]\n</parameter>\n</function>\n"
           "</tool_call>",
           legacy);
    report("I5 declared integer receiving '007'",
           "<tool_call>\n<function=configure>\n<parameter=value>\n007\n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);
    report("I6 declared integer receiving '+7'",
           "<tool_call>\n<function=configure>\n<parameter=value>\n+7\n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);
    report("I7 declared integer receiving '0x10'",
           "<tool_call>\n<function=configure>\n<parameter=value>\n0x10\n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);
    report("I8 declared integer receiving a 20-digit integer",
           "<tool_call>\n<function=configure>\n<parameter=value>\n12345678901234567890\n</parameter>\n"
           "</function>\n</tool_call>",
           declared_int);
    report("I9 declared integer receiving '1e400'",
           "<tool_call>\n<function=configure>\n<parameter=value>\n1e400\n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);
    report("I10 declared integer receiving '1E+2'",
           "<tool_call>\n<function=configure>\n<parameter=value>\n1E+2\n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);
    report("I11 declared integer receiving ' 7 ' with surrounding spaces",
           "<tool_call>\n<function=configure>\n<parameter=value>\n 7 \n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);
    report("I12 declared integer receiving an empty value",
           "<tool_call>\n<function=configure>\n<parameter=value>\n</parameter>\n</function>\n"
           "</tool_call>",
           declared_int);

    // 10. marker repetition: broken first region, real call after it.
    report("J1 broken first call, complete second call",
           "<tool_call>\n<function=configure>\n<parameter=value>\nleaked\n</tool_call>\n"
           "<tool_call>\n<function=configure>\n<parameter=value>\nok\n</parameter>\n</function>\n"
           "</tool_call>",
           configure);
    report("J2 complete call, then a second complete call",
           "<tool_call>\n<function=configure>\n<parameter=value>\n1\n</parameter>\n</function>\n"
           "</tool_call>\nNow also:\n<tool_call>\n<function=configure>\n<parameter=value>\n2\n"
           "</parameter>\n</function>\n</tool_call>",
           configure);
    report("J3 prose quoting the opener, then a real call",
           "Avoid `<tool_call>\n<function=NAME>`; then real:\n<tool_call>\n<function=configure>\n"
           "<parameter=value>\nok\n</parameter>\n</function>\n</tool_call>",
           configure);
    report("J4 TaskCreate plan repro with the declared tool",
           "Plan ready:\n<tool_call>\n<function name=\"TaskCreate\">\n"
           "<parameter name=\"description\">\ndo it\n</parameter>\n</function>\n</tool_call>",
           task);

    std::cout << "probe done\n";
    return 0;
}
