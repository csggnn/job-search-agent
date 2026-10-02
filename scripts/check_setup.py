"""
Environment smoke-check (not a unit test): reports API keys missing from the environment
and job_preferences.md sections missing from the active profile, then confirms the API
keys and aisuite/Tavily wiring work by running a Tavily search and sending the same context
to Anthropic and Groq.
Run with: python scripts/check_setup.py [--default-profile]
"""

import argparse
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


def check_profile(profile):
    """ print the job_preferences.md sections missing from `profile`. returns True if none """
    path = profile.job_preferences_path
    missing = config.missing_preference_sections(profile.read_job_preferences())
    for heading in missing:
        print(f"MISSING: '## {heading}' is missing or empty in {path}")
    if not missing:
        print(f"OK: {path} fills every section the pipeline reads")
    return not missing


def check_keys():
    """ print the API keys missing from the environment. returns True if none """
    missing = [name for name in config.API_KEYS if not config.get_env(name)]
    for name in missing:
        print(f"MISSING: {name} is not set in {config.KEYS_FILE}")
    if not missing:
        print("OK: every API key is set")
    return not missing


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    config.add_profile_argument(parser)
    args = parser.parse_args()
    profile = config.profile_from_args(args)

    print("=== Setup ===")
    profile_ok = check_profile(profile)
    keys_ok = check_keys()
    if not (profile_ok and keys_ok):
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
