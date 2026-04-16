"""
generators/claude_extractor.py

LLM interaction layer: system prompt, prompt builder, and Claude API call
for extracting ESG claims from report blocks.
"""
from __future__ import annotations

import json
import sys

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an ESG disclosure auditor specialising in Vietnamese corporate sustainability reports.

TASK
Extract all ESG disclosure claims from the REPORT BLOCKS that correspond to the INDICATORS below.

CLAIM TYPE DEFINITIONS
- "reported"    : actual measured data with a specific value for the reporting year
- "committed"   : specific target with a year and quantity (a binding commitment)
- "aspirational": vague goal without specific data, timeline, or accountability
- "qualitative" : policy, process, or management approach description (valid only for
                  non-quantitative indicators)

RULES
1. Use each indicator's extraction_hint to decide whether text constitutes a valid claim.
2. One report block can produce multiple claims for different indicators.
3. If no relevant claim exists for an indicator, omit it — do NOT force a match.
4. Set value and unit only when a specific number is present; otherwise null.
5. Confidence scale:
     0.9–1.0  explicit, unambiguous data
     0.6–0.89 implied or partial match
     0.3–0.59 weak or inferred match
6. Return ONLY valid JSON — no markdown, no explanation, no extra text.

OUTPUT SCHEMA (strict)
{
  "claims": [
    {
      "indicator_id": "<string>",
      "claim_type": "reported|committed|aspirational|qualitative",
      "claim_text": "<concise quote or paraphrase>",
      "value": "<numeric string or null>",
      "unit": "<unit string or null>",
      "confidence": <float 0.0-1.0>,
      "source_block_id": "<block id string>",
      "source_page": <int>
    }
  ]
}
"""


def build_prompt(indicators: list[dict], blocks: list[dict]) -> str:
    """Assemble the user message content for Claude."""
    ind_slim: list[dict] = []
    for ind in indicators:
        entry: dict = {
            "indicator_id":    ind["indicator_id"],
            "code":            ind.get("code", ""),
            "title":           ind.get("title", ""),
            "pillar":          ind.get("pillar", ""),
            "category":        ind.get("category", ""),
            "is_quantitative": ind.get("is_quantitative", False),
            "extraction_hint": ind.get("extraction_hint", ""),
            "valid_claim_types": ind.get("valid_claim_types", []),
        }
        if ind.get("unit"):
            entry["unit"] = ind["unit"]
        if ind.get("mandatory_for"):
            entry["mandatory_for"] = ind["mandatory_for"]
        ind_slim.append(entry)

    return (
        "## INDICATORS\n"
        + json.dumps(ind_slim, ensure_ascii=False, indent=2)
        + "\n\n## REPORT BLOCKS\n"
        + json.dumps(blocks, ensure_ascii=False, indent=2)
        + "\n\n## OUTPUT\n"
    )


def call_claude(prompt: str, model: str, api_key: str) -> list[dict]:
    """Send prompt to Claude and return the parsed claims list."""
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic not installed. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"  Sending request to {model}  (~{len(prompt) // 1000}k chars) ...")
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        temperature=0.1,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = ""
    for block in response.content:
        if block.type == "text":
            raw = block.text
            break

    try:
        parsed = json.loads(raw)
        claims = parsed.get("claims", [])
        if not isinstance(claims, list):
            raise ValueError("'claims' key is not a list")
        return claims
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"  WARNING: Claude returned invalid JSON — {exc}")
        print(f"  Raw response (first 500 chars):\n{raw[:500]}")
        return []
