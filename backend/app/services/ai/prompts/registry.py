"""Prompt registry for Drawing Mirror. Architecture adapted from art-journal."""

from typing import Optional
from dataclasses import dataclass, field


@dataclass
class PromptTemplate:
    id: str
    template: str
    default_values: dict = field(default_factory=dict)


class PromptRegistry:
    """
    Manages prompt templates with variable substitution.
    Templates use Python str.format() style {placeholders}.
    """

    def __init__(self):
        self._templates: dict[str, PromptTemplate] = {}
        self._load_templates()

    def _load_templates(self):
        # ── PHASE 1: Batch image analysis ─────────────────────────────────────
        self.register(PromptTemplate(
            id="drawing_batch_analysis",
            template="""You are analyzing a personal drawing archive. Each image above is labeled with its filename.

For EACH drawing labeled above, return a JSON object with these fields:
- filename: exactly as labeled (e.g. "2016-05-06-trees.jpeg")
- description: 2-3 sentences describing subject, setting, mood, and composition
- visual_attributes: one sentence covering medium (watercolor/pencil/ink/charcoal/digital/etc), palette (warm/cool/muted/vibrant/monochrome), technique (loose/detailed/gestural/precise/hatched), and atmosphere
- time_period_clues: brief note on visual evidence suggesting when this might have been made (style maturity, subject matter, wear on paper, etc) — or "no clear clues" if uncertain

Return ONLY a valid JSON array, no markdown, no explanation:
[{{"filename": "...", "description": "...", "visual_attributes": "...", "time_period_clues": "..."}}, ...]"""
        ))

        # ── PHASE 2: Lens discovery from all text summaries ────────────────────
        self.register(PromptTemplate(
            id="lens_discovery",
            template="""You are helping someone reflect on their personal drawing archive spanning {year_range}.
They have {total_count} drawings in total.

Here are text descriptions of all their drawings in chronological order:
---
{all_summaries}
---

Your task: identify 3-5 meaningful "lenses" — narrative frames or observation angles that emerge specifically from THIS person's actual body of work.

A lens is an angle through which one can read the ENTIRE archive chronologically and discover a pattern or story. It is NOT a filter, not a category, not an art technique term.

Good lens examples (specific to a person's work):
- "Geographic journey — how the places you've visited shape what you choose to draw"
- "Presence and absence of people — when human figures appear vs. when scenes are empty"
- "Movement from interior to exterior — a shift in the types of spaces drawn over time"

Bad examples (too generic): "Color theory", "Composition", "Watercolor technique", "Nature"

For each lens, provide:
- name: short evocative title (3-6 words)
- description: ONE sentence explaining the observation angle this lens provides
- drawing_relevance: an object mapping EVERY drawing filename to a relevance score (0.0 to 1.0)
  where 1.0 = this drawing is highly expressive of the lens, 0.0 = essentially unrelated

Return ONLY valid JSON, no markdown:
{{
  "lenses": [
    {{
      "name": "...",
      "description": "...",
      "drawing_relevance": {{"filename1.jpeg": 0.9, "filename2.jpg": 0.3, ...}}
    }}
  ]
}}""",
            default_values={
                "year_range": "unknown period",
                "total_count": 0,
                "all_summaries": ""
            }
        ))

        # ── PHASE 3: Per-drawing annotations through a lens ────────────────────
        self.register(PromptTemplate(
            id="lens_annotation_batch",
            template="""Lens: "{lens_name}" — {lens_description}

For each drawing listed below, write ONE sentence observing it through the lens above.
- Be concrete and specific to what is actually in the drawing
- Frame as a quiet, perceptive observation — not an evaluation or judgment
- Vary your sentence structure (don't start every sentence with "This drawing...")
- Note what is relevant to the lens even if it's through contrast or absence

{drawing_entries}

Return ONLY a valid JSON array, one object per drawing, in the same order:
[{{"filename": "...", "annotation": "..."}}, ...]"""
        ))

    def register(self, template: PromptTemplate) -> None:
        self._templates[template.id] = template

    def render(self, template_id: str, **kwargs) -> str:
        """
        Render a template with the given keyword arguments.
        Missing keys that have defaults are filled in automatically.
        """
        template = self._templates.get(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        variables = dict(template.default_values)
        variables.update(kwargs)

        try:
            return template.template.format(**variables)
        except KeyError as e:
            raise ValueError(f"Missing required variable for template '{template_id}': {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────

_registry: Optional[PromptRegistry] = None


def get_prompt_registry() -> PromptRegistry:
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry
