"""Interface with the mediawiki API."""

from typing import Any
from . import wikidata_oauth

wiki_hostname = "en.wikipedia.org"
wiki_api_php = f"https://{wiki_hostname}/w/api.php"
user_agent = "dab-mechanic/0.1"


def parse_page(enwiki: str) -> dict[str, Any]:
    """Call mediawiki parse API for given article."""
    params: dict[str, str | int] = {
        "action": "parse",
        "format": "json",
        "formatversion": 2,
        "disableeditsection": 1,
        "page": enwiki,
        "prop": "text|links|headhtml",
        "disabletoc": 1,
    }

    parse: dict[str, Any] = call(params)["parse"]
    return parse


def call(params: dict[str, str | int]) -> dict[str, Any]:
    """Make GET request to mediawiki API."""
    data: dict[str, Any] = wikidata_oauth.api_post_request(params)
    return data.json()


def get_content(title: str) -> str:
    """Get article text."""
    params: dict[str, str | int] = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "revisions|info",
        "rvprop": "content|timestamp",
        "titles": title,
    }
    data = call(params)
    rev: str = data["query"]["pages"][0]["revisions"][0]["content"]
    return rev


def compare(title: str, new_text: str) -> str:
    """Generate a diff for the new article text."""
    params: dict[str, str | int] = {
        "format": "json",
        "formatversion": 2,
        "action": "compare",
        "fromtitle": title,
        "toslots": "main",
        "totext-main": new_text,
        "prop": "diff",
    }
    diff: str = call(params)["compare"]["body"]
    return diff
