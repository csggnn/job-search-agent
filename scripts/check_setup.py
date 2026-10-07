"""
Environment smoke-check (not a unit test): reports missing user data files, missing or empty
job preferences sections and API keys missing from the environment, then confirms API keys
and aisuite/Tavily wiring work by running a Tavily search and sending the same context to
Anthropic and Groq. Exits 1 when a key is missing, before any API call, or after the API
calls when user data is incomplete.
Run with: python scripts/check_setup.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tavily import TavilyClient
import aisuite as ai

from jobsearch import config

QUERY = "What is the current state of AI agent frameworks in 2025?"

MODELS = [
    "anthropic:claude-haiku-4-5-20251001",
    "groq:openai/gpt-oss-120b",
]


def search(query: str) -> str:
    tavily = TavilyClient(api_key=config.require_env("TAVILY_API_KEY"))
    results = tavily.search(query, max_results=3)
    return "\n\n".join(r["content"] for r in results["results"])


def ask(client: ai.Client, model: str, context: str, query: str) -> str:
    messages = [
        {
            "role": "user",
            "content": (
                f"Based on the search results below, give a two-sentence answer to: '{query}'\n\n"
                f"{context}"
            ),
        }
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
    )
    return response.choices[0].message.content


def check_data():
    """ print the missing user data files and job preferences sections. returns True if none """
    missing = config.missing_data_files()
    preferences = (None if config.JOB_PREFERENCES_PATH in missing
                   else config.read_job_preferences())
    problems = config.data_problems(missing, preferences)
    for problem in problems:
        print(f"MISSING: {problem}")
    if not problems:
        print("OK: resume and job preferences are complete")
    return not problems


def check_keys():
    """ print the API keys missing from the environment. returns True if none """
    missing = [name for name in config.API_KEYS if not config.get_env(name)]
    for name in missing:
        print(f"MISSING: {name} is not set in {config.KEYS_FILE}")
    if not missing:
        print("OK: every API key is set")
    return not missing


if __name__ == "__main__":
    print("=== Setup ===")
    data_ok = check_data()
    if not check_keys():
        sys.exit(1)
    print()

    print("=== Tavily search ===")
    context = search(QUERY)
    print(context[:400], "...\n")

    client = ai.Client()

    for model in MODELS:
        print(f"=== {model} ===")
        answer = ask(client, model, context, QUERY)
        print(answer, "\n")

    if not data_ok:
        sys.exit(1)
