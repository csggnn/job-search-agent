"""
Location and commute scoring: resolving an employer's office address for a job posting
and computing a commute score weighted by required in-office days per week.
"""

import os
import re

import requests
from tavily import TavilyClient
from dotenv import load_dotenv

from llm import _ask_json

load_dotenv()

ORS_API_KEY = os.environ["ORS_API_KEY"]
HOME_ADDRESS = os.environ["HOME_ADDRESS"]
ORS_BASE_URL = "https://api.openrouteservice.org"
FULLY_REMOTE = "Fully Remote"


def classify_location(company, location, debug=False):
    """ decide whether location is already a full address, a generic place name, or remote """
    result = _ask_json(
        "You are given a job posting's company name and its raw location text.\n"
        f"Company: {company}\n"
        f"Location: {location}\n\n"
        'Respond with only a JSON object with keys "status" and "address":\n'
        '"status" must hold one of the following 3 options:\n'
        '- "remote": the job is fully remote, no office attendance is required. Set "address" to null.\n'
        '- "full_address": the location text already contains a specific street-level '
        'address (street name and number), not just a city/region/country. Set '
        '"address" to that address.\n'
        '- "generic": the location text only names a city/region/country without a '
        'specific street address. Set "address" to null.\n',
        max_tokens=256,
    )
    if debug:
        print(f"[classify_location] company={company!r} location={location!r} -> {result}")
    return result


def search_office_address(company, location, debug=False):
    """ search the web for the company's office address, using location as a discriminator """
    # LinkedIn appends "Metropolitan Area" to location text when it lacks a precise city;
    # it's noise for search (not a real geographic term) and dilutes results toward
    # unrelated same-named companies rather than helping narrow down the right one.
    clean_location = re.sub(r"\s*Metropolitan Area\s*$", "", location, flags=re.IGNORECASE)

    # A plain "company + location" query tends to surface the company's own site; adding
    # search-engine-y terms like "headquarters office address" instead biases results
    # toward directory/aggregator sites that rarely have a real street address.
    query = f"{company} {clean_location}"
    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    results = tavily.search(query, max_results=5)
    urls = [r["url"] for r in results["results"]]
    if debug:
        print(f"[search_office_address] query={query!r}")
        print(f"[search_office_address] candidate urls: {urls}")

    # Addresses usually live in a page footer/contact section, which search snippets
    # truncate away. Extracting full page content from the top candidates catches those.
    extracted = tavily.extract(urls[:3], format="text")
    context = "\n\n---\n\n".join(
        f"{r['url']}\n{r['raw_content']}" for r in extracted["results"]
    )
    if debug:
        print(f"[search_office_address] extracted {len(extracted['results'])} pages:\n{context}\n")
    return context


def resolve_office_address(company, location, search_context, debug=False):
    """ pick the office address matching location out of the search results """
    result = _ask_json(
        f"Company: {company}\n"
        f"Known location (city/region) - use this to pick the right office if the "
        f"company has multiple locations: {location}\n\n"
        f"Search results:\n{search_context}\n\n"
        "Find the company's full street-level office address that matches the given "
        'location. Respond with only a JSON object: {"address": <full address string, '
        "or null if it can't be determined from the search results>}.",
        max_tokens=256,
    )
    if debug:
        print(f"[resolve_office_address] -> {result}")
    return result["address"]


def figure_address(company, location, debug=False):
    """ return a full street address for company/location, or FULLY_REMOTE if no office applies """
    classification = classify_location(company, location, debug=debug)

    if classification["status"] == "remote":
        return FULLY_REMOTE
    if classification["status"] == "full_address" and classification["address"]:
        return classification["address"]

    search_context = search_office_address(company, location, debug=debug)
    return resolve_office_address(company, location, search_context, debug=debug)


def figure_days_on_office(description):
    """ return the required number of on-site office days per week (0-5) """
    result = _ask_json(
        "You are given a job posting's location text and full description. Determine "
        "how many days per week on-site office attendance is required.\n"
        f"Description:\n{description}\n\n"
        'Respond with only text representing a single integer 0-5.\n'
        "- 0 means fully remote, no office attendance required.\n"
        "- 5 means fully in-office / on-site every day.\n"
        "- For hybrid roles, use the number of required in-office days per week explicitly "
        'stated (e.g. "3 days a week", "hybrid 2 days/week").\n'
        "- if the job location is hybrid but no specific number of days is stated, use 4.\n"
        "- If nothing about remote/hybrid/on-site policy is mentioned at all, use 5 as the "
        "conservative default."
        "double check that your reply is text representing a single integer with no other added comment",
        max_tokens=256,
    )
    return result


def improve_for_geocode(address):
    """ improve a free-form address string for geocoding by adding city/state/country if missing """
    result = _ask_json(
        f"This address failed a geocoding attempt: {address!r}\n\n"
        "Improve it so that it includes the city, state, and country if they are missing, "
        "and remove any parts that are not relevant to geocoding (e.g. building/company "
        "names, floor or suite numbers).\n\n"
        'Respond with only a JSON object: {"address": <improved address string>}.',
        max_tokens=256,
    )
    return result["address"]


def geocode_address(address):
    """ return (longitude, latitude) for a free-form address string """

    for attempt in range(2):
        if attempt > 0:
            address = improve_for_geocode(address)
        response = requests.get(
            f"{ORS_BASE_URL}/geocode/search",
            params={"api_key": ORS_API_KEY, "text": address, "size": 1},
            timeout=10,
        )
        response.raise_for_status()
        features = response.json()["features"]
        if features:
            break
        else: 
            if attempt>0:
                raise ValueError(f"could not geocode address: {address}")
    return features[0]["geometry"]["coordinates"]


def commute_route(address, profile="driving-car"):
    """ return (duration_minutes, distance_km) from HOME_ADDRESS to address """
    origin = geocode_address(HOME_ADDRESS)
    destination = geocode_address(address)

    response = requests.get(
        f"{ORS_BASE_URL}/v2/directions/{profile}",
        params={
            "api_key": ORS_API_KEY,
            "start": f"{origin[0]},{origin[1]}",
            "end": f"{destination[0]},{destination[1]}",
        },
        timeout=10,
    )
    response.raise_for_status()
    segment = response.json()["features"][0]["properties"]["segments"][0]
    return segment["duration"] / 60, segment["distance"] / 1000


def commute_time(address, profile="driving-car"):
    """ return commute time in minutes """
    duration, _ = commute_route(address, profile)
    return duration


def commute_score(company, location, description, debug=False):
    """commute_score is the commute time for companies requiring 3 or 4 days from office.
       for fully in office, multiply by 1.5
       for <3 days on office, commute score is commute_time * days-on-office / 3.
       fully remote jobs have no commute, so their score is 0.
       returns {"score": float, "days_on_office": int, "address": str,
                "raw_minutes": float|None, "distance_km": float|None}
    """
    days_on_office = int(figure_days_on_office(description))

    if days_on_office <= 0:
        return {"score": 0, "days_on_office": days_on_office, "address": FULLY_REMOTE,
                "raw_minutes": None, "distance_km": None}

    address = figure_address(company, location, debug=debug)
    if address == FULLY_REMOTE:
        return {"score": 0, "days_on_office": days_on_office, "address": FULLY_REMOTE,
                "raw_minutes": None, "distance_km": None}
    if not address:
        return {"score": None, "days_on_office": days_on_office, "address": None,
                "raw_minutes": None, "distance_km": None}

    time, distance = commute_route(address)

    if days_on_office >= 5:
        score = time * 1.5
    elif days_on_office in (3, 4):
        score = time
    else:
        score = time * days_on_office / 3

    return {"score": score, "days_on_office": days_on_office, "address": address,
            "raw_minutes": time, "distance_km": distance}
