"""Wikidata OAuth."""

import typing
from urllib.parse import urlencode

from flask import current_app, session
from requests.models import Response
from requests_oauthlib import OAuth1Session

wiki_hostname = "en.wikipedia.org"
api_url = f"https://{wiki_hostname}/w/api.php"

CallParams = dict[str, str | int]


def get_edit_proxy() -> dict[str, str]:
    """Retrieve proxy information from config."""
    edit_proxy = current_app.config.get("EDIT_PROXY")
    if edit_proxy:
        return {"http": edit_proxy, "https": edit_proxy}
    else:
        return {}


def api_post_request(params: CallParams) -> Response:
    """HTTP Post using Oauth."""
    app = current_app
    client_key = app.config["CLIENT_KEY"]
    client_secret = app.config["CLIENT_SECRET"]
    oauth = OAuth1Session(
        client_key,
        client_secret=client_secret,
        resource_owner_key=session["owner_key"],
        resource_owner_secret=session["owner_secret"],
    )
    r: Response = oauth.post(api_url, data=params, timeout=10, proxies=get_edit_proxy())
    return r


def raw_request(params: CallParams) -> Response:
    """Raw request."""
    app = current_app
    url = api_url + "?" + urlencode(params)
    client_key = app.config["CLIENT_KEY"]
    client_secret = app.config["CLIENT_SECRET"]
    oauth = OAuth1Session(
        client_key,
        client_secret=client_secret,
        resource_owner_key=session["owner_key"],
        resource_owner_secret=session["owner_secret"],
    )
    r: Response = oauth.get(url, timeout=10, proxies=get_edit_proxy())
    return r


def api_request(params: CallParams) -> dict[str, typing.Any]:
    """Make API request and return object parsed from JSON."""
    return typing.cast(dict[str, typing.Any], raw_request(params).json())


def get_token() -> str:
    """Get csrftoken from MediaWiki API."""
    params: CallParams = {
        "action": "query",
        "meta": "tokens",
        "format": "json",
        "formatversion": 2,
    }
    reply = api_request(params)
    token: str = reply["query"]["tokens"]["csrftoken"]

    return token


def userinfo_call() -> dict[str, typing.Any]:
    """Request user information via OAuth."""
    params: CallParams = {"action": "query", "meta": "userinfo", "format": "json"}
    return api_request(params)


def get_username() -> str | None:
    """Get username for current user."""
    if "owner_key" not in session:
        return None  # not authorized

    if "username" in session:
        assert isinstance(session["username"], str)
        return session["username"]

    reply = userinfo_call()
    if "query" not in reply:
        return None
    username = reply["query"]["userinfo"]["name"]
    assert isinstance(username, str)
    session["username"] = username

    return username
