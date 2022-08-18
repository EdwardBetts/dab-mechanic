from collections import defaultdict
from typing import Any, Iterator, Optional, TypedDict

import flask
import lxml.html

from . import mediawiki_api
from pprint import pprint
from time import sleep

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
        "redirects": 1,
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

    params: dict[str, str | int] = link_params(enwiki)
    links: set[str] = set()

    redirects = defaultdict(set)

    while True:
        data = mediawiki_api.call(params)
        if "query" not in data:
            pprint(data)
        pages = data["query"].pop("pages")
        for r in data["query"].pop("redirects"):
            redirects[r["to"]].add(r["from"])

        links.update(page["title"] for page in pages if needs_disambig(page))

        if "continue" not in data:
            break

        params["gplcontinue"] = data["continue"]["gplcontinue"]
        sleep(0.1)

    for link in set(links):
        if link in redirects:
            links.update(redirects[link])

    return list(links)

    # return {link["title"] for link in r.json()["query"]["pages"][0]["links"]}


def get_article_html(enwiki: str) -> str:
    """Parse article wikitext and return HTML."""
    text: str = mediawiki_api.parse_page(enwiki)["text"]
    return text


class DabItem(TypedDict):
    """Represent a disabiguation page."""

    num: int
    title: str
    html: str


def delete_toc(root: lxml.html.HtmlElement) -> None:
    """Delete table of contents from article HTML."""
    for toc in root.findall(".//div[@class='toc']"):
        toc.getparent().remove(toc)


def get_dab_html(dab_num: int, html: str) -> str:
    """Parse dab page and rewrite links."""
    root = lxml.html.fromstring(html)
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


class Article:
    """Current article we're working on."""

    def __init__(self, enwiki: str) -> None:
        """Make a new Article object."""
        self.enwiki = enwiki.replace("_", " ")

        self.links = get_article_links(enwiki)

        self.dab_list: list[DabItem] = []
        self.dab_lookup: dict[int, str] = {}
        self.dab_order: list[str] = []
        self.parse: Optional[dict[str, Any]] = None
        self.dab_html: dict[str, str] = {}

    def save_endpoint(self) -> str:
        """Endpoint for saving changes."""
        href: str = flask.url_for("save", enwiki=self.enwiki.replace(" ", "_"))
        return href

    def load(self) -> None:
        """Load parsed article HTML."""
        self.parse = mediawiki_api.parse_page(self.enwiki)
        self.root = lxml.html.fromstring(self.parse.pop("text"))

    def iter_links(self) -> Iterator[tuple[lxml.html.Element, str]]:
        """Disambiguation links that need fixing."""
        for a in self.root.findall(".//a[@href]"):
            title = a.get("title")
            if title is None or title not in self.links:
                continue
            yield a, title

    def process_links(self) -> None:
        """Process links in parsed wikitext."""
        for dab_num, (a, title) in enumerate(self.iter_links()):
            a.set("class", "disambig")
            a.set("id", f"dab-{dab_num}")

            if title not in self.dab_html:
                self.dab_html[title] = get_article_html(title)

            dab: DabItem = {
                "num": dab_num,
                "title": title,
                "html": get_dab_html(dab_num, self.dab_html[title]),
            }
            self.dab_list.append(dab)
            self.dab_order.append(title)
            self.dab_lookup[dab_num] = title

    def get_html(self) -> str:
        """Return the processed article HTML."""
        html: str = lxml.html.tostring(self.root, encoding=str)
        return html
