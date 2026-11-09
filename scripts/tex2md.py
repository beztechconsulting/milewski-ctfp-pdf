#!/usr/bin/env python3
"""Convert one CTFP chapter (src/content/<n>/*.tex) to GitHub-flavored Markdown.

The book's LaTeX relies on custom macros (\\src, snip, \\code, \\newterm, ...)
that pandoc doesn't know, so we expand them here and then hand the result to
pandoc. Only the Haskell snippets are inlined.

Usage: tex2md.py <chapter-dir> <out-dir>
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
WORDS = Path("/usr/share/dict/words")

# category.tex ends lines with '%' (TeX comment-continuation) and uses \symbf,
# which MathJax/KaTeX don't support; normalize both for Markdown output.
MACROS = (
    (SRC / "category.tex").read_text().replace("%\n", "\n").replace("\\symbf", "\\mathbf")
    + "\n\\newcommand{\\Colon}{::}\n\n"
)


def balanced(s, i):
    """Return (content, end) for the {...} group whose '{' is at s[i]."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
    raise ValueError("unbalanced braces")


def sub_cmd(s, name, fn):
    """Replace \\name{arg}... occurrences, where fn(arg) gives the new text."""
    out, pos = [], 0
    for m in re.finditer(r"\\" + name + r"(?![a-zA-Z])\{", s):
        if m.start() < pos:
            continue
        arg, end = balanced(s, m.end() - 1)
        out.append(s[pos : m.start()])
        out.append(fn(arg))
        pos = end
    out.append(s[pos:])
    return "".join(out)


def code_inline(arg):
    # "{[}" / "{]}" is LaTeX's way of protecting brackets; in \verb it'd stay literal.
    arg = arg.replace("{[}", "[").replace("{]}", "]")
    arg = re.sub(r"\\([_&%#$])", r"\1", arg)
    for d in "|!+~^":
        if d not in arg:
            return f"\\verb{d}{arg}{d}"
    return f"\\texttt{{{arg}}}"


def is_word(w):
    if not WORDS.exists():
        return False
    return w.lower() in {x.strip().lower() for x in WORDS.open(errors="ignore")}


def lettrine(s):
    def fix(m):
        letter, rest = m.group(1), m.group(2)
        if letter in "AI":
            first = re.match(r"[A-Za-z]+", rest)
            if not first or not is_word(letter + first.group(0)):
                return f"{letter} {rest}"
        return letter + rest

    return re.sub(r"\\lettrine(?:\[[^\]]*\])?\{([^}]*)\}\{([^}]*)\}", fix, s)


def preprocess(tex, chapter_dir):
    tex = re.sub(r"^% !TEX root.*\n", "", tex)

    def inline_src(m):
        name = m.group(1)
        text = (chapter_dir / "code" / "haskell" / f"{name}.hs").read_text()
        return "\\begin{minted}{haskell}\n" + text.rstrip("\n") + "\n\\end{minted}\n"

    tex = re.sub(r"\\src\{([^}]+)\}(?:\[[^\]]*\])?", inline_src, tex)
    tex = re.sub(r"\\begin\{snip\}(?:\[[^\]]*\])?\{([^}]*)\}", r"\\begin{minted}{\1}", tex)
    tex = tex.replace("\\end{snip}", "\\end{minted}")
    tex = re.sub(r"\\begin\{snipv\}", "\\\\begin{minted}{text}", tex)
    tex = tex.replace("\\end{snipv}", "\\end{minted}")
    tex = re.sub(r"\\ensuremath\{\\Colon\}", "::", tex)
    tex = lettrine(tex)
    tex = sub_cmd(tex, "newterm", lambda a: f"\\emph{{{a}}}")
    tex = sub_cmd(tex, "code", code_inline)
    tex = re.sub(r"\\urlref\{([^}]*)\}", r"\\href{\1}", tex)
    # Cross-chapter links point at labels in other files; drop to plain text.
    tex = sub_cmd(tex, "hyperref", lambda a: a)
    tex = re.sub(r"\\hyperref\[[^\]]*\]", "", tex)
    return MACROS + tex


def main(chapter_dir, out_dir):
    chapter_dir, out_dir = Path(chapter_dir).resolve(), Path(out_dir)
    for tex_file in sorted(chapter_dir.glob("*.tex")):
        pre = preprocess(tex_file.read_text(), chapter_dir)
        # pandoc `-f latex` picks up the \newcommand macros prepended in MACROS
        res = subprocess.run(
            ["pandoc", "-f", "latex", "-t", "gfm-raw_html", "--wrap=none"],
            input=pre, capture_output=True, text=True, check=True,
        )
        dest = out_dir / chapter_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        # pandoc emits a figure as an image paragraph followed by its caption
        # paragraph; italicize the caption so the pairing is obvious.
        md = re.sub(r"(^!\[\]\([^)]*\)\n\n)([^\n]+)$", r"\1*\2*", res.stdout, flags=re.M)
        # a bare '|' inside a GFM table cell splits the cell, even in code spans
        md = "\n".join(
            re.sub(
                r"\$`[^`]*`\$|`[^`]*`",
                lambda m: m.group(0) if m.group(0).startswith("$") else m.group(0).replace("|", "\\|"),
                l,
            )
            if l.startswith("|") else l
            for l in md.split("\n")
        )
        (dest / f"{tex_file.stem}.md").write_text(md)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
        images = chapter_dir / "images"
        if images.is_dir():
            shutil.copytree(images, dest / "images", dirs_exist_ok=True)
        print(f"wrote {dest / (tex_file.stem + '.md')}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
