#!/usr/bin/python3

import inspect
import json
import re
from typing import Optional

import flask
import lxml.html
import requests
import werkzeug.exceptions
from requests_oauthlib import OAuth1Session
from werkzeug.debug.tbtools import get_current_traceback
from werkzeug.wrappers import Response

from dab_mechanic import mediawiki_api, wikidata_oauth, wikipedia

app = flask.Flask(__name__)
app.config.from_object("config.default")

wiki_hostname = "en.wikipedia.org"
wiki_api_php = f"https://{wiki_hostname}/w/api.php"
wiki_index_php = f"https://{wiki_hostname}/w/index.php"

awdl_url = "https://dplbot.toolforge.org/articles_with_dab_links.php"


@app.before_request
def global_user() -> None:
    """Make username available everywhere."""
    flask.g.user = wikidata_oauth.get_username()


@app.errorhandler(werkzeug.exceptions.InternalServerError)
def exception_handler(e):
    tb = get_current_traceback()
    last_frame = next(frame for frame in reversed(tb.frames) if not frame.is_library)
    last_frame_args = inspect.getargs(last_frame.code)
    return (
        flask.render_template(
            "show_error.html",
            tb=tb,
            last_frame=last_frame,
            last_frame_args=last_frame_args,
        ),
        500,
    )


def parse_articles_with_dab_links(root: lxml.html.HtmlElement) -> list[tuple[str, int]]:
    """Parse Articles With Multiple Dablinks."""
    articles = []
    table = root.find(".//table")
    assert table is not None
    for tr in table:
        title = tr[0][0].text
        count_text = tr[1][0].text
        assert title and count_text and count_text.endswith(" links")
        count = int(count_text[:-6])

        articles.append((title, count))

    return articles


@app.route("/")
def index() -> str:
    """Index page."""
    r = requests.get(awdl_url, params={"limit": 100})
    root = lxml.html.fromstring(r.content)
    articles = parse_articles_with_dab_links(root)

    # articles = [line[:-1] for line in open("article_list")]

    return flask.render_template("index.html", articles=articles)


def make_disamb_link(edit: tuple[str, str]) -> str:
    """Given an edit return the appropriate link."""
    return f"[[{edit[1]}|{edit[0]}]]"


def apply_edits(article_text: str, edits: list[tuple[str, str]]) -> str:
    """Apply edits to article text."""

    def escape(s: str) -> str:
        return re.escape(s).replace("_", "[ _]").replace(r"\ ", "[ _]")

    for link_from, link_to in edits:
        print(rf"\[\[{escape(link_from)}\]\]")
        article_text = re.sub(
            rf"\[\[{escape(link_from)}\]\]",
            f"[[{link_to}|{link_from}]]",
            article_text,
        )

    return article_text


@app.route("/save/<path:enwiki>", methods=["POST"])
def save(enwiki: str) -> Response | str:
    """Save edits to article."""
    edits = [
        (link_to, link_from)
        for link_to, link_from in json.loads(flask.request.form["edits"])
    ]

    enwiki = enwiki.replace("_", " ")
    titles = ", ".join(make_disamb_link(edit) for edit in edits[:-1])
    if len(titles) > 1:
        titles += " and "

    titles += make_disamb_link(edits[-1])

    edit_summary = f"Disambiguate {titles} using [[User:Edward/Dab mechanic]]"

    article_text = apply_edits(mediawiki_api.get_content(enwiki), edits)

    return flask.render_template(
        "save.html",
        edit_summary=edit_summary,
        title=enwiki,
        edits=edits,
        text=article_text,
    )


def redirect_if_needed(enwiki: str) -> Optional[Response]:
    """Check if there are spaces in the article name and redirect."""
    endpoint = flask.request.endpoint
    assert endpoint
    return (
        flask.redirect(flask.url_for(endpoint, enwiki=enwiki.replace(" ", "_")))
        if " " in enwiki
        else None
    )


@app.route("/enwiki/<path:enwiki>")
def article_page(enwiki: str) -> Response | str:
    """Article Page."""
    redirect = redirect_if_needed(enwiki)
    if redirect:
        return redirect

    article = wikipedia.Article(enwiki)
    article.load()
    article.process_links()

    assert article.parse

    return flask.render_template("article.html", article=article)


@app.route("/oauth/start")
def start_oauth() -> Response:
    """Start OAuth."""
    next_page = flask.request.args.get("next")
    if next_page:
        flask.session["after_login"] = next_page

    client_key = app.config["CLIENT_KEY"]
    client_secret = app.config["CLIENT_SECRET"]
    request_token_url = wiki_index_php + "?title=Special%3aOAuth%2finitiate"

    oauth = OAuth1Session(client_key, client_secret=client_secret, callback_uri="oob")
    fetch_response = oauth.fetch_request_token(request_token_url)

    flask.session["owner_key"] = fetch_response.get("oauth_token")
    flask.session["owner_secret"] = fetch_response.get("oauth_token_secret")

    base_authorization_url = f"https://{wiki_hostname}/wiki/Special:OAuth/authorize"
    authorization_url = oauth.authorization_url(
        base_authorization_url, oauth_consumer_key=client_key
    )
    return flask.redirect(authorization_url)


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback() -> Response:
    """Autentication callback."""
    client_key = app.config["CLIENT_KEY"]
    client_secret = app.config["CLIENT_SECRET"]

    oauth = OAuth1Session(
        client_key,
        client_secret=client_secret,
        resource_owner_key=flask.session["owner_key"],
        resource_owner_secret=flask.session["owner_secret"],
    )

    oauth_response = oauth.parse_authorization_response(flask.request.url)
    verifier = oauth_response.get("oauth_verifier")
    access_token_url = wiki_index_php + "?title=Special%3aOAuth%2ftoken"
    oauth = OAuth1Session(
        client_key,
        client_secret=client_secret,
        resource_owner_key=flask.session["owner_key"],
        resource_owner_secret=flask.session["owner_secret"],
        verifier=verifier,
    )

    oauth_tokens = oauth.fetch_access_token(access_token_url)
    flask.session["owner_key"] = oauth_tokens.get("oauth_token")
    flask.session["owner_secret"] = oauth_tokens.get("oauth_token_secret")

    next_page = flask.session.get("after_login")
    return flask.redirect(next_page if next_page else flask.url_for("index"))


@app.route("/oauth/disconnect")
def oauth_disconnect() -> Response:
    """Disconnect OAuth."""
    for key in "owner_key", "owner_secret", "username", "after_login":
        if key in flask.session:
            del flask.session[key]
    return flask.redirect(flask.url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0")
