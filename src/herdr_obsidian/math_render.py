"""LaTeX mathematical notation to Unicode converter for GPUI Markdown and plain-text views."""

from __future__ import annotations

import re

DISPLAY_MATH_RE = re.compile(r"\$\$([\s\S]+?)\$\$")
INLINE_MATH_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)((?:\\.|[^$\\\n])+?)(?<!\\)\$(?!\$)")
CODE_SPAN_RE = re.compile(r"(`+[^`\n]+?`+)")

SUPERSCRIPT_MAP = str.maketrans(
    {
        "0": "⁰",
        "1": "¹",
        "2": "²",
        "3": "³",
        "4": "⁴",
        "5": "⁵",
        "6": "⁶",
        "7": "⁷",
        "8": "⁸",
        "9": "⁹",
        "+": "⁺",
        "-": "⁻",
        "−": "⁻",
        "=": "⁼",
        "(": "⁽",
        ")": "⁾",
        "a": "ᵃ",
        "b": "ᵇ",
        "c": "ᶜ",
        "d": "ᵈ",
        "e": "ᵉ",
        "f": "ᶠ",
        "g": "ᵍ",
        "h": "ʰ",
        "i": "ⁱ",
        "j": "ʲ",
        "k": "ᵏ",
        "l": "ˡ",
        "m": "ᵐ",
        "n": "ⁿ",
        "o": "ᵒ",
        "p": "ᵖ",
        "r": "ʳ",
        "s": "ˢ",
        "t": "ᵗ",
        "u": "ᵘ",
        "v": "ᵛ",
        "w": "ʷ",
        "x": "ˣ",
        "y": "ʸ",
        "z": "ᶻ",
        "A": "ᴬ",
        "B": "ᴮ",
        "D": "ᴰ",
        "E": "ᴱ",
        "G": "ᴳ",
        "H": "ᴴ",
        "I": "ᴵ",
        "J": "ᴶ",
        "K": "ᴷ",
        "L": "ᴸ",
        "M": "ᴹ",
        "N": "ᴺ",
        "O": "ᴼ",
        "P": "ᴾ",
        "R": "ᴿ",
        "T": "ᵀ",
        "U": "ᵁ",
        "V": "ⱽ",
        "W": "ᵂ",
    }
)

SUBSCRIPT_MAP = str.maketrans(
    {
        "0": "₀",
        "1": "₁",
        "2": "₂",
        "3": "₃",
        "4": "₄",
        "5": "₅",
        "6": "₆",
        "7": "₇",
        "8": "₈",
        "9": "₉",
        "+": "₊",
        "-": "₋",
        "−": "₋",
        "=": "₌",
        "(": "₍",
        ")": "₎",
        "a": "ₐ",
        "e": "ₑ",
        "h": "ₕ",
        "i": "ᵢ",
        "j": "ⱼ",
        "k": "ₖ",
        "l": "ₗ",
        "m": "ₘ",
        "n": "ₙ",
        "o": "ₒ",
        "p": "ₚ",
        "r": "ᵣ",
        "s": "ₛ",
        "t": "ₜ",
        "u": "ᵤ",
        "v": "ᵥ",
        "x": "ₓ",
        "β": "ᵦ",
        "γ": "ᵧ",
        "ρ": "ᵨ",
        "φ": "ᵩ",
        "ϕ": "ᵩ",
        "χ": "ᵪ",
    }
)

SUPERSCRIPT_CHARS = set(
    "0123456789+-−=()abcdefghijklmoprstuvwxyzABDEGHIJKLMNOPRTUVW "
)
SUBSCRIPT_CHARS = set("0123456789+-−=()aehijklmnoprstuvxβγρφϕχ, ")

BLACKBOARD_MAP = {
    "R": "ℝ",
    "Z": "ℤ",
    "N": "ℕ",
    "Q": "ℚ",
    "C": "ℂ",
    "E": "𝔼",
    "P": "ℙ",
    "F": "𝔽",
    "H": "ℍ",
    "S": "𝕊",
    "1": "𝟙",
}

CALLIGRAPHIC_MAP = {
    "A": "𝒜",
    "B": "ℬ",
    "C": "𝒞",
    "D": "𝒟",
    "E": "ℰ",
    "F": "ℱ",
    "G": "𝒢",
    "H": "ℋ",
    "I": "ℐ",
    "J": "𝒥",
    "K": "𝒦",
    "L": "ℒ",
    "M": "ℳ",
    "N": "𝒩",
    "O": "𝒪",
    "P": "𝒫",
    "Q": "𝒬",
    "R": "ℛ",
    "S": "𝒮",
    "T": "𝒯",
    "U": "𝒰",
    "V": "𝒱",
    "W": "𝒲",
    "X": "𝒳",
    "Y": "𝒴",
    "Z": "𝒵",
}

LATEX_COMMANDS: dict[str, str] = {
    # Lowercase Greek
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ϵ",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "varrho": "ϱ",
    "sigma": "σ",
    "varsigma": "ς",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "ϕ",
    "varphi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    # Uppercase Greek
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    # Calculus & Logic
    "infty": "∞",
    "partial": "∂",
    "nabla": "∇",
    "forall": "∀",
    "exists": "∃",
    "nexists": "∄",
    "emptyset": "∅",
    "varnothing": "∅",
    "in": "∈",
    "notin": "∉",
    "ni": "∋",
    "subset": "⊂",
    "supset": "⊃",
    "subseteq": "⊆",
    "supseteq": "⊇",
    "subsetneq": "⊊",
    "supsetneq": "⊋",
    "cup": "∪",
    "cap": "∩",
    "setminus": "∖",
    "land": "∧",
    "lor": "∨",
    "bigvee": "⋁",
    "bigwedge": "⋀",
    "neg": "¬",
    "lnot": "¬",
    # Arrows
    "to": "→",
    "rightarrow": "→",
    "longrightarrow": "⟶",
    "leftarrow": "←",
    "longleftarrow": "⟵",
    "leftrightarrow": "↔",
    "longleftrightarrow": "⟷",
    "mapsto": "↦",
    "longmapsto": "⟼",
    "implies": "⟹",
    "Longrightarrow": "⟹",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "iff": "⟺",
    "Longleftrightarrow": "⟺",
    "Leftrightarrow": "⇔",
    "uparrow": "↑",
    "downarrow": "↓",
    # Relations & Operators
    "le": "≤",
    "leq": "≤",
    "leqslant": "⩽",
    "ge": "≥",
    "geq": "⩾",
    "geqslant": "⩾",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "equiv": "≡",
    "sim": "∼",
    "simeq": "≃",
    "cong": "≅",
    "propto": "∝",
    "prec": "≺",
    "succ": "≻",
    "preceq": "⪯",
    "succeq": "⪰",
    "ll": "≪",
    "gg": "≫",
    "pm": "±",
    "mp": "∓",
    "times": "×",
    "cdot": "·",
    "div": "÷",
    "ast": "∗",
    "star": "⋆",
    "circ": "∘",
    "bullet": "•",
    "oplus": "⊕",
    "ominus": "⊖",
    "otimes": "⊗",
    "odot": "⊙",
    "sum": "∑",
    "prod": "∏",
    "coprod": "∐",
    "int": "∫",
    "iint": "∬",
    "iiint": "∭",
    "oint": "∮",
    # Delimiters & Geometry
    "lfloor": "⌊",
    "rfloor": "⌋",
    "lceil": "⌈",
    "rceil": "⌉",
    "langle": "⟨",
    "rangle": "⟩",
    "lvert": "|",
    "rvert": "|",
    "lVert": "‖",
    "rVert": "‖",
    "vert": "|",
    "Vert": "‖",
    "mid": " | ",
    "parallel": "∥",
    "perp": "⊥",
    "angle": "∠",
    "dots": "…",
    "ldots": "…",
    "cdots": "⋯",
    "vdots": "⋮",
    "ddots": "⋱",
    "blacksquare": "■",
    "square": "□",
    "qed": "∎",
    "triangle": "△",
    "triangleq": "≜",
    "colon": ":",
    # Named functions
    "max": "max",
    "min": "min",
    "sup": "sup",
    "inf": "inf",
    "arg": "arg",
    "argmax": "argmax",
    "argmin": "argmin",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "cot": "cot",
    "sec": "sec",
    "csc": "csc",
    "arcsin": "arcsin",
    "arccos": "arccos",
    "arctan": "arctan",
    "atan2": "atan2",
    "sinh": "sinh",
    "cosh": "cosh",
    "tanh": "tanh",
    "ln": "ln",
    "log": "log",
    "exp": "exp",
    "det": "det",
    "dim": "dim",
    "ker": "ker",
    "rank": "rank",
    "tr": "tr",
    "lim": "lim",
    "limsup": "lim sup",
    "liminf": "lim inf",
    "bmod": " mod ",
    "pmod": " mod ",
    # Sizing / spacing no-ops
    "left": "",
    "right": "",
    "big": "",
    "Big": "",
    "bigg": "",
    "Bigg": "",
    "bigl": "",
    "bigr": "",
    "Bigl": "",
    "Bigr": "",
    "biggl": "",
    "biggr": "",
    "displaystyle": "",
    "textstyle": "",
    "scriptstyle": "",
    "quad": "  ",
    "qquad": "   ",
    "enspace": " ",
    "thinspace": " ",
    "nbsp": " ",
}

COMBINING_ACCENTS: dict[str, str] = {
    "dot": "\u0307",
    "ddot": "\u0308",
    "dddot": "\u20db",
    "ddddot": "\u20dc",
    "hat": "\u0302",
    "widehat": "\u0302",
    "bar": "\u0304",
    "overline": "\u0304",
    "tilde": "\u0303",
    "widetilde": "\u0303",
    "vec": "\u20d7",
    "overrightarrow": "\u20d7",
    "check": "\u030c",
    "breve": "\u0306",
}


def _extract_brace_group(text: str, pos: int) -> tuple[str, int] | None:
    """If `text[pos:]` starts with optional whitespace + `{...}`, return `(inner, next_pos)`."""
    i = pos
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    if i >= n or text[i] != "{":
        return None
    depth = 0
    start = i + 1
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return text[start:], n


def _apply_combining(inner: str, combining_char: str) -> str:
    clean = inner.strip()
    if not clean:
        return ""
    if len(clean) == 1:
        return clean + combining_char
    return clean[0] + combining_char + clean[1:]


def _format_superscript(exp: str) -> str:
    s = exp.strip()
    if not s:
        return ""
    if s in ("∘", "°", r"\circ"):
        return "°"
    if s == "′" or s == "'":
        return "′"
    if all(ch in SUPERSCRIPT_CHARS for ch in s):
        return s.translate(SUPERSCRIPT_MAP)
    if len(s) == 1:
        return f"^{s}"
    return f"^({s})"


def _format_subscript(sub: str) -> str:
    s = sub.strip()
    if not s:
        return ""
    if all(ch in SUBSCRIPT_CHARS for ch in s):
        return s.translate(SUBSCRIPT_MAP)
    return f"_{s}"


def latex_to_unicode(expr: str, *, escape_md: bool = False) -> str:
    """Convert a LaTeX math string into clean Unicode mathematical notation."""
    s = expr.strip()
    if not s:
        return ""

    # 1. Pre-normalize common degree / prime / escaped punctuation sequences
    s = re.sub(r"\^\s*\{\s*\\circ\s*\}", "°", s)
    s = re.sub(r"\^\s*\\circ\b", "°", s)
    s = s.replace(r"\%", "%").replace(r"\_", "_").replace(r"\&", "&").replace(r"\$", "$")
    s = s.replace(r"\{", "⦃").replace(r"\}", "⦄")
    s = s.replace(r"\,", " ").replace(r"\;", " ").replace(r"\:", " ").replace(r"\!", "")

    # 2. Handle environments (\begin{aligned}, \begin{cases}, \begin{bmatrix}, etc.)
    def _repl_env(m: re.Match[str]) -> str:
        env = m.group(1).strip()
        body = m.group(2).strip()
        rows = [r.strip() for r in re.split(r"\\\\", body) if r.strip()]
        formatted_rows: list[str] = []
        for r in rows:
            cols = [c.strip() for c in r.split("&")]
            line_txt = "  ".join(c for c in cols if c)
            if env == "cases":
                formatted_rows.append(f"⎧ {line_txt}" if len(formatted_rows) == 0 else f"⎨ {line_txt}")
            elif "matrix" in env:
                formatted_rows.append(f"[ {line_txt} ]")
            else:
                formatted_rows.append(line_txt)
        return "\n".join(formatted_rows)

    s = re.sub(r"\\begin\{([a-zA-Z*]+)\}([\s\S]*?)\\end\{\1\}", _repl_env, s)
    s = s.replace("\\\\", "\n").replace("&", " ")

    # 3. Recursively expand multi-argument and unary brace commands (\frac, \sqrt, \text, \mathbf, etc.)
    for _ in range(8):
        changed = False
        out: list[str] = []
        i = 0
        n = len(s)
        while i < n:
            if s[i] == "\\":
                m_cmd = re.match(r"\\([a-zA-Z]+)", s[i:])
                if m_cmd:
                    cmd = m_cmd.group(1)
                    after_cmd = i + len(m_cmd.group(0))

                    # Binary commands: \frac{a}{b}, \dfrac{a}{b}, \tfrac{a}{b}, \binom{a}{b}
                    if cmd in ("frac", "dfrac", "tfrac", "binom"):
                        g1 = _extract_brace_group(s, after_cmd)
                        if g1:
                            g2 = _extract_brace_group(s, g1[1])
                            if g2:
                                num = latex_to_unicode(g1[0], escape_md=False)
                                den = latex_to_unicode(g2[0], escape_md=False)
                                if cmd == "binom":
                                    out.append(f"C({num}, {den})")
                                else:
                                    n_wrap = f"({num})" if any(c in num for c in " +-−") else num
                                    d_wrap = f"({den})" if any(c in den for c in " +-−*/") else den
                                    out.append(f"{n_wrap}/{d_wrap}")
                                i = g2[1]
                                changed = True
                                continue

                    # \underbrace{a}_{b} or \overbrace{a}^{b}
                    if cmd in ("underbrace", "overbrace"):
                        g1 = _extract_brace_group(s, after_cmd)
                        if g1:
                            inner = latex_to_unicode(g1[0], escape_md=False)
                            out.append(inner)
                            i = g1[1]
                            changed = True
                            continue

                    # \sqrt[n]{x} or \sqrt{x}
                    if cmd == "sqrt":
                        idx_pos = after_cmd
                        root_prefix = "√"
                        if idx_pos < n and s[idx_pos] == "[":
                            close_b = s.find("]", idx_pos + 1)
                            if close_b != -1:
                                deg = s[idx_pos + 1 : close_b].strip()
                                root_prefix = (
                                    "∛"
                                    if deg == "3"
                                    else ("∜" if deg == "4" else f"{_format_superscript(deg)}√")
                                )
                                idx_pos = close_b + 1
                        g1 = _extract_brace_group(s, idx_pos)
                        if g1:
                            rad = latex_to_unicode(g1[0], escape_md=False)
                            if len(rad) <= 2 and all(ch.isalnum() for ch in rad):
                                out.append(f"{root_prefix}{rad}")
                            else:
                                out.append(f"{root_prefix}({rad})")
                            i = g1[1]
                            changed = True
                            continue

                    # Text / font / operator wrappers
                    if cmd in (
                        "text",
                        "textrm",
                        "textit",
                        "textbf",
                        "texttt",
                        "mathrm",
                        "mathbf",
                        "boldsymbol",
                        "mathit",
                        "mathsf",
                        "mathtt",
                        "operatorname",
                        "mathbin",
                        "mathrel",
                        "substack",
                        "boxed",
                    ):
                        g1 = _extract_brace_group(s, after_cmd)
                        if g1:
                            inner = latex_to_unicode(g1[0], escape_md=False)
                            out.append(inner)
                            i = g1[1]
                            changed = True
                            continue

                    if cmd == "mathbb":
                        g1 = _extract_brace_group(s, after_cmd)
                        if g1:
                            inner = g1[0].strip()
                            out.append("".join(BLACKBOARD_MAP.get(ch, ch) for ch in inner))
                            i = g1[1]
                            changed = True
                            continue

                    if cmd == "mathcal":
                        g1 = _extract_brace_group(s, after_cmd)
                        if g1:
                            inner = g1[0].strip()
                            out.append("".join(CALLIGRAPHIC_MAP.get(ch, ch) for ch in inner))
                            i = g1[1]
                            changed = True
                            continue

                    if cmd in COMBINING_ACCENTS:
                        g1 = _extract_brace_group(s, after_cmd)
                        if g1:
                            inner = latex_to_unicode(g1[0], escape_md=False)
                            out.append(_apply_combining(inner, COMBINING_ACCENTS[cmd]))
                            i = g1[1]
                            changed = True
                            continue
                        # Also handle unbraced \dot x or \hat x
                        m_tok = re.match(r"\s*([a-zA-Z0-9]|\\[a-zA-Z]+)", s[after_cmd:])
                        if m_tok:
                            inner = latex_to_unicode(m_tok.group(1), escape_md=False)
                            out.append(_apply_combining(inner, COMBINING_ACCENTS[cmd]))
                            i = after_cmd + len(m_tok.group(0))
                            changed = True
                            continue

                    if cmd in LATEX_COMMANDS:
                        repl = LATEX_COMMANDS[cmd]
                        out.append(repl)
                        i = after_cmd
                        # Consume a single trailing space if command was followed by a letter/digit
                        if i < n and s[i] == " " and repl and not repl.endswith(" "):
                            if i + 1 < n and (s[i + 1].isalnum() or s[i + 1] == "\\"):
                                out.append(" ")
                            i += 1
                        changed = True
                        continue

            out.append(s[i])
            i += 1
        s = "".join(out)
        if not changed:
            break

    # 4. Handle superscripts ^{...} / ^x and subscripts _{...} / _x
    def _process_scripts(text: str) -> str:
        res: list[str] = []
        idx = 0
        length = len(text)
        while idx < length:
            ch = text[idx]
            if ch in ("^", "_"):
                is_sup = ch == "^"
                grp = _extract_brace_group(text, idx + 1)
                if grp:
                    inner = _process_scripts(grp[0])
                    res.append(_format_superscript(inner) if is_sup else _format_subscript(inner))
                    idx = grp[1]
                    continue
                if idx + 1 < length and text[idx + 1] not in " \t\n":
                    tok = text[idx + 1]
                    res.append(_format_superscript(tok) if is_sup else _format_subscript(tok))
                    idx += 2
                    continue
            res.append(ch)
            idx += 1
        return "".join(res)

    s = _process_scripts(s)

    # 5. Strip leftover grouping braces `{` and `}`, and restore escaped literal braces `⦃` / `⦄`
    s = s.replace("{", "").replace("}", "")
    s = s.replace("⦃", "{").replace("⦄", "}")

    # 6. Normalize spacing around binary relations & minus signs inside math
    s = re.sub(r"[ \t]+", " ", s).strip()

    if escape_md:
        # Escape `_` and `*` so CommonMark (`pulldown-cmark`) never turns `D_L(t) ... U_L(t)` into italics
        s = s.replace("_", r"\_").replace("*", r"\*")

    return s


def transform_markdown_math(md_text: str, *, escape_md: bool = True) -> str:
    """Replace `$$...$$` and `$...$` in Markdown text while preserving inline `` `code` `` spans."""
    if "$" not in md_text:
        return md_text

    # 1. Convert display math blocks `$$ ... $$` first
    def _repl_display(m: re.Match[str]) -> str:
        rendered = latex_to_unicode(m.group(1), escape_md=escape_md)
        lines = [ln.strip() for ln in rendered.splitlines() if ln.strip()]
        return "\n" + "\n".join(f"> **{ln}**" for ln in lines) + "\n"

    text = DISPLAY_MATH_RE.sub(_repl_display, md_text)

    # 2. Protect inline backtick code spans (`...`) before replacing inline `$...$`
    parts = CODE_SPAN_RE.split(text)
    out: list[str] = []
    for idx, part in enumerate(parts):
        if idx % 2 == 1:
            # Inside `code` span: leave untouched
            out.append(part)
        else:
            out.append(
                INLINE_MATH_RE.sub(
                    lambda m: latex_to_unicode(m.group(1), escape_md=escape_md),
                    part,
                )
            )
    return "".join(out)
