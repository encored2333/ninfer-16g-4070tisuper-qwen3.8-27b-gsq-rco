// G3 probe: does the streaming decoder lose or duplicate bytes at any chunk size?
#include "models/qwen3_5/frontend/tool_call_parser.h"

#include <nlohmann/json.hpp>

#include <iostream>
#include <memory>
#include <span>
#include <string>
#include <vector>

using Json = nlohmann::json;
namespace fi = ninfer::models::qwen3_5::frontend;

static std::string tool_definition(const std::string& tool_name, Json properties) {
    Json parameters{{"type", "object"}, {"properties", std::move(properties)}};
    return Json{{"type", "function"},
                {"function", Json{{"name", tool_name}, {"parameters", std::move(parameters)}}}}
        .dump();
}

static fi::ToolCallOutputContract contract_from(const std::vector<std::string>& defs) {
    return *fi::build_tool_call_output_contract(
        std::span<const std::string>(defs.data(), defs.size()), true);
}

int main() {
    const auto contract = contract_from(
        {tool_definition("configure", Json{{"value", Json{{"type", "string"}}}}),
         tool_definition("bash", Json{{"command", Json{{"type", "string"}}}})});

    const std::string call =
        "<tool_call>\n<function=configure>\n<parameter=value>\nx\n</parameter>\n</function>\n</tool_call>";
    const std::vector<std::pair<std::string, std::string>> cases = {
        {"plain prose", "the quick brown fox jumps over the lazy dog"},
        {"prose then call", "I will configure it now.\n" + call},
        {"bare call", call},
        {"two calls", call + "\n" + call},
        {"lone '<' characters", "a < b << c <f <fu <fun and nothing else"},
        {"unfinished marker", "prefix <tool_ca"},
        {"marker split", "prefix <tool_call>"},
        {"nested markup in value",
         "<tool_call>\n<function=configure>\n<parameter=value>\nliteral </function> and <parameter=x>\n"
         "</parameter>\n</function>\n</tool_call>"},
        {"cdata value",
         "<tool_call>\n<function=configure>\n<parameter=value>\n<![CDATA[ls -la]]>\n</parameter>\n"
         "</function>\n</tool_call>"},
        {"prose quoting bare function",
         "Use <function=configure>\n<parameter=value>\nx\n</parameter>\n</function> as the format."},
        {"whitespace before marker", "answer\n\n   " + call},
        {"angle soup", "<> << >> <x> </x> < / > <?"}};

    int failures = 0;
    for (const auto& [label, text] : cases) {
        const auto parsed = fi::parse_qwen_tool_call_output(text, 64, contract);
        for (std::size_t chunk = 1; chunk <= text.size() && chunk <= 23; ++chunk) {
            fi::ToolCallOutputDecoder decoder(
                std::make_shared<const fi::ToolCallOutputContract>(contract), 64);
            std::string visible;
            for (std::size_t offset = 0; offset < text.size(); offset += chunk) {
                visible += decoder.feed(std::string_view(text).substr(offset, chunk));
            }
            auto terminal = decoder.finish();
            const std::string streamed = visible + terminal.content;
            if (streamed != parsed.content) {
                ++failures;
                std::cout << "CONTENT MISMATCH [" << label << " chunk=" << chunk << "]\n"
                          << "  streamed=" << Json(streamed).dump() << "\n"
                          << "  parsed  =" << Json(parsed.content).dump() << "\n";
                break;
            }
            if (terminal.tool_calls.size() != parsed.tool_calls.size()) {
                ++failures;
                std::cout << "CALL COUNT MISMATCH [" << label << " chunk=" << chunk << "] streamed="
                          << terminal.tool_calls.size() << " parsed=" << parsed.tool_calls.size()
                          << "\n";
                break;
            }
        }
    }
    std::cout << (failures == 0 ? "G3: no byte loss/duplication at any chunk size"
                                : "G3: FAILURES=" + std::to_string(failures))
              << "\n";
    return failures == 0 ? 0 : 1;
}
