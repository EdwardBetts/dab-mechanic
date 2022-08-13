#!/usr/bin/python3

import json
from collections import defaultdict
from typing import Any

import flask
import lxml.html
import requests
from werkzeug.wrappers import Response

app = flask.Flask(__name__)


app.debug = True


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


@app.route("/save/<path:enwiki>", methods=["POST"])
def save(enwiki: str) -> Response | str:
    """Save edits to article."""
    edits = json.loads(flask.request.form["edits"])
    return flask.render_template("save.html", title=enwiki, edits=edits)


@app.route("/enwiki/<path:enwiki>")
def article(enwiki: str) -> Response:
    """Article Page."""
    enwiki_orig = enwiki
    enwiki = enwiki.replace("_", " ")
    enwiki_underscore = enwiki.replace(" ", "_")
    if " " in enwiki_orig:
        return flask.redirect(
            flask.url_for(flask.request.endpoint, enwiki=enwiki_underscore)
        )
    html = get_article_html(enwiki)
    links = get_article_links(enwiki)

    root = lxml.html.fromstring(html)
    html_links = defaultdict(list)
    seen = set()

    dab_list = []
    dab_lookup = {}
    dab_num = 0

    for a in root.findall(".//a[@href]"):
        title = a.get("title")
        if title is None:
            continue
        if title not in links:
            continue
        a.set("class", "disambig")
        if title not in seen:
            dab_num += 1
            a.set("id", f"dab-{dab_num}")
            seen.add(title)
            dab_html = get_dab_html(dab_num, title)
            dab_list.append({"num": dab_num, "title": title, "html": dab_html})
            dab_lookup[dab_num] = title

        html_links[title].append(a)

    return flask.render_template(
        "article.html",
        title=enwiki,
        enwiki_underscore=enwiki_underscore,
        text=lxml.html.tostring(root, encoding=str),
        links=links,
        html_links=html_links,
        dab_list=dab_list,
        dab_lookup=dab_lookup,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
