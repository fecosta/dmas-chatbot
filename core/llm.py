from __future__ import annotations

from typing import Dict, List, Tuple, Any
import re

from anthropic import Anthropic


def language_instruction(lang_code: str) -> str:
    if lang_code == "es":
        return "Responde en español con explicaciones en prosa (párrafos conectados) y con contexto. Evita listas salvo que el usuario las pida explícitamente."
    if lang_code == "pt":
        return "Responda em português com explicações em prosa (parágrafos conectados) e com contexto. Evite listas a menos que o usuário peça explicitamente."
    if lang_code == "en":
        return "Answer in English with narrative explanations (connected paragraphs) and context. Avoid bullets unless the user explicitly asks."
    return "Respond in the user's language with narrative explanations (connected paragraphs). Avoid lists unless explicitly requested."


def build_system_prompt(answer_lang: str) -> str:
    return (
        "You are the Democracia+ assistant.\n"
        "Answer using ONLY the provided Democracia+ materials excerpts.\n"
        "If the info is not present, say so and ask what is missing.\n"
        "Default to narrative, explanatory prose in connected paragraphs.\n"
        "Use bullets/headings only when the user explicitly asks for a checklist/summary, or as a very brief recap after explanation.\n\n"
        + language_instruction(answer_lang)
    )


def format_excerpts(retrieved: List[Tuple[Dict[str, Any], float]]) -> str:
    if not retrieved:
        return "No relevant excerpts were retrieved."
    parts = []
    for i, (sec, score) in enumerate(retrieved, start=1):
        parts.append(
            f"[Excerpt {i} | {sec.get('path','')} | pages {sec.get('page_start')}–{sec.get('page_end')} | sim {score:.3f}]\n"
            f"{sec.get('text','')}"
        )
    return "\n\n".join(parts)


# --- Response mode switching (narrative-first vs structured summary) ---
_STRUCTURED_TRIGGERS = re.compile(
    r"\b(checklist|bullet|bullets|framework|tl;dr|tldr|summary|summarize|key points|in points)\b",
    re.IGNORECASE,
)


def pick_mode(user_text: str) -> str:
    return "STRUCTURED_SUMMARY" if _STRUCTURED_TRIGGERS.search(user_text or "") else "NARRATIVE_FIRST"


def mode_hint(user_text: str) -> str:
    mode = pick_mode(user_text)
    if mode == "STRUCTURED_SUMMARY":
        return (
            "[MODE: STRUCTURED_SUMMARY]\n"
            "Use headings and bullet points. Keep it concise and scannable.\n\n"
        )
    return (
        "[MODE: NARRATIVE_FIRST]\n"
        "Write in connected paragraphs with context and reasoning. "
        "Avoid bullet points unless explicitly requested.\n\n"
    )


def build_user_turn(query: str, retrieved: List[Tuple[Dict[str, Any], float]], persona_hint: str) -> str:
    ctx = format_excerpts(retrieved)
    persona_block = f"\n\nConversation focus:\n{persona_hint}\n" if persona_hint else ""
    return (
        mode_hint(query)
        + "Use the following Democracia+ excerpts as reference to answer the question.\n"
        + "Rules:\n"
        + "- Use only the excerpts as factual basis.\n"
        + "- If excerpts are insufficient, say what is missing.\n"
        + "- Do not mirror the formatting of the excerpts; default to narrative explanation unless a checklist/summary is explicitly requested.\n\n"
        + f"EXCERPTS:\n{ctx}"
        + f"{persona_block}\n\n"
        + f"QUESTION:\n{query}"
    )


def call_claude(api_key: str, model: str, temperature: float, max_tokens: int, system_prompt: str, messages: List[Dict[str, str]]) -> str:
    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )
    return "".join([b.text for b in resp.content if getattr(b, 'type', None) == 'text'])
