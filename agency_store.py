"""Local SQLite store for the Shorts Agency research and production system."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


STYLE_LINE = (
    "black and white scientific illustration, fine ink lines and soft graphite "
    "shading, like an old textbook, with one soft blue accent added only by the animation"
)


TEMPLATES = [
    {
        "id": "animated-science-short-v1",
        "name": "Animated scientific short",
        "format": "9:16 · 30 seconds · ~75 words",
        "purpose": "Calm single-camera explainers built from isolated cut-out objects.",
        "rules": [
            "One calm narrator; simple conversational language.",
            "Open on the subject immediately; no generic introduction.",
            "Use only verified facts. Omit uncertain claims.",
            "One continuous camera journey; no hard cuts.",
            "Use 4–8 isolated objects. Add labels, numbers, and arrows in animation only.",
        ],
    },
    {
        "id": "animated-science-longform-v1",
        "name": "Animated scientific long-form",
        "format": "16:9 · 10 minutes · ~1,500 words",
        "purpose": "Chaptered visual explainers that reuse the short-form object-and-camera system.",
        "rules": [
            "Start with a surprising verified fact and promise the ending within 30 seconds.",
            "Use 6–8 chapters. Each ends on a question leading to the next.",
            "Create a fact ledger with source URLs before writing final narration.",
            "Change the visual state at least every five seconds.",
            "Use about 20 isolated objects and one persistent camera; no hard cuts or black frames.",
        ],
    },
]


PROMPT_BLOCKS = [
    {
        "id": "short-script-v1",
        "template_id": "animated-science-short-v1",
        "stage": "script",
        "title": "Short script planner",
        "prompt": """You're going to help me make a short animated video, step by step. Today we only write the script. Don't make any pictures or code yet. Write a script for a vertical video (9:16), about 30 seconds long (around 75 words), read by one calm narrator.

Write like a real person explaining something to a friend. Use short sentences and simple words. The first sentence names what we are looking at and makes people curious. No intro and no 'Have you ever wondered'. Use only true, well-known facts; if a fact is uncertain, leave it out. Avoid hype words.

Design one continuous camera journey, with no hard cuts: begin on something recognisable, zoom into the detail that explains it, then pull back or loop to the start. Every sentence must have an exact visual counterpart. Use 4–8 separate objects with labels, numbers and text added later by animation.

Return: (1) narration word for word, (2) a sentence-by-sentence shot list with camera motion, (3) picture file names plus object descriptions, and (4) this style line exactly: {{style_line}}.

Idea: {{idea}}""",
    },
    {
        "id": "short-images-v1",
        "template_id": "animated-science-short-v1",
        "stage": "image",
        "title": "Object-image prompt",
        "prompt": """Create {{filename}}: {{object_and_angle}}, lots of empty space around it, nothing touching the edges, {{style_line}}, plain white background, no text, no labels, no numbers, no arrows, no shadows, no frame.

Choose {{image_model}} from the models currently available through your selected provider. Verify supported sizes, quality options and usage terms before generating; this template makes no model capability claim. Use square output unless the object is clearly wide or tall. Remove the background afterwards and save the clean cut-out to images/{{filename}}. Inspect it. Regenerate at most twice if it includes text, an unrequested colour, a cut-off edge, extra objects, or breaks the shared style.""",
    },
    {
        "id": "short-remotion-v1",
        "template_id": "animated-science-short-v1",
        "stage": "animation",
        "title": "Remotion short animation brief",
        "prompt": """Build a reusable Remotion template for this short: 1080x1920, 60 fps, duration equal to voice length plus one second. Put pictures, positions, traced paths, labels and timings in one settings file.

Use a white background and faint dot grid. Use one camera for the full scene. Follow the shot list precisely. Camera moves must ease in and settle; no constant-speed motion, pops, or abrupt stops. Introduce objects with blur, small scale and opacity over roughly half a second. Draw lines on. Make soft blue glowing light travel along the correct paths. Keep the top 8% and bottom 18% clear. Render a still every half-second and at every sentence start; fix all visible problems before final render.""",
    },
    {
        "id": "longform-script-v1",
        "template_id": "animated-science-longform-v1",
        "stage": "script",
        "title": "10-minute script and evidence planner",
        "prompt": """Create a complete ten-minute YouTube explainer on: {{topic}}.

Write roughly 1,500 words for one calm narrator. Use short, natural sentences and plain language. The first 30 seconds open with the most surprising verified fact and say what the viewer will understand by the end. Then create 6–8 chapters. Each chapter answers one question and ends with a small question that pulls the viewer onward. The ending returns to the opening.

Only use facts that can be sourced. For every number or factual claim, add a row to facts.md with the claim, source title, publisher, URL, and access date. Cut any fact that lacks a solid source. Write a sentence-level shot list: specify the object/diagram on screen and the one-camera movement. Change something visually at least every five seconds. List about 20 isolated picture assets, all using this style line exactly: {{style_line}}.""",
    },
    {
        "id": "longform-images-v1",
        "template_id": "animated-science-longform-v1",
        "stage": "image",
        "title": "Long-form asset prompt",
        "prompt": """Create {{filename}}: {{object_and_angle}}, lots of empty space around it, nothing touching the edges, {{style_line}}, plain white background, no text, no labels, no numbers, no arrows, no shadows, no frame.

Choose {{image_model}} from the models currently available through your selected provider. Verify supported sizes, quality options and usage terms before generating; this template makes no model capability claim. Remove the background so it is a clean cut-out. Save it in images/{{filename}}. Reject and regenerate at most twice for text, wrong colours, edge clipping, extra objects, or a style mismatch.""",
    },
    {
        "id": "longform-remotion-v1",
        "template_id": "animated-science-longform-v1",
        "stage": "animation",
        "title": "Remotion long-form build brief",
        "prompt": """Build a reusable Remotion project at 1920x1080 and 60 fps. Create one composition per chapter and join them through continuous camera moves; never use a hard cut or black frame. Use one camera across the complete video, always drifting slightly.

Match each shot-list sentence. Use slow pushes and pull-backs, magnifying circles connected with thin lines, soft glowing blue path lights, labels and counters, side-by-side comparisons, line-drawn diagrams, and depth layers. Ease every move in and out. One thing should happen at a time.

Render a still every second for every chapter and inspect them. Fix all layout, object-edge, timing and label issues. Render the final voice-synchronised video to out/full-video.mp4. Then write youtube.md containing a title, description with chapter timestamps, thumbnail concept, source disclosure, and a decision log.""",
    },
]


class AgencyStore:
    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL DEFAULT 'youtube',
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    format TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    rules_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prompt_blocks (
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_notes (
                    id INTEGER PRIMARY KEY,
                    channel_id INTEGER REFERENCES channels(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_url TEXT,
                    confidence TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL
                );
                """
            )
            for template in TEMPLATES:
                connection.execute(
                    """INSERT OR REPLACE INTO templates
                    (id, name, format, purpose, rules_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        template["id"], template["name"], template["format"],
                        template["purpose"], json.dumps(template["rules"]), utc_now(),
                    ),
                )
            for block in PROMPT_BLOCKS:
                connection.execute(
                    """INSERT OR REPLACE INTO prompt_blocks
                    (id, template_id, stage, title, prompt, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (block["id"], block["template_id"], block["stage"], block["title"], block["prompt"], utc_now()),
                )

    def list_templates(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM templates ORDER BY id").fetchall()
        return [self._template_row(row) for row in rows]

    def list_prompt_blocks(self, template_id: str | None = None) -> list[dict]:
        query = "SELECT id, template_id, stage, title, prompt, created_at FROM prompt_blocks"
        params: tuple = ()
        if template_id:
            query += " WHERE template_id = ?"
            params = (template_id,)
        query += " ORDER BY template_id, stage, id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def render_prompt(self, prompt_id: str, variables: dict[str, str]) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM prompt_blocks WHERE id = ?", (prompt_id,)).fetchone()
        if row is None:
            raise KeyError(prompt_id)
        context = {"style_line": STYLE_LINE, **variables}
        prompt = row["prompt"]
        for key, value in context.items():
            prompt = prompt.replace("{{" + key + "}}", value)
        result = dict(row)
        result["rendered_prompt"] = prompt
        return result

    def list_channels(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM channels ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def add_channel(self, name: str, url: str, analysis_status: str = "pending", notes: str = "") -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO channels (name, url, analysis_status, notes, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (name, url, analysis_status, notes, utc_now()),
            )
            return int(cursor.lastrowid)

    def get_channel(self, channel_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if row is None:
            raise KeyError(channel_id)
        return dict(row)

    @staticmethod
    def _template_row(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["rules"] = json.loads(item.pop("rules_json"))
        return item
