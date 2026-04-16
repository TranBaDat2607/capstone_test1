"""
reasoning/rl_agent.py

RL-shaped step-by-step reasoning agent for ESG greenwashing detection.

This module implements an actor-critic prompting loop where:
  - Actor  : Main LLM reasons step-by-step, citing KG nodes/edges
  - Critic : Evaluates graph-groundedness of each reasoning step
  - Reward : +1 if the step cites a KG node/edge; -1 if unsupported
  - Loop   : Continues until all steps are grounded or max_iterations reached

This is in-context RL / inference-time policy optimisation.
No gradient updates are performed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL: str = "gemini-2.0-flash"
_DEFAULT_MAX_ITER: int = 2
_GROUNDEDNESS_THRESHOLD: float = 0.60   # minimum score to accept a step
_LOW_CONFIDENCE_THRESHOLD: float = 0.50  # flag verdict if below this


class RLReasoningAgent:
    """
    RL-shaped step-by-step reasoning agent for greenwashing detection.

    Uses an actor-critic prompt loop where:
    - Actor: Main LLM reasons step-by-step, citing KG nodes
    - Critic: Evaluates graph-groundedness of each step
    - Reward: +1 if step cites KG node/edge, -1 if unsupported leap
    - Loop: Continues until all steps grounded or max_iterations reached

    This is in-context RL / inference-time policy optimization.
    No gradient updates required.

    Parameters
    ----------
    api_key : str | None
        Google AI API key. If None, reads ``GOOGLE_AI_API_KEY`` from env.
    model : str
        Gemini model identifier to use for both actor and critic calls.
    max_iterations : int
        Maximum number of actor-critic loop iterations per claim.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        max_iterations: int = _DEFAULT_MAX_ITER,
    ) -> None:
        _key = api_key or ""
        self._genai_client = genai.Client(api_key=_key)
        self.model = model
        self.max_iterations = max_iterations

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def build_actor_prompt(
        self,
        claim: dict[str, Any],
        pro_paths: str,
        anti_paths: str,
        reasoning_history: list[dict[str, Any]],
        iteration: int,
    ) -> str:
        """
        Build the actor system + user prompt for one reasoning step.

        On iteration 0 the actor receives the raw claim and evidence.
        On subsequent iterations it also receives the previous reasoning
        steps and the critic feedback from the last step.

        Parameters
        ----------
        claim : dict
            Claim node dict (id, text, pillar, sentiment, year, …).
        pro_paths : str
            LLM-formatted pro-evidence paths (from
            ``ContrastiveGraphRAG.format_paths_for_llm``).
        anti_paths : str
            LLM-formatted anti-evidence paths.
        reasoning_history : list[dict]
            Accumulated steps, each with keys ``step``, ``groundedness``,
            ``feedback``.
        iteration : int
            Current loop iteration (0-indexed).

        Returns
        -------
        str
            Full prompt string (system + user sections concatenated for
            single-turn call convenience).
        """
        claim_text = claim.get("text", "(no claim text)")
        claim_id = claim.get("id", "?")
        claim_year = claim.get("year", "?")
        pillar = claim.get("pillar", "?")

        system_block = (
            "You are a meticulous ESG greenwashing analyst with expertise in "
            "Vietnamese regulatory frameworks (TT96/2020, TT08/2026, GRI Standards, "
            "ISSB IFRS S1/S2, Vietnam Green Taxonomy QD 21/2025).\n\n"
            "Your task is to reason step-by-step about whether an ESG claim "
            "constitutes greenwashing, using ONLY the provided Knowledge Graph (KG) "
            "evidence paths.\n\n"
            "RULES:\n"
            "1. Each response must contain EXACTLY ONE reasoning step.\n"
            "2. Every factual assertion must cite a specific KG node or edge "
            "   (use the node ID in brackets, e.g. [CLM_E_001], [DP_E_001]).\n"
            "3. Do NOT introduce information not present in the provided KG paths.\n"
            "4. End your step with one of: CONTINUE | READY_FOR_VERDICT\n"
        )

        user_block = (
            f"=== CLAIM UNDER REVIEW ===\n"
            f"ID    : {claim_id}\n"
            f"Year  : {claim_year}\n"
            f"Pillar: {pillar}\n"
            f"Text  : {claim_text}\n\n"
            f"=== PRO-CLAIM EVIDENCE (KG paths supporting the claim) ===\n"
            f"{pro_paths}\n\n"
            f"=== ANTI-CLAIM EVIDENCE (KG paths contradicting the claim) ===\n"
            f"{anti_paths}\n\n"
        )

        if iteration > 0 and reasoning_history:
            user_block += "=== PREVIOUS REASONING STEPS ===\n"
            for i, entry in enumerate(reasoning_history, start=1):
                user_block += (
                    f"Step {i}: {entry.get('step', '')}\n"
                    f"  [Groundedness: {entry.get('groundedness', '?')} | "
                    f"Feedback: {entry.get('feedback', '')}]\n\n"
                )
            last_feedback = reasoning_history[-1].get("feedback", "")
            if last_feedback:
                user_block += (
                    f"=== CRITIC FEEDBACK ON LAST STEP ===\n"
                    f"{last_feedback}\n\n"
                )

        user_block += (
            f"=== YOUR TASK ===\n"
            f"Provide reasoning step {iteration + 1}. "
            f"Cite at least one KG node/edge from the evidence above. "
            f"End with CONTINUE or READY_FOR_VERDICT.\n"
        )

        return f"<system>\n{system_block}\n</system>\n\n{user_block}"

    def build_critic_prompt(
        self,
        reasoning_step: str,
        pro_paths: str,
        anti_paths: str,
    ) -> str:
        """
        Build the critic evaluation prompt for a single reasoning step.

        The critic checks three dimensions:
        1. Groundedness — is every claim traceable to a KG path?
        2. Hallucination — does the step introduce unsupported information?
        3. Progress — does the step advance toward a verdict?

        Parameters
        ----------
        reasoning_step : str
            The actor's latest reasoning step text.
        pro_paths : str
            Formatted pro-evidence paths for verification.
        anti_paths : str
            Formatted anti-evidence paths for verification.

        Returns
        -------
        str
            Critic prompt string requesting a JSON response.
        """
        system_block = (
            "You are a strict fact-checker evaluating a single reasoning step "
            "produced by a greenwashing analysis agent.\n\n"
            "Your job is to verify that every factual assertion in the step is "
            "directly traceable to the provided Knowledge Graph evidence paths.\n\n"
            "Respond with a JSON object and NOTHING ELSE. Schema:\n"
            "{\n"
            '  "groundedness": <float 0.0–1.0>,\n'
            '  "hallucination": <true|false>,\n'
            '  "progress": <true|false>,\n'
            '  "feedback": "<one-sentence critique or confirmation>"\n'
            "}\n\n"
            "Criteria:\n"
            "- groundedness : fraction of assertions that cite a KG node/edge ID\n"
            "- hallucination: true if any assertion has no KG support\n"
            "- progress     : true if the step meaningfully advances toward "
            "  a Verified / Greenwashing / Insufficient_Evidence verdict\n"
        )

        user_block = (
            f"=== REASONING STEP TO EVALUATE ===\n"
            f"{reasoning_step}\n\n"
            f"=== AVAILABLE PRO-CLAIM EVIDENCE ===\n"
            f"{pro_paths}\n\n"
            f"=== AVAILABLE ANTI-CLAIM EVIDENCE ===\n"
            f"{anti_paths}\n\n"
            f"Evaluate the reasoning step strictly against the KG evidence above.\n"
            f"Return only the JSON object.\n"
        )

        return f"<system>\n{system_block}\n</system>\n\n{user_block}"

    # ------------------------------------------------------------------
    # LLM call wrappers
    # ------------------------------------------------------------------

    def actor_step(
        self,
        claim: dict[str, Any],
        pro_paths_str: str,
        anti_paths_str: str,
        history: list[dict[str, Any]],
        iteration: int,
    ) -> str:
        """
        Invoke the actor LLM and return one reasoning step.

        Parameters
        ----------
        claim : dict
            Claim node dict.
        pro_paths_str : str
            Formatted pro-evidence string.
        anti_paths_str : str
            Formatted anti-evidence string.
        history : list[dict]
            Accumulated reasoning history.
        iteration : int
            Current loop iteration.

        Returns
        -------
        str
            Actor reasoning step text.  Empty string on API error.
        """
        prompt = self.build_actor_prompt(
            claim=claim,
            pro_paths=pro_paths_str,
            anti_paths=anti_paths_str,
            reasoning_history=history,
            iteration=iteration,
        )
        try:
            return _gemini_call(self._genai_client, self.model, prompt, max_tokens=1024)
        except Exception as exc:
            logger.error("Actor LLM call failed at iteration %d: %s", iteration, exc)
            return ""

    def critic_evaluate(
        self,
        step: str,
        pro_paths_str: str,
        anti_paths_str: str,
    ) -> dict[str, Any]:
        """
        Invoke the critic LLM and return a structured evaluation dict.

        Parameters
        ----------
        step : str
            The actor's reasoning step to evaluate.
        pro_paths_str : str
            Formatted pro-evidence string.
        anti_paths_str : str
            Formatted anti-evidence string.

        Returns
        -------
        dict with keys: groundedness (float), hallucination (bool),
        progress (bool), feedback (str).
        Returns safe defaults on parse failure.
        """
        fallback: dict[str, Any] = {
            "groundedness": _DEFAULT_GROUNDEDNESS_ON_ERROR,
            "hallucination": False,
            "progress": True,
            "feedback": "(critic evaluation unavailable)",
        }

        prompt = self.build_critic_prompt(
            reasoning_step=step,
            pro_paths=pro_paths_str,
            anti_paths=anti_paths_str,
        )
        try:
            raw_text = _gemini_call(self._genai_client, self.model, prompt, max_tokens=256)
            return _parse_critic_json(raw_text, fallback=fallback)
        except Exception as exc:
            logger.error("Critic LLM call failed: %s", exc)
            return fallback

    # ------------------------------------------------------------------
    # Final verdict synthesis
    # ------------------------------------------------------------------

    def generate_final_verdict(
        self,
        claim: dict[str, Any],
        reasoning_chain: list[dict[str, Any]],
        pro_paths: str,
        anti_paths: str,
    ) -> dict[str, Any]:
        """
        Synthesise a final greenwashing verdict from the completed reasoning chain.

        Parameters
        ----------
        claim : dict
            Claim node dict.
        reasoning_chain : list[dict]
            All accepted reasoning steps with their groundedness scores.
        pro_paths : str
            Formatted pro-evidence string.
        anti_paths : str
            Formatted anti-evidence string.

        Returns
        -------
        dict with keys:
            verdict      : "Verified" | "Greenwashing" | "Insufficient_Evidence"
            confidence   : float [0, 1]
            evidence_chain: list[str]  (cited KG node IDs)
            explanation  : str
        """
        chain_text = "\n".join(
            f"Step {i + 1} [groundedness={s.get('groundedness', '?')}]: "
            f"{s.get('step', '')}"
            for i, s in enumerate(reasoning_chain)
        )

        system_block = (
            "You are a senior ESG auditor issuing a final greenwashing verdict.\n\n"
            "Based on the completed reasoning chain and the KG evidence, output a "
            "JSON object with EXACTLY these keys:\n"
            "{\n"
            '  "verdict": "Verified" | "Greenwashing" | "Insufficient_Evidence",\n'
            '  "confidence": <float 0.0–1.0>,\n'
            '  "evidence_chain": [<list of KG node IDs cited>],\n'
            '  "explanation": "<2-3 sentence summary>"\n'
            "}\n"
        )

        user_block = (
            f"=== CLAIM ===\n"
            f"ID: {claim.get('id', '?')} | Pillar: {claim.get('pillar', '?')}\n"
            f"Text: {claim.get('text', '')}\n\n"
            f"=== PRO-CLAIM EVIDENCE ===\n{pro_paths}\n\n"
            f"=== ANTI-CLAIM EVIDENCE ===\n{anti_paths}\n\n"
            f"=== REASONING CHAIN ===\n{chain_text}\n\n"
            f"Issue the final verdict as a JSON object.\n"
        )

        prompt = f"<system>\n{system_block}\n</system>\n\n{user_block}"

        fallback_verdict: dict[str, Any] = {
            "verdict": "Insufficient_Evidence",
            "confidence": 0.0,
            "evidence_chain": [],
            "explanation": "Verdict generation failed; manual review required.",
        }

        try:
            raw_text = _gemini_call(self._genai_client, self.model, prompt, max_tokens=512)
            return _parse_verdict_json(raw_text, fallback=fallback_verdict)
        except Exception as exc:
            logger.error("Verdict generation failed: %s", exc)
            return fallback_verdict

    # ------------------------------------------------------------------
    # RL reasoning loop
    # ------------------------------------------------------------------

    def reason(
        self,
        claim_id: str,
        claim: dict[str, Any],
        contrastive_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute the full RL actor-critic loop for a single claim.

        Algorithm
        ---------
        1. Format pro and anti paths as LLM-readable text.
        2. Actor generates one reasoning step.
        3. Critic evaluates groundedness.
        4. If groundedness >= threshold -> accept step and continue.
        5. If groundedness < threshold -> regenerate with critic feedback
           (counted as the same iteration).
        6. Repeat until actor signals READY_FOR_VERDICT or max_iterations.
        7. Call ``generate_final_verdict`` on the accepted chain.

        Parameters
        ----------
        claim_id : str
            The claim's KG node ID.
        claim : dict
            Claim node dict.
        contrastive_context : dict
            Output of ``ContrastiveGraphRAG.retrieve_contrastive_context``.

        Returns
        -------
        dict with keys:
            claim_id            : str
            verdict             : "Verified" | "Greenwashing" | "Insufficient_Evidence"
            confidence          : float
            reasoning_chain     : list[dict]  (accepted steps)
            evidence_chain      : list[str]   (cited KG node IDs)
            iterations_used     : int
            low_confidence_flag : bool
        """
        from retrieval.contrastive_graph_rag import ContrastiveGraphRAG  # lazy import

        # Format evidence strings
        rag_instance: Any = contrastive_context.get("_rag_instance")
        pro_paths_raw: list[dict] = contrastive_context.get("pro_paths", [])
        anti_paths_raw: list[dict] = contrastive_context.get("anti_paths", [])

        if rag_instance is not None and hasattr(rag_instance, "format_paths_for_llm"):
            pro_paths_str: str = rag_instance.format_paths_for_llm(pro_paths_raw)
            anti_paths_str: str = rag_instance.format_paths_for_llm(anti_paths_raw)
        else:
            # Fallback: basic serialisation
            pro_paths_str = _format_paths_simple(pro_paths_raw)
            anti_paths_str = _format_paths_simple(anti_paths_raw)

        reasoning_chain: list[dict[str, Any]] = []
        iterations_used: int = 0
        ready_for_verdict: bool = False

        for iteration in range(self.max_iterations):
            iterations_used = iteration + 1

            # --- Actor step ---
            step_text = self.actor_step(
                claim=claim,
                pro_paths_str=pro_paths_str,
                anti_paths_str=anti_paths_str,
                history=reasoning_chain,
                iteration=iteration,
            )

            if not step_text:
                logger.warning("Actor returned empty step at iteration %d", iteration)
                break

            # --- Critic evaluation ---
            critique = self.critic_evaluate(
                step=step_text,
                pro_paths_str=pro_paths_str,
                anti_paths_str=anti_paths_str,
            )
            groundedness: float = float(critique.get("groundedness", 0.0))

            # If groundedness too low -> one regeneration attempt with feedback
            if groundedness < _GROUNDEDNESS_THRESHOLD:
                logger.debug(
                    "Step %d groundedness %.2f below threshold; regenerating",
                    iteration + 1, groundedness,
                )
                # Inject feedback into history temporarily for regeneration
                regen_history = reasoning_chain + [
                    {
                        "step": step_text,
                        "groundedness": groundedness,
                        "feedback": critique.get("feedback", ""),
                    }
                ]
                step_text = self.actor_step(
                    claim=claim,
                    pro_paths_str=pro_paths_str,
                    anti_paths_str=anti_paths_str,
                    history=regen_history,
                    iteration=iteration,
                )
                critique = self.critic_evaluate(
                    step=step_text,
                    pro_paths_str=pro_paths_str,
                    anti_paths_str=anti_paths_str,
                )
                groundedness = float(critique.get("groundedness", 0.0))

            # Accept the step regardless (we tried our best)
            reasoning_chain.append(
                {
                    "step": step_text,
                    "groundedness": groundedness,
                    "hallucination": critique.get("hallucination", False),
                    "progress": critique.get("progress", True),
                    "feedback": critique.get("feedback", ""),
                }
            )

            # Check actor signal
            if "READY_FOR_VERDICT" in step_text.upper():
                ready_for_verdict = True
                break

        # --- Final verdict ---
        verdict_dict = self.generate_final_verdict(
            claim=claim,
            reasoning_chain=reasoning_chain,
            pro_paths=pro_paths_str,
            anti_paths=anti_paths_str,
        )

        confidence: float = float(verdict_dict.get("confidence", 0.0))
        low_confidence_flag: bool = confidence < _LOW_CONFIDENCE_THRESHOLD

        return {
            "claim_id": claim_id,
            "verdict": verdict_dict.get("verdict", "Insufficient_Evidence"),
            "confidence": confidence,
            "reasoning_chain": reasoning_chain,
            "evidence_chain": verdict_dict.get("evidence_chain", []),
            "iterations_used": iterations_used,
            "low_confidence_flag": low_confidence_flag,
        }


# ---------------------------------------------------------------------------
# Module-level constants (must be defined after class for forward reference)
# ---------------------------------------------------------------------------

_DEFAULT_GROUNDEDNESS_ON_ERROR: float = 0.50


# ---------------------------------------------------------------------------
# Gemini call wrapper with quota-safe retry
# ---------------------------------------------------------------------------

def _gemini_call(
    client: Any,
    model_name: str,
    prompt: str,
    max_tokens: int = 1024,
    max_retries: int = 3,
) -> str:
    """
    Call the Gemini API with exponential backoff on quota errors.

    Retries up to *max_retries* times on 429 / ResourceExhausted responses,
    doubling the wait each time (4 s -> 8 s -> 16 s).

    Parameters
    ----------
    client : google.genai.Client
    model_name : str
        Model name, e.g. "gemini-2.0-flash".
    prompt : str
        Full prompt string (system + user combined).
    max_tokens : int
        Maximum output token budget.
    max_retries : int
        Number of retry attempts before re-raising.

    Returns
    -------
    str
        Model response text, stripped of leading/trailing whitespace.
    """
    config = genai_types.GenerateContentConfig(max_output_tokens=max_tokens)
    delay = 4  # seconds
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            return response.text.strip()
        except Exception as exc:
            exc_str = str(exc).lower()
            is_quota = (
                "429" in exc_str
                or "quota" in exc_str
                or "resource_exhausted" in exc_str
                or "resourceexhausted" in exc_str
            )
            if is_quota and attempt < max_retries:
                logger.warning(
                    "Gemini quota hit (attempt %d/%d), retrying in %ds — %s",
                    attempt + 1, max_retries, delay, exc,
                )
                time.sleep(delay)
                delay *= 2
                last_exc = exc
            else:
                raise
    raise RuntimeError("Gemini call failed after retries") from last_exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_critic_json(
    raw: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract and parse the JSON payload from a critic response.

    Handles cases where the model wraps JSON in markdown code fences.
    """
    text = raw.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return {
            "groundedness": float(data.get("groundedness", fallback["groundedness"])),
            "hallucination": bool(data.get("hallucination", fallback["hallucination"])),
            "progress": bool(data.get("progress", fallback["progress"])),
            "feedback": str(data.get("feedback", fallback["feedback"])),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.debug("Failed to parse critic JSON: %s | raw=%r", exc, raw[:200])
        return fallback


def _parse_verdict_json(
    raw: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Extract and parse the JSON payload from a verdict response."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    valid_verdicts = {"Verified", "Greenwashing", "Insufficient_Evidence"}
    try:
        data = json.loads(text)
        verdict = str(data.get("verdict", "Insufficient_Evidence"))
        if verdict not in valid_verdicts:
            verdict = "Insufficient_Evidence"
        return {
            "verdict": verdict,
            "confidence": float(data.get("confidence", 0.0)),
            "evidence_chain": list(data.get("evidence_chain", [])),
            "explanation": str(data.get("explanation", "")),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.debug("Failed to parse verdict JSON: %s | raw=%r", exc, raw[:200])
        return fallback


def _format_paths_simple(paths: list[dict[str, Any]]) -> str:
    """Minimal path formatter used as fallback when no RAG instance is available."""
    if not paths:
        return "(no paths found)"
    lines: list[str] = []
    for i, p in enumerate(paths, start=1):
        score = p.get("score", 0.0)
        path_type = p.get("path_type", "?")
        path_nodes = p.get("path", [])
        node_ids = [
            e.get("id", "?") for e in path_nodes if isinstance(e, dict) and "id" in e
        ]
        lines.append(
            f"Path {i} [{path_type.upper()} | score={score:.3f}]: "
            + " -> ".join(node_ids)
        )
    return "\n".join(lines)
