"""
Shared thin wrapper around aisuite for structured (JSON) LLM calls and an agentic
tool-call loop, used across the job-search-agent pipeline.
"""

import json
import re

import aisuite as ai

EXTRACTION_MODEL = "anthropic:claude-haiku-4-5-20251001"
EXTRACTION_MODEL_MAX_TOKENS = 4096

# Rubric compilation (draft + reflect) is the one place where regex/criteria quality
# justifies a stronger, pricier model; the rest of the pipeline stays on EXTRACTION_MODEL.
RUBRIC_MODEL = "anthropic:claude-sonnet-5"


def _provider_kwargs(model):
    """ per-provider extra request kwargs. Anthropic 'claude-*-5'-gen models emit extended-thinking
        blocks by default, which aisuite's response converter can't parse (it reads content[0].text
        and chokes on a leading ThinkingBlock) - explicitly disable thinking so replies are plain text.
    """
    if model.startswith("anthropic:"):
        return {"thinking": {"type": "disabled"}}
    return {}


def _parse_json_reply(content):
    """ extract JSON from a model reply that may include a code fence and/or leading prose """
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence_match:
        content = fence_match.group(1)
    else:
        brace_match = re.search(r"\{.*\}", content, re.DOTALL)
        if brace_match:
            content = brace_match.group(0)
    return json.loads(content.strip())


def ask_json(prompt, max_tokens=1024, model=EXTRACTION_MODEL):
    """ send a prompt to the given model (default extraction model) and parse its JSON reply """
    client = ai.Client()
    messages = [{"role": "user", "content": prompt}]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        **_provider_kwargs(model),
    )
    return _parse_json_reply(response.choices[0].message.content)


def ask_json_with_tools(prompt, tools, tool_names, max_tokens=1024, max_iterations=10, model=EXTRACTION_MODEL):
    """ run an agentic tool-call loop, letting the given model (default extraction model) call the
        given tools before answering.
        `tools` is a {name: {"spec": <tool schema>, "impl": <callable>}} registry owned by the caller.
    """
    client = ai.Client()
    tool_specs = [tools[name]["spec"] for name in tool_names]
    messages = [{"role": "user", "content": prompt}]

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_specs,
            max_tokens=max_tokens,
            **_provider_kwargs(model),
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return _parse_json_reply(message.content)

        messages.append({"role": "assistant", "content": message.content, "tool_calls": message.tool_calls})
        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
            result = tools[tool_call.function.name]["impl"](**args)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(result)})

    raise RuntimeError("tool-call loop did not converge within max_iterations")
