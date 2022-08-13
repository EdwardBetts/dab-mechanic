#!/usr/bin/python3

from collections import defaultdict

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
    url = "https://en.wikipedia.org/w/api.php"

    params = {
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


def get_article_links(enwiki: str) -> list[str]:
    """Get links that appear in this article."""
    url = "https://en.wikipedia.org/w/api.php"

    params = {
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

    links = []

    while True:
        r = requests.get(url, params=params)
        json_data = r.json()
        query = json_data.pop("query")
        pages = query["pages"]
        for page in pages:
            title = page["title"]
            if title.endswith(" (disambiguation)") or not page.get("templates"):
                continue
            if title not in links:
                links.append(title)

        if "continue" not in json_data:
            break
        print(json_data["continue"])

        params["gplcontinue"] = json_data["continue"]["gplcontinue"]

    return links

    # return {link["title"] for link in r.json()["query"]["pages"][0]["links"]}


@app.route("/enwiki/<path:enwiki>")
def article(enwiki: str) -> Response:
    """Article Page."""
    html = get_article_html(enwiki)
    links = get_article_links(enwiki)

    root = lxml.html.fromstring(html)
    html_links = defaultdict(list)
    seen = set()

    dab_list = []
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
            dab_html = get_article_html(title)
            dab_list.append({"num": dab_num, "title": title, "html": dab_html})

        html_links[title].append(a)

    return flask.render_template(
        "article.html",
        title=enwiki,
        text=lxml.html.tostring(root, encoding=str),
        links=links,
        html_links=html_links,
        dab_list=dab_list,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
