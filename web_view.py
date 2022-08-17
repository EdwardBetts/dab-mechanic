#!/usr/bin/python3

import inspect
import json
import re
from typing import Any, Iterator, Optional, TypedDict

import flask
import lxml.html
import requests
import werkzeug.exceptions
from requests_oauthlib import OAuth1Session
from werkzeug.debug.tbtools import get_current_traceback
from werkzeug.wrappers import Response

from dab_mechanic import wikidata_oauth

app = flask.Flask(__name__)
app.config.from_object("config.default")
app.debug = True

wiki_hostname = "en.wikipedia.org"
wiki_api_php = f"https://{wiki_hostname}/w/api.php"
wiki_index_php = f"https://{wiki_hostname}/w/index.php"

awdl_url = "https://dplbot.toolforge.org/articles_with_dab_links.php"


@app.before_request
def global_user():
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
    data = requests.get(wiki_api_php, params=params).json()
    rev: str = data["query"]["pages"][0]["revisions"][0]["content"]
    return rev


def parse_articles_with_dab_links(root: lxml.html.Element) -> list[tuple[str, int]]:
    """Parse Articles With Multiple Dablinks."""
    articles = []
    table = root.find(".//table")
    for tr in table:
        title = tr[0][0].text
        count_text = tr[1][0].text
        assert count_text.endswith(" links")
        count = int(count_text[:-6])

        articles.append((title, count))

    return articles


@app.route("/")
def index():
    r = requests.get(awdl_url, params={"limit": 100})
    root = lxml.html.fromstring(r.content)
    articles = parse_articles_with_dab_links(root)

    # articles = [line[:-1] for line in open("article_list")]

    return flask.render_template("index.html", articles=articles)


def call_parse_api(enwiki: str) -> dict[str, Any]:
    """Call mediawiki parse API for given article."""
    url = "https://en.wikipedia.org/w/api.php"

    params: dict[str, str | int] = {
        "action": "parse",
        "format": "json",
        "formatversion": 2,
        "disableeditsection": 1,
        "page": enwiki,
        "prop": "text|links|headhtml",
        "disabletoc": 1,
    }

    r = requests.get(url, params=params)
    parse: dict[str, Any] = r.json()["parse"]
    return parse


def get_article_html(enwiki: str) -> str:
    """Parse article wikitext and return HTML."""
    text: str = call_parse_api(enwiki)["text"]
    return text


disambig_templates = [
    "Template:Disambiguation",
    "Template:Airport disambiguation",
    "Template:Biology disambiguation",
    "Template:Call sign disambiguation",
    "Template:Caselaw disambiguation",
    "Template:Chinese title disambiguation",
    "Template:Disambiguation cleanup",
    "Template:Genus disambiguation",
    "Template:Hospital disambiguation",
    "Template:Human name disambiguation",
    "Template:Human name disambiguation cleanup",
    "Template:Letter-number combination disambiguation",
    "Template:Mathematical disambiguation",
    "Template:Military unit disambiguation",
    "Template:Music disambiguation",
    "Template:Number disambiguation",
    "Template:Opus number disambiguation",
    "Template:Phonetics disambiguation",
    "Template:Place name disambiguation",
    "Template:Portal disambiguation",
    "Template:Road disambiguation",
    "Template:School disambiguation",
    "Template:Species Latin name abbreviation disambiguation",
    "Template:Species Latin name disambiguation",
    "Template:Station disambiguation",
    "Template:Synagogue disambiguation",
    "Template:Taxonomic authority disambiguation",
    "Template:Taxonomy disambiguation",
    "Template:Template disambiguation",
    "Template:WoO number disambiguation",
]


def link_params(enwiki: str) -> dict[str, str | int]:
    """Parameters for finding article links from the API."""
    params: dict[str, str | int] = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "titles": enwiki,
        "generator": "links",
        "gpllimit": "max",
        "gplnamespace": 0,
        "tllimit": "max",
        "tlnamespace": 10,
        "tltemplates": "|".join(disambig_templates),
        "prop": "templates",
    }
    return params


def needs_disambig(link: dict[str, Any]) -> bool:
    """Is this a disambiguation link."""
    return bool(
        not link["title"].endswith(" (disambiguation)") and link.get("templates")
    )


def get_article_links(enwiki: str) -> list[str]:
    """Get links that appear in this article."""
    url = "https://en.wikipedia.org/w/api.php"

    params: dict[str, str | int] = link_params(enwiki)
    links: set[str] = set()

    while True:
        data = requests.get(url, params=params).json()
        links.update(
            page["title"] for page in data["query"]["pages"] if needs_disambig(page)
        )

        if "continue" not in data:
            break

        params["gplcontinue"] = data["continue"]["gplcontinue"]

    return list(links)

    # return {link["title"] for link in r.json()["query"]["pages"][0]["links"]}


def delete_toc(root: lxml.html.HtmlElement) -> None:
    """Delete table of contents from article HTML."""
    for toc in root.findall(".//div[@class='toc']"):
        toc.getparent().remove(toc)


def get_dab_html(dab_num: int, title: str) -> str:
    """Parse dab page and rewrite links."""
    dab_html = get_article_html(title)
    root = lxml.html.fromstring(dab_html)
    delete_toc(root)

    element_id_map = {e.get("id"): e for e in root.findall(".//*[@id]")}

    for a in root.findall(".//a[@href]"):
        href: str | None = a.get("href")
        if not href:
            continue
        if not href.startswith("#"):
            a.set("href", "#")
            a.set("onclick", f"return select_dab(this, {dab_num})")
            continue

        destination_element = element_id_map[href[1:]]
        assert destination_element is not None
        destination_element.set("id", f"{dab_num}{href[1:]}")
        a.set("href", f"#{dab_num}{href[1:]}")

    html: str = lxml.html.tostring(root, encoding=str)
    return html


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

    article_text = apply_edits(get_content(enwiki), edits)

    return flask.render_template(
        "save.html",
        edit_summary=edit_summary,
        title=enwiki,
        edits=edits,
        text=article_text,
    )


class DabItem(TypedDict):
    """Represent a disabiguation page."""

    num: int
    title: str
    html: str


class Article:
    """Current article we're working on."""

    def __init__(self, enwiki: str) -> None:
        """Make a new Article object."""
        self.enwiki = enwiki

        self.links = get_article_links(enwiki)

        self.dab_list: list[DabItem] = []
        self.dab_lookup: dict[int, str] = {}
        self.dab_order: list[str] = []
        self.parse: Optional[dict[str, Any]] = None

    def save_endpoint(self) -> str:
        """Endpoint for saving changes."""
        href: str = flask.url_for("save", enwiki=self.enwiki.replace(" ", "_"))
        return href

    def load(self) -> None:
        """Load parsed article HTML."""
        self.parse = call_parse_api(self.enwiki)
        self.root = lxml.html.fromstring(self.parse.pop("text"))

    def iter_links(self) -> Iterator[tuple[lxml.html.Element, str]]:
        """Disambiguation links that need fixing."""
        seen = set()
        for a in self.root.findall(".//a[@href]"):
            title = a.get("title")
            if title is None or title not in self.links:
                continue
            a.set("class", "disambig")

            if title in seen:
                continue
            seen.add(title)

            yield a, title

    def process_links(self) -> None:
        """Process links in parsed wikitext."""
        for dab_num, (a, title) in enumerate(self.iter_links()):
            a.set("id", f"dab-{dab_num}")

            dab: DabItem = {
                "num": dab_num,
                "title": title,
                "html": get_dab_html(dab_num, title),
            }
            self.dab_list.append(dab)
            self.dab_order.append(title)
            self.dab_lookup[dab_num] = title

    def get_html(self) -> str:
        """Return the processed article HTML."""
        html: str = lxml.html.tostring(self.root, encoding=str)
        return html


@app.route("/enwiki/<path:enwiki>")
def article_page(enwiki: str) -> Response:
    """Article Page."""
    enwiki_orig = enwiki
    enwiki = enwiki.replace("_", " ")
    enwiki_underscore = enwiki.replace(" ", "_")
    if " " in enwiki_orig:
        return flask.redirect(
            flask.url_for(flask.request.endpoint, enwiki=enwiki_underscore)
        )

    article = Article(enwiki)
    article.load()
    article.process_links()

    assert article.parse

    return flask.render_template("article.html", article=article)


@app.route("/oauth/start")
def start_oauth():
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
def oauth_callback():
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
    return flask.redirect(next_page) if next_page else flask.url_for("index")


@app.route("/oauth/disconnect")
def oauth_disconnect():
    for key in "owner_key", "owner_secret", "username", "after_login":
        if key in flask.session:
            del flask.session[key]
    return flask.redirect(flask.url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0")
