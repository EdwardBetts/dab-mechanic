#!/usr/bin/python3

import json
import re
from typing import Any, TypedDict

import flask
import lxml.html
import requests
from werkzeug.wrappers import Response

app = flask.Flask(__name__)
app.debug = True

api_url = "https://en.wikipedia.org/w/api.php"


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
    data = requests.get(api_url, params=params).json()
    rev: str = data["query"]["pages"][0]["revisions"][0]["content"]
    return rev


@app.route("/")
def index():
    articles = [line[:-1] for line in open("article_list")]

    return flask.render_template("index.html", articles=articles)


def get_article_html(enwiki: str) -> str:
    """Parse article wikitext and return HTML."""
    url = "https://en.wikipedia.org/w/api.php"

    params: dict[str, str | int] = {
        "action": "parse",
        "format": "json",
        "formatversion": 2,
        "disableeditsection": 1,
        "page": enwiki,
    }

    r = requests.get(url, params=params)
    html: str = r.json()["parse"]["text"]
    return html


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

    def save_endpoint(self) -> str:
        """Endpoint for saving changes."""
        href: str = flask.url_for("save", enwiki=self.enwiki.replace(" ", "_"))
        return href

    def load(self) -> None:
        """Load parsed article HTML."""
        html = get_article_html(self.enwiki)
        self.root = lxml.html.fromstring(html)

    def process_links(self) -> None:
        """Process links in parsed wikitext."""
        dab_num = 0
        seen = set()

        for a in self.root.findall(".//a[@href]"):
            title = a.get("title")
            if title is None:
                continue
            if title not in self.links:
                continue
            a.set("class", "disambig")
            if title not in seen:
                dab_num += 1
                a.set("id", f"dab-{dab_num}")
                seen.add(title)
                dab_html = get_dab_html(dab_num, title)
                dab: DabItem = {"num": dab_num, "title": title, "html": dab_html}
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

    return flask.render_template("article.html", article=article)


if __name__ == "__main__":
    app.run(host="0.0.0.0")
