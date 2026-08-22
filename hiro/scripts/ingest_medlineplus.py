#!/usr/bin/env python
"""Ingest MedlinePlus content into the Baymax knowledge base.

    MedlinePlus data files -> parse into topics -> MedGemma generates QA items
                           -> POST each item to /knowledge-base/qa

Sources
-------
MedlinePlus publishes bulk data files for only some of the sections in its
navigation. This script covers everything that has an official download:

  health-topics  Health Topics. Dated daily file, resolved automatically from
                 https://medlineplus.gov/xml.html (there is no stable undated
                 URL — that is why mplus_topics.xml 404s). The file holds both
                 English and Spanish topics; see --language.
  genetics       MedlinePlus Genetics: ~2800 gene, condition, chromosome and
                 mtDNA summaries in one compendium.
  definitions    Definitions of Health Terms: vitamins, minerals, nutrition,
                 fitness, general health. The only bulk supplement-adjacent
                 content MedlinePlus publishes.

Not available as bulk downloads, and therefore not covered:

  Drugs & Supplements   Drug monographs are AHFS Patient Medication Information,
                        licensed from ASHP; herb and supplement pages are
                        likewise licensed. No data file is offered.
  Medical Tests         No data file is offered.
  Medical Encyclopedia  Licensed from A.D.A.M. No data file is offered.

Those three exist only as web pages of third-party licensed content, so this
script does not scrape them. See https://medlineplus.gov/about/developers/.

Usage
-----
    uv run python scripts/ingest_medlineplus.py --list-sources
    uv run python scripts/ingest_medlineplus.py --limit 2 --dry-run
    uv run python scripts/ingest_medlineplus.py                  # all sources
    uv run python scripts/ingest_medlineplus.py --source genetics

Requires the API (entrypoints/api.sh) and MedGemma to be running.

Resumability
------------
Two things under --data-dir make re-runs cheap and non-duplicating:

* ``generated/<source>/<id>.json`` caches MedGemma's output per topic, so a
  resumed run re-uses the previous generation instead of paying for it again —
  and, because generation is non-deterministic, so that the same answers are
  posted rather than near-duplicates.
* ``state.jsonl`` records every topic completed and every item posted (by a hash
  of its answer text). Both are consulted on startup, so nothing is inserted
  twice even if the run is interrupted mid-topic.

Delete either to force that work to happen again.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

# Running this as a file puts scripts/ on sys.path, not the project root, so the
# ``hiro`` package is invisible until we put its parent there ourselves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hiro.common.logging import configure_logging, get_logger

logger = get_logger("scripts.ingest_medlineplus")

XML_INDEX_URL = "https://medlineplus.gov/xml.html"
GENETICS_URL = "https://medlineplus.gov/download/ghr-summaries.xml"
DEFINITION_FILES = [
    "vitaminsdefinitions.xml",
    "mineralsdefinitions.xml",
    "nutritiondefinitions.xml",
    "fitnessdefinitions.xml",
    "generalhealthdefinitions.xml",
]

DEFAULT_API_URL = "http://localhost:8080"
DEFAULT_LLM_BASE_URL = "https://chatbot-llm-gateway.pr.mci.dev/v1/"
DEFAULT_LLM_MODEL = "google/gemma-4-26B-A4B-it"

# The API caps questions per entry; keep the model well inside it.
MIN_QUESTIONS = 1
MAX_QUESTIONS = 10

# Skip stubs — too little text to ground several QA items in.
MIN_CONTENT_CHARS = 200

# Smaller models sometimes put a question in the "answer" field. Such an item is
# worse than useless once retrieved, so reject it rather than store it.
MIN_ANSWER_CHARS = 60

# Split into three pieces so the JSON example can contain literal braces without
# having to double every one of them for str.format().
_RULES = """\
You extract question-and-answer items from a medical article, for a knowledge \
base that retrieves answers one at a time.

Every item has two parts:

"answer"  - A COMPLETE FACTUAL STATEMENT that answers a question, written as \
prose. It must never be a question, a title, a heading or a topic name. Write \
2-5 sentences. Name the subject explicitly ("An A1C test measures...", not "It \
measures..."), because the reader will see this answer without the article \
around it.
"questions" - {min_q} to {max_q} different ways a patient might ask for exactly \
that answer. These ARE questions.

Rules:
1. Use ONLY facts stated in the article. Never add facts, numbers, drug names or \
recommendations that are not in it.
2. Cover the whole article. Give each distinct concept its own item: what it is, \
symptoms, causes, risk factors, how it is diagnosed, what the numbers mean, \
treatment, prevention, follow-up. A typical article yields 3 to 8 items.
3. Do not state the same fact in two different items.
4. Write in the same language as the article.
5. Output the JSON object and nothing else. No preamble, no commentary, and do \
not repeat the article back."""

_FORMAT = """
Format:
{"items": [{"answer": "...", "questions": ["...", "..."]}]}"""

# A worked example matters more than any instruction for a 4B model. Uses a
# subject unrelated to the likely inputs so it cannot bleed into the output.
_EXAMPLE = """
Example, for an article about vitamin D:
{"items": [
  {"answer": "Vitamin D is a nutrient the body needs to absorb calcium and build \
strong bones. The body makes vitamin D when skin is exposed to sunlight, and it is \
also found in a few foods and in supplements.", "questions": ["What is vitamin D?", \
"What does vitamin D do in the body?", "Why do I need vitamin D?"]},
  {"answer": "Not getting enough vitamin D can make bones thin, brittle or \
misshapen. In children this condition is called rickets, and in adults it is called \
osteomalacia.", "questions": ["What happens if I don't get enough vitamin D?", \
"What is vitamin D deficiency?", "Can low vitamin D affect my bones?"]}
]}

Note that each "answer" states facts. An answer such as "What is vitamin D?" \
would be wrong — that belongs in "questions"."""


def build_system_prompt() -> str:
    return (
        _RULES.format(min_q=MIN_QUESTIONS, max_q=MAX_QUESTIONS) + "\n" + _FORMAT + "\n" + _EXAMPLE
    )


USER_PROMPT = """\
{kind}: {title}
Source URL: {url}

Source text:
\"\"\"
{content}
\"\"\"

Produce the JSON object of grounded question-and-answer items now.\
"""


@dataclass(frozen=True)
class Topic:
    """One unit of source material, whatever file it came from."""

    source: str
    id: str
    title: str
    url: str
    content: str
    kind: str = "Topic"

    @property
    def uid(self) -> str:
        """Namespaced so ids from different sources can never collide."""
        return f"{self.source}:{self.id}"


@dataclass(frozen=True)
class QAItem:
    answer: str
    questions: list[str]

    @property
    def hash(self) -> str:
        """Identity used to avoid re-posting. Whitespace/case-insensitive."""
        normalised = " ".join(self.answer.lower().split())
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# XML helpers
# --------------------------------------------------------------------------- #


def localname(tag: str) -> str:
    """Element name without its namespace.

    The genetics compendium declares a namespace whose URI carries the schema
    date (``ghr-summaries-20250602.xsd``), so matching on the full tag would
    break the next time NLM revises the schema.
    """
    return tag.rsplit("}", 1)[-1]


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in element if localname(c.tag) == name), None)


def clean_text(raw: str) -> str:
    """Turn raw element text into clean prose.

    MedlinePlus escapes the HTML inside its summaries, so after the XML parser
    has decoded entities the string still contains literal ``<p>``/``<ul>`` tags
    as text. Those would otherwise be handed to the model and end up inside
    answers, so strip them — unescaping twice, since some entities are
    double-encoded. Definition files also prefix their CDATA values with ">".
    """
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.lstrip(">").strip()


def element_text(element: ET.Element) -> str:
    """All text under an element, including any nested markup."""
    return clean_text(" ".join(t.strip() for t in element.itertext() if t.strip()))


# --------------------------------------------------------------------------- #
# Source: health topics
# --------------------------------------------------------------------------- #


def resolve_health_topics(url_override: str | None = None) -> list[tuple[str, str]]:
    """Find the most recent dated health-topics file.

    MedlinePlus posts a new ``mplus_topics_YYYY-MM-DD.xml`` every day and keeps
    only the last week or so; there is no stable undated URL, so read the index
    for the newest one rather than hard-coding a filename that will rot.
    """
    if url_override:
        return [(url_override, "mplus_topics.xml")]

    logger.info("resolving latest health-topics file from %s", XML_INDEX_URL)
    response = httpx.get(XML_INDEX_URL, follow_redirects=True, timeout=60.0)
    response.raise_for_status()

    dates = re.findall(r"mplus_topics_(\d{4}-\d{2}-\d{2})\.xml", response.text)
    if not dates:
        msg = f"no dated mplus_topics file found at {XML_INDEX_URL}; pass --topics-url"
        raise RuntimeError(msg)

    latest = max(dates)
    logger.info("latest health-topics file is dated %s", latest)
    return [(f"https://medlineplus.gov/xml/mplus_topics_{latest}.xml", "mplus_topics.xml")]


def parse_health_topics(paths: list[Path], language: str = "english") -> list[Topic]:
    """Parse <health-topic> elements.

    ``findall`` on the root matches direct children only: topics embed
    <related-topic> references that a recursive search would pick up as if they
    were real topics.
    """
    topics: list[Topic] = []
    skipped = 0
    seen_languages: dict[str, int] = {}

    for path in paths:
        root = ET.parse(path).getroot()
        for element in root.findall("health-topic"):
            topic_language = (element.attrib.get("language") or "unspecified").lower()
            seen_languages[topic_language] = seen_languages.get(topic_language, 0) + 1
            if language != "all" and topic_language not in (language, "unspecified"):
                continue

            topic_id = element.attrib.get("id")
            title = element.attrib.get("title")
            summary_element = child(element, "full-summary")
            if summary_element is None or not topic_id or not title:
                skipped += 1
                continue

            content = element_text(summary_element)
            if len(content) < MIN_CONTENT_CHARS:
                skipped += 1
                continue

            topics.append(
                Topic(
                    source="health-topics",
                    id=topic_id,
                    title=title,
                    url=element.attrib.get("url", ""),
                    content=content,
                    kind="Health topic",
                )
            )

    logger.info("health-topics: languages in file %s", seen_languages)
    logger.info("health-topics: %d usable, %d skipped", len(topics), skipped)
    return topics


# --------------------------------------------------------------------------- #
# Source: genetics
# --------------------------------------------------------------------------- #

# Element name -> how the subject is described to the model.
GENETICS_KINDS = {
    "health-condition-summary": "Genetic condition",
    "gene-summary": "Gene",
    "chromosome-summary": "Chromosome",
    "mtdna-summary": "Mitochondrial DNA",
}


def resolve_genetics(_: str | None = None) -> list[tuple[str, str]]:
    return [(GENETICS_URL, "ghr-summaries.xml")]


def parse_genetics(paths: list[Path]) -> list[Topic]:
    """Parse the genetics compendium: conditions, genes, chromosomes, mtDNA."""
    topics: list[Topic] = []
    skipped = 0

    for path in paths:
        root = ET.parse(path).getroot()
        for element in root:
            kind = GENETICS_KINDS.get(localname(element.tag))
            if kind is None:
                continue

            topic_id = element.attrib.get("id")
            name_element = child(element, "name")
            page_element = child(element, "ghr-page")
            text_list = child(element, "text-list")

            if not topic_id or name_element is None or text_list is None:
                skipped += 1
                continue

            # Take each <text>'s <html> body only. Using itertext() on the whole
            # <text-list> would prepend the <text-role> value ("description",
            # "function") to the prose as if it were part of the article.
            bodies = [
                element_text(body)
                for text in text_list
                if (body := child(text, "html")) is not None
            ]
            content = " ".join(part for part in bodies if part)
            if len(content) < MIN_CONTENT_CHARS:
                skipped += 1
                continue

            topics.append(
                Topic(
                    source="genetics",
                    id=topic_id,
                    title=(name_element.text or "").strip(),
                    url=(page_element.text or "").strip() if page_element is not None else "",
                    content=content,
                    kind=kind,
                )
            )

    logger.info("genetics: %d usable, %d skipped", len(topics), skipped)
    return topics


# --------------------------------------------------------------------------- #
# Source: definitions of health terms
# --------------------------------------------------------------------------- #


def resolve_definitions(_: str | None = None) -> list[tuple[str, str]]:
    return [(f"https://medlineplus.gov/xml/{name}", name) for name in DEFINITION_FILES]


def parse_definitions(paths: list[Path]) -> list[Topic]:
    """Parse the term/definition files (vitamins, minerals, nutrition, ...).

    Each term is short, so these usually yield a single QA item — which is what
    the prompt's "fewer, well-grounded items" rule is there for.
    """
    topics: list[Topic] = []
    skipped = 0

    for path in paths:
        root = ET.parse(path).getroot()
        page_title = root.attrib.get("title", path.stem)
        page_url = root.attrib.get("page-url", "")

        # <term> and <definition> are siblings inside each <term-group>.
        for group in root:
            term_element = child(group, "term")
            definition_element = child(group, "definition")
            if term_element is None or definition_element is None:
                skipped += 1
                continue

            term = clean_text(term_element.text or "")
            definition = clean_text(definition_element.text or "")
            if not term or len(definition) < 60:
                skipped += 1
                continue

            topics.append(
                Topic(
                    source="definitions",
                    id=re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")[:80],
                    title=term,
                    url=page_url,
                    content=f"{term}: {definition}",
                    kind=page_title,
                )
            )

    logger.info("definitions: %d usable, %d skipped", len(topics), skipped)
    return topics


# --------------------------------------------------------------------------- #
# Source registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Source:
    name: str
    description: str
    resolve: Callable[..., list[tuple[str, str]]]
    parse: Callable[..., list[Topic]]


SOURCES: dict[str, Source] = {
    "health-topics": Source(
        name="health-topics",
        description="MedlinePlus Health Topics (dated daily file)",
        resolve=resolve_health_topics,
        parse=parse_health_topics,
    ),
    "genetics": Source(
        name="genetics",
        description="MedlinePlus Genetics: conditions, genes, chromosomes, mtDNA",
        resolve=resolve_genetics,
        parse=parse_genetics,
    ),
    "definitions": Source(
        name="definitions",
        description="Definitions of Health Terms (vitamins, minerals, nutrition, ...)",
        resolve=resolve_definitions,
        parse=parse_definitions,
    ),
}


# --------------------------------------------------------------------------- #
# Download and collect
# --------------------------------------------------------------------------- #


def download(url: str, path: Path, *, force: bool) -> Path:
    """Fetch a file unless we already have it."""
    if path.exists() and not force:
        logger.info("using existing %s (%.1f MB)", path, path.stat().st_size / 1e6)
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s", url)

    # Stream to a temp file so an interrupted download never leaves a truncated
    # XML behind that would then fail to parse on the next run.
    tmp = path.with_suffix(path.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1 << 16):
                handle.write(chunk)
    tmp.replace(path)

    logger.info("saved %s (%.1f MB)", path, path.stat().st_size / 1e6)
    return path


def collect_topics(args: argparse.Namespace) -> list[Topic]:
    """Download and parse every selected source; one failing source is skipped."""
    topics: list[Topic] = []

    for name in args.sources:
        source = SOURCES[name]
        logger.info("--- source: %s (%s)", name, source.description)

        try:
            targets = source.resolve(args.topics_url if name == "health-topics" else None)
            paths = [
                download(url, args.data_dir / name / filename, force=args.force_download)
                for url, filename in targets
            ]
        except Exception as exc:
            logger.error("could not fetch %s: %s: %s", name, type(exc).__name__, exc)
            continue

        try:
            if name == "health-topics":
                topics.extend(source.parse(paths, language=args.language))
            else:
                topics.extend(source.parse(paths))
        except ET.ParseError as exc:
            logger.error("could not parse %s: %s (try --force-download)", name, exc)

    return topics


# --------------------------------------------------------------------------- #
# Generate QA items with MedGemma
# --------------------------------------------------------------------------- #


def _extract_json(raw: str) -> Any:
    """Parse the model's reply, tolerating code fences and surrounding prose."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    msg = "model did not return parsable JSON"
    raise ValueError(msg)


def _coerce_items(payload: Any) -> list[QAItem]:
    """Validate the model's output, dropping anything malformed."""
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        return []

    items: list[QAItem] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue

        answer = str(entry.get("answer", "")).strip()
        raw_questions = entry.get("questions", [])
        if not answer or not isinstance(raw_questions, list):
            continue

        # The model put a question, a heading or a fragment where the answer
        # belongs. Storing it would poison retrieval.
        if answer.endswith("?"):
            logger.warning("  dropping item whose answer is a question: %r", answer[:80])
            continue
        if len(answer) < MIN_ANSWER_CHARS:
            logger.warning("  dropping item with a %d-char answer: %r", len(answer), answer[:80])
            continue

        # De-duplicate case-insensitively, the same way the API does.
        seen: set[str] = set()
        questions: list[str] = []
        for question in raw_questions:
            text = str(question).strip()
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                questions.append(text)

        if len(questions) < MIN_QUESTIONS:
            continue

        items.append(QAItem(answer=answer, questions=questions[:MAX_QUESTIONS]))

    return items


def generate_items(client: OpenAI, model: str, topic: Topic, *, max_chars: int) -> list[QAItem]:
    """Ask MedGemma for grounded QA items covering one topic."""
    content = topic.content
    if len(content) > max_chars:
        logger.debug("truncating %s from %d to %d chars", topic.uid, len(content), max_chars)
        content = content[:max_chars]

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": build_system_prompt(),
            },
            {
                "role": "user",
                "content": USER_PROMPT.format(
                    kind=topic.kind, title=topic.title, url=topic.url, content=content
                ),
            },
        ],
        # Low temperature: this is extraction, not writing.
        "temperature": 0.2,
        # Room for 8 items; too low truncates the JSON mid-array and the whole
        # topic then fails to parse.
        "max_tokens": 4096,
    }

    try:
        response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    except Exception as exc:
        logger.debug("json response_format rejected (%s), retrying without it", type(exc).__name__)
        response = client.chat.completions.create(**kwargs)

    print(response.choices[0].message.content, content, topic)
    return _coerce_items(_extract_json(response.choices[0].message.content or ""))


def load_or_generate(
    topic: Topic,
    cache_dir: Path,
    client: OpenAI,
    model: str,
    *,
    max_chars: int,
    regenerate: bool,
) -> list[QAItem]:
    """Return cached items for a topic, generating and caching them if needed."""
    cache_path = cache_dir / topic.source / f"{topic.id}.json"

    if cache_path.exists() and not regenerate:
        return _coerce_items(json.loads(cache_path.read_text(encoding="utf-8")))

    items = generate_items(client, model, topic, max_chars=max_chars)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"items": [{"answer": i.answer, "questions": i.questions} for i in items]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return items


# --------------------------------------------------------------------------- #
# Post to the knowledge base
# --------------------------------------------------------------------------- #


class PermanentPostError(RuntimeError):
    """The API rejected the item; retrying will not help."""


def post_item(http: httpx.Client, item: QAItem, *, attempts: int = 3) -> str:
    """POST one item, returning the created answer_uid.

    4xx is permanent (the item is malformed for the API); 5xx and connection
    errors are retried, since those are usually the API restarting.
    """
    body = {"answer": item.answer, "questions": item.questions}

    for attempt in range(1, attempts + 1):
        try:
            response = http.post("/knowledge-base/qa", json=body)
        except httpx.HTTPError as exc:
            if attempt == attempts:
                raise
            logger.warning("post failed (%s), retry %d/%d", exc, attempt, attempts)
            time.sleep(2 * attempt)
            continue

        if response.status_code < 400:
            return str(response.json()["answer_uid"])

        if response.status_code < 500:
            msg = f"{response.status_code}: {response.text[:200]}"
            raise PermanentPostError(msg)

        if attempt == attempts:
            msg = f"{response.status_code}: {response.text[:200]}"
            raise RuntimeError(msg)
        logger.warning("api returned %d, retry %d/%d", response.status_code, attempt, attempts)
        time.sleep(2 * attempt)

    msg = "unreachable"
    raise RuntimeError(msg)


# --------------------------------------------------------------------------- #
# Resumable state
# --------------------------------------------------------------------------- #


@dataclass
class State:
    """What previous runs already did."""

    path: Path
    done_topics: set[str]
    posted_hashes: set[str]

    @classmethod
    def load(cls, path: Path) -> State:
        done_topics: set[str] = set()
        posted_hashes: set[str] = set()

        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a half-written final line after a hard kill
                if record.get("type") == "topic" and record.get("status") == "ok":
                    done_topics.add(str(record["topic_uid"]))
                elif record.get("type") == "item":
                    posted_hashes.add(str(record["hash"]))

        logger.info(
            "state: %d topic(s) done, %d item(s) already posted",
            len(done_topics),
            len(posted_hashes),
        )
        return cls(path=path, done_topics=done_topics, posted_hashes=posted_hashes)

    def _append(self, record: dict[str, Any]) -> None:
        record["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record_item(self, topic: Topic, item: QAItem, answer_uid: str) -> None:
        self.posted_hashes.add(item.hash)
        self._append(
            {
                "type": "item",
                "topic_uid": topic.uid,
                "hash": item.hash,
                "answer_uid": answer_uid,
            }
        )

    def record_topic(self, topic: Topic, status: str, **extra: Any) -> None:
        if status == "ok":
            self.done_topics.add(topic.uid)
        self._append({"type": "topic", "topic_uid": topic.uid, "status": status, **extra})


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        choices=[*SOURCES, "all"],
        help="Source to ingest; repeatable. Default: all.",
    )
    parser.add_argument(
        "--language",
        default="english",
        choices=["english", "spanish", "all"],
        help="Health topics only — the file holds both languages. Default: english.",
    )
    parser.add_argument(
        "--topics-url",
        default=os.environ.get("MEDLINEPLUS_TOPICS_URL"),
        help="Override the auto-resolved health-topics file URL.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data/medlineplus"))
    parser.add_argument("--api-url", default=os.environ.get("BAYMAX_API_URL", DEFAULT_API_URL))
    parser.add_argument(
        "--llm-base-url", default=os.environ.get("MEDGEMMA_BASE_URL", DEFAULT_LLM_BASE_URL)
    )
    parser.add_argument("--model", default=os.environ.get("MEDGEMMA_MODEL", DEFAULT_LLM_MODEL))
    parser.add_argument("--llm-api-key", default=os.environ.get("MEDGEMMA_API_KEY", "not-needed"))
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N topics.")
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--llm-timeout", type=float, default=300.0)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--regenerate", action="store_true", help="Ignore the generation cache.")
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--parse-only", action="store_true", help="Parse and report, then stop.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))

    args = parser.parse_args(argv)
    if not args.sources or "all" in args.sources:
        args.sources = list(SOURCES)
    else:
        args.sources = list(dict.fromkeys(args.sources))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os.environ["LOG_LEVEL"] = args.log_level.upper()
    configure_logging(force=True)
    logger.info(
        "medlineplus ingestion started sources=%s dry_run=%s parse_only=%s limit=%d",
        args.sources,
        args.dry_run,
        args.parse_only,
        args.limit,
    )

    if args.list_sources:
        for source in SOURCES.values():
            print(f"{source.name:15} {source.description}")
        return 0

    topics = collect_topics(args)
    if not topics:
        logger.error("no topics parsed from any source")
        return 1

    if args.limit:
        topics = topics[: args.limit]
    logger.info("%d topic(s) to consider across: %s", len(topics), ", ".join(args.sources))

    if args.parse_only:
        for topic in topics[:5]:
            logger.info("  e.g. %s | %s | %d chars", topic.uid, topic.title, len(topic.content))
        return 0

    state = State.load(args.data_dir / "state.jsonl")
    cache_dir = args.data_dir / "generated"

    client = OpenAI(
        base_url=args.llm_base_url,
        api_key=args.llm_api_key,
        timeout=args.llm_timeout,
        max_retries=2,
    )
    http = httpx.Client(base_url=args.api_url, timeout=60.0)

    totals = dict.fromkeys(("topics", "skipped", "items", "duplicates", "failed"), 0)

    try:
        for index, topic in enumerate(topics, start=1):
            if topic.uid in state.done_topics:
                totals["skipped"] += 1
                continue

            logger.info("[%d/%d] %s: %s", index, len(topics), topic.source, topic.title)

            # One failing topic must never end the run — there are thousands.
            try:
                items = load_or_generate(
                    topic,
                    cache_dir,
                    client,
                    args.model,
                    max_chars=args.max_chars,
                    regenerate=args.regenerate,
                )
            except Exception as exc:
                logger.warning("  generation failed: %s: %s", type(exc).__name__, exc)
                if not args.dry_run:
                    state.record_topic(topic, "failed", stage="generate", error=str(exc)[:200])
                totals["failed"] += 1
                continue

            if not items:
                logger.warning("  no usable items produced")
                if not args.dry_run:
                    state.record_topic(topic, "failed", stage="generate", error="no items")
                totals["failed"] += 1
                continue

            posted = 0
            failed = False
            for item in items:
                if item.hash in state.posted_hashes:
                    totals["duplicates"] += 1
                    continue

                if args.dry_run:
                    print(
                        json.dumps(
                            {"answer": item.answer, "questions": item.questions},
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                    posted += 1
                    continue

                try:
                    answer_uid = post_item(http, item)
                except PermanentPostError as exc:
                    logger.warning("  api rejected an item: %s", exc)
                    continue  # skip this item, keep the rest of the topic
                except Exception as exc:
                    logger.warning("  post failed: %s: %s", type(exc).__name__, exc)
                    failed = True
                    break

                state.record_item(topic, item, answer_uid)
                posted += 1

            totals["items"] += posted

            if args.dry_run:
                continue

            if failed:
                # Items already posted are recorded, so the retry resumes here.
                state.record_topic(topic, "failed", stage="post", posted=posted)
                totals["failed"] += 1
            else:
                state.record_topic(topic, "ok", items=posted)
                totals["topics"] += 1

    except KeyboardInterrupt:
        logger.warning("interrupted — re-run to resume from here")
    finally:
        http.close()

    logger.info(
        "done: %d topic(s) ingested, %d item(s) posted, %d already present, "
        "%d topic(s) skipped, %d topic(s) failed",
        totals["topics"],
        totals["items"],
        totals["duplicates"],
        totals["skipped"],
        totals["failed"],
    )
    if totals["failed"]:
        logger.info("failed topics are retried automatically on the next run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
