from urllib.parse import urlencode

from flask import current_app, session
from requests_oauthlib import OAuth1Session

wiki_hostname = "en.wikipedia.org"
api_url = f"https://{wiki_hostname}/w/api.php"


def get_edit_proxy() -> dict[str, str]:
    """Retrieve proxy information from config."""
    edit_proxy = current_app.config.get("EDIT_PROXY")
    if edit_proxy:
        return {"http": edit_proxy, "https": edit_proxy}
    else:
        return {}


def api_post_request(params: dict[str, str | int]):
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
    proxies = get_edit_proxy()
    return oauth.post(api_url, data=params, timeout=10, proxies=proxies)


def raw_request(params):
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
    proxies = get_edit_proxy()
    return oauth.get(url, timeout=10, proxies=proxies)


def api_request(params):
    return raw_request(params).json()


def get_token():
    params = {
        "action": "query",
        "meta": "tokens",
        "format": "json",
        "formatversion": 2,
    }
    reply = api_request(params)
    token = reply["query"]["tokens"]["csrftoken"]

    return token


def userinfo_call():
    """Request user information via OAuth."""
    params = {"action": "query", "meta": "userinfo", "format": "json"}
    return api_request(params)


def get_username():
    if "owner_key" not in session:
        return  # not authorized

    if "username" in session:
        return session["username"]

    reply = userinfo_call()
    if "query" not in reply:
        return
    session["username"] = reply["query"]["userinfo"]["name"]

    return session["username"]
