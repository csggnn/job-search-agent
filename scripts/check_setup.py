"""
Environment smoke-check (not a unit test): confirms API keys and aisuite/Tavily wiring
work by running a Tavily search and sending the same context to Anthropic and Groq.
Run with: python scripts/check_setup.py
"""

import os
from dotenv import load_dotenv
from tavily import TavilyClient
import aisuite as ai

load_dotenv()

QUERY = "What is the current state of AI agent frameworks in 2025?"

MODELS = [
    "anthropic:claude-haiku-4-5-20251001",
    "groq:llama-3.3-70b-versatile",
]


def search(query: str) -> str:
    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
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
        max_tokens=256,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    print("=== Tavily search ===")
    context = search(QUERY)
    print(context[:400], "...\n")

    client = ai.Client()

    for model in MODELS:
        print(f"=== {model} ===")
        answer = ask(client, model, context, QUERY)
        print(answer, "\n")
