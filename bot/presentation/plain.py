"""Safe, deterministic plain-text rendering for QQ.

The model remains the source of the answer.  This module only changes the
presentation layer: it protects code and URLs, converts a deliberately small
set of LaTeX constructs, and removes Markdown display markers without
touching ordinary backslashes or C/C++ syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_PROTECTED = re.compile(r"(```[\s\S]*?```|`[^`\n]*`|https?://[^\s]+|file://[^\s]+)")
_MATH = re.compile(
    r"\$\$([\s\S]*?)\$\$|\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|"
    r"(?<!\$)\$([^\n$]+?)\$(?!\$)"
)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")

_SYMBOLS = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ",
    r"\pi": "π", r"\sigma": "σ", r"\phi": "φ", r"\omega": "ω",
    r"\in": "∈", r"\notin": "∉", r"\subseteq": "⊆", r"\subset": "⊂",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\sim": "∼",
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←",
    r"\pm": "±", r"\times": "×", r"\cdot": "·", r"\infty": "∞",
    r"\sum": "Σ", r"\prod": "Π", r"\int": "∫", r"\partial": "∂",
    r"\nabla": "∇", r"\circ": "°",
    r"\arcsin": "arcsin", r"\arccos": "arccos", r"\arctan": "arctan",
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tan", r"\log": "log", r"\ln": "ln",
}

_SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBSCRIPT = str.maketrans({
    **dict(zip("0123456789", "₀₁₂₃₄₅₆₇₈₉")),
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ",
    "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ",
    "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
})


@dataclass(frozen=True)
class SplitAnswer:
    parts: tuple[str, ...]
    truncated: bool = False


def _group(text: str, start: int) -> tuple[str, int] | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    return None


def _format_group(value: str) -> str:
    return re.sub(r"\s+", " ", _format_math(value)).strip()


def _accent_or_command(text: str, index: int) -> tuple[str, int] | None:
    for command in (r"\text", r"\mathrm", r"\mathbf", r"\operatorname"):
        if text.startswith(command, index):
            parsed = _group(text, index + len(command))
            if parsed:
                value, end = parsed
                return _format_group(value), end
    return None


def _format_math(text: str) -> str:
    """Convert supported LaTeX while preserving unknown syntax visibly."""
    out: list[str] = []
    index = 0
    while index < len(text):
        # Parse compound commands before the generic backslash handler.
        if text.startswith(r"\frac", index):
            numerator = _group(text, index + 5)
            if numerator:
                denominator = _group(text, numerator[1])
                if denominator:
                    left, right = _format_group(numerator[0]), _format_group(denominator[0])
                    out.append(f"({left})/({right})")
                    index = denominator[1]
                    continue
        if text.startswith(r"\sqrt", index):
            radicand = _group(text, index + 5)
            if radicand:
                out.append(f"√({_format_group(radicand[0])})")
                index = radicand[1]
                continue
        if text[index] == "\\":
            formatted = _accent_or_command(text, index)
            if formatted:
                value, index = formatted
                out.append(value)
                continue
            matched = False
            for command, symbol in sorted(_SYMBOLS.items(), key=lambda item: -len(item[0])):
                if text.startswith(command, index):
                    out.append(symbol)
                    index += len(command)
                    matched = True
                    break
            if matched:
                continue
            # Common spacing/size commands have no visual meaning in plain QQ.
            if text.startswith((r"\left", r"\right", r"\,", r"\!"), index):
                index += 5 if text.startswith((r"\left", r"\right"), index) else 2
                continue
            # Keep unknown commands visible instead of deleting mathematical data.
            out.append("\\")
            index += 1
            continue
        if text[index] in "^_":
            marker = text[index]
            index += 1
            if index < len(text) and text[index] == "{":
                parsed = _group(text, index)
                if parsed:
                    value, index = parsed
                    value = _format_group(value)
                else:
                    value = "?"
            elif index < len(text):
                value = text[index]
                index += 1
            else:
                out.append(marker)
                break
            table = _SUPERSCRIPT if marker == "^" else _SUBSCRIPT
            converted = value.translate(table)
            out.append(converted if converted != value else marker + value)
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _format_math_match(match: re.Match[str]) -> str:
    body = next((value for value in match.groups() if value is not None), "")
    # Dollar signs also denote money.  Treat a dollar pair as math only when
    # there is a reliable operator/command or a single variable.
    if match.group(4) is not None and not (
        re.search(r"\\[A-Za-z]+|[=^_+\-*/]|[π√]", body)
        or re.fullmatch(r"\s*[A-Za-z]\s*", body)
    ):
        return match.group(0)
    return _format_math(body)


def _protect(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def replace(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00P{len(protected) - 1}\x00"

    return _PROTECTED.sub(replace, text), protected


def _restore(text: str, protected: list[str]) -> str:
    for index, value in enumerate(protected):
        text = text.replace(f"\x00P{index}\x00", value)
    return text


def format_answer(text: str) -> str:
    """Return readable QQ text without executing or dropping model markup."""
    if not isinstance(text, str):
        return ""
    value, protected = _protect(text.replace("\r\n", "\n"))
    value = _MATH.sub(_format_math_match, value)
    # Some providers emit short formulas without delimiters.  Only invoke the
    # math scanner when a known command is present; ordinary file paths and
    # prose backslashes remain untouched.
    if any(command in value for command in (*_SYMBOLS, r"\frac", r"\sqrt")):
        value = _format_math(value)
    value = _HEADING.sub("", value)
    value = _BOLD.sub(lambda match: match.group(1) or match.group(2) or "", value)
    value = _restore(value, protected)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _safe_boundaries(text: str) -> list[int]:
    boundaries = [match.end() for match in re.finditer(r"\n\s*\n|\n", text)]
    return sorted(set(boundaries + [len(text)]))


def split_for_qq(text: str, limit: int = 4000, max_parts: int = 2) -> SplitAnswer:
    """Split at paragraph/line boundaries and report unavoidable truncation."""
    if limit < 200 or max_parts < 1:
        raise ValueError("invalid QQ split limits")
    text = text.strip()
    if len(text) <= limit:
        return SplitAnswer((text,))
    parts: list[str] = []
    remaining = text
    truncated = False
    while remaining and len(parts) < max_parts:
        if len(remaining) <= limit:
            parts.append(remaining.strip())
            remaining = ""
            break
        candidates = [point for point in _safe_boundaries(remaining) if point <= limit]
        cut = max(candidates, default=0)
        if cut < 200:
            # Do not silently use the old token-as-character slice.  A hard
            # split is the last resort, and the caller marks it as truncated.
            cut = limit
            truncated = True
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        truncated = True
        if parts:
            parts[-1] = parts[-1].rstrip() + "\n\n（内容过长，后续部分未发送；请回复“继续”）"
    return SplitAnswer(tuple(part for part in parts if part), truncated)
