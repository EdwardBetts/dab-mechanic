#!/usr/bin/python3

import inspect
import json
import re
import sys
import traceback
from typing import Optional, TypedDict

import flask
import lxml.html
import mwparserfromhell
import requests
import werkzeug.exceptions
from requests_oauthlib import OAuth1Session
from werkzeug.debug.tbtools import DebugTraceback
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
def exception_handler(e: werkzeug.exceptions.InternalServerError) -> tuple[str, int]:
    """Handle exception."""
    exec_type, exc_value, current_traceback = sys.exc_info()
    assert exc_value
    tb = DebugTraceback(exc_value)

    summary = tb.render_traceback_html(include_title=False)
    exc_lines = "".join(tb._te.format_exception_only())

    last_frame = list(traceback.walk_tb(current_traceback))[-1][0]
    last_frame_args = inspect.getargs(last_frame.f_code)

    return (
        flask.render_template(
            "show_error.html",
            plaintext=tb.render_traceback_text(),
            exception=exc_lines,
            exception_type=tb._te.exc_type.__name__,
            summary=summary,
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
def index() -> str | Response:
    """Index page."""
    title = flask.request.args.get("title")
    exists = None
    if title:
        title = title.strip()
        exists = mediawiki_api.article_exists(title)
        if exists:
            return flask.redirect(
                flask.url_for("article_page", enwiki=title.replace(" ", "_"))
            )

    r = requests.get(awdl_url, params={"limit": 100})
    root = lxml.html.fromstring(r.content)
    articles = parse_articles_with_dab_links(root)

    # articles = [line[:-1] for line in open("article_list")]

    return flask.render_template(
        "index.html",
        title=title,
        exists=exists,
        articles=articles,
    )


class Edit(TypedDict):
    """Edit to an article."""

    num: int
    link_to: str
    title: str


def old_apply_edits(article_text: str, edits: list[Edit]) -> str:
    """Apply edits to article text."""

    def escape(s: str) -> str:
        return re.escape(s).replace("_", "[ _]").replace(r"\ ", "[ _]")

    for edit in edits:
        # print(rf"\[\[{escape(link_from)}\]\]")
        article_text = re.sub(
            rf"\[\[{escape(link_from)}\]\]",
            f"[[{link_to}|{link_from}]]",
            article_text,
        )

    return article_text


def make_disamb_link(edit: Edit) -> str:
    """Given an edit return the appropriate link."""
    return f"[[{edit['title']}|{edit['link_to']}]]"


def build_edit_summary(edits: list[Edit]) -> str:
    """Given a list of edits return an edit summary."""
    titles = ", ".join(make_disamb_link(edit) for edit in edits[:-1])
    if len(titles) > 1:
        titles += " and "

    titles += make_disamb_link(edits[-1])

    return f"Disambiguate {titles} using [[User:Edward/Dab mechanic]]"


def get_links(wikicode, dab_links):
    edits = [edit for edit in dab_links if edit.get("title")]

    dab_titles = {dab["link_to"] for dab in edits}
    return [
        link for link in wikicode.filter_wikilinks() if str(link.title) in dab_titles
    ]


def apply_edits(text, dab_links):
    wikicode = mwparserfromhell.parse(text)
    links = get_links(wikicode, dab_links)
    if len(links) != len(dab_links):
        print("links:", len(links))
        print("dab_links:", len(dab_links))
        print("dab_links:", dab_links)
    assert len(links) == len(dab_links)

    for wikilink, edit in zip(links, dab_links):
        if not edit.get("title"):
            continue
        if not wikilink.text:
            wikilink.text = wikilink.title
        wikilink.title = edit["title"]

    return str(wikicode)


@app.route("/preview/<path:enwiki>", methods=["POST"])
def preview(enwiki: str) -> Response | str:
    """Preview article edits."""
    enwiki = enwiki.replace("_", " ")

    dab_links = json.loads(flask.request.form["edits"])
    dab_links = [link for link in dab_links if "title" in link]
    cur_text, baserevid = mediawiki_api.get_content(enwiki)

    text = apply_edits(cur_text, dab_links)
    diff = mediawiki_api.compare(enwiki, text)

    return flask.render_template(
        "preview.html",
        edit_summary=build_edit_summary(dab_links),
        title=enwiki,
        edits=dab_links,
        diff=diff,
    )


def do_save(enwiki: str):
    """Update page on Wikipedia."""
    dab_links = json.loads(flask.request.form["edits"])
    dab_links = [link for link in dab_links if "title" in link]

    cur_text, baserevid = mediawiki_api.get_content(enwiki)

    new_text = apply_edits(cur_text, dab_links)
    token = wikidata_oauth.get_token()

    summary = build_edit_summary(dab_links)
    print(summary)

    edit = mediawiki_api.edit_page(
        title=enwiki,
        text=new_text,
        summary=summary,
        baserevid=baserevid,
        token=token,
    )

    return edit


@app.route("/save/<path:enwiki>", methods=["GET", "POST"])
def save(enwiki: str) -> Response | str:
    """Save edits to article."""
    enwiki_norm = enwiki.replace("_", " ")

    if flask.request.method == "GET":
        return flask.render_template("edit_saved.html", title=enwiki_norm)

    do_save(enwiki_norm)
    return flask.redirect(flask.url_for(flask.request.endpoint, enwiki=enwiki))


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

    if "owner_key" not in flask.session:
        return flask.render_template("login_needed.html")

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
