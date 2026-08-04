"""HTML email rendering — one layout, every message.

Email HTML is a hostile dialect: no external stylesheets, no web fonts, no
flexbox in half the clients people actually use, and a preview pane that
decides whether the message gets opened at all. So everything here is inline
styles on tables, one accent colour, and a layout that survives being
rendered by a fifteen-year-old engine.

Every send keeps the plain-text body as the first alternative. Text is the
version that survives everything — screen readers, strict corporate filters,
the terminal someone reads mail in — and it is also what clients quote when
replying. HTML is presentation, never the only copy of the information.
"""

from __future__ import annotations

from html import escape

#: The product's jade, hex-frozen: email clients cannot read CSS variables,
#: so the token is duplicated here by necessity. If the brand colour moves,
#: this is the one other place it lives.
ACCENT = "#1d7a5f"
INK = "#1c1b18"
MUTED = "#8a877e"
RULE = "#e8e6e0"
BG = "#f6f5f2"
CARD = "#ffffff"
DANGER = "#b3402a"

FONT = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def wrap(*, preheader: str, title: str, body_html: str, footer_links: list[tuple[str, str]]) -> str:
    """The shared shell: preheader, masthead, card, footer.

    The preheader is the sentence shown next to the subject in the inbox list
    — for most recipients it decides the open, so callers must pass the one
    figure that matters, not a description of the email.
    """
    links = " &nbsp;·&nbsp; ".join(
        f'<a href="{escape(href)}" style="color:{MUTED};text-decoration:underline;">{escape(label)}</a>'
        for label, href in footer_links
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:{BG};">
  <div style="display:none;max-height:0;overflow:hidden;">{escape(preheader)}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};">
    <tr><td align="center" style="padding:24px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;">
        <tr><td style="padding:0 4px 12px;font-family:{FONT};font-size:14px;font-weight:600;letter-spacing:0.04em;color:{ACCENT};">LedgerFlow</td></tr>
        <tr><td style="background:{CARD};border:1px solid {RULE};border-radius:12px;padding:28px;">
          <h1 style="margin:0 0 16px;font-family:{FONT};font-size:20px;line-height:1.3;color:{INK};">{escape(title)}</h1>
          {body_html}
        </td></tr>
        <tr><td style="padding:16px 4px;font-family:{FONT};font-size:12px;color:{MUTED};">{links}</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def hero(amount: str, caption: str, *, tone: str = "accent") -> str:
    """The one big number. `tone="danger"` for the weeks where it is zero."""
    colour = DANGER if tone == "danger" else ACCENT
    return (
        f'<p style="margin:0 0 4px;font-family:{FONT};font-size:32px;font-weight:700;'
        f'color:{colour};">{escape(amount)}</p>'
        f'<p style="margin:0 0 20px;font-family:{FONT};font-size:13px;color:{MUTED};">{escape(caption)}</p>'
    )


def figure_row(pairs: list[tuple[str, str]]) -> str:
    """Label/value pairs as one bordered row group."""
    rows = "".join(
        f'<tr><td style="padding:8px 0;font-family:{FONT};font-size:14px;color:{MUTED};">{escape(label)}</td>'
        f'<td align="right" style="padding:8px 0;font-family:{FONT};font-size:14px;color:{INK};'
        f'font-variant-numeric:tabular-nums;">{escape(value)}</td></tr>'
        for label, value in pairs
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-top:1px solid {RULE};border-bottom:1px solid {RULE};margin:0 0 20px;">{rows}</table>'
    )


def section(title: str) -> str:
    return (
        f'<p style="margin:0 0 8px;font-family:{FONT};font-size:11px;font-weight:600;'
        f'letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};">{escape(title)}</p>'
    )


def bullet_list(items: list[str]) -> str:
    rows = "".join(
        f'<li style="margin:0 0 6px;font-family:{FONT};font-size:14px;color:{INK};">{escape(item)}</li>'
        for item in items
    )
    return f'<ul style="margin:0 0 20px;padding-left:18px;">{rows}</ul>'


def note(text: str) -> str:
    return f'<p style="margin:0 0 20px;font-family:{FONT};font-size:13px;color:{MUTED};">{escape(text)}</p>'


def button(label: str, href: str) -> str:
    return (
        f'<a href="{escape(href)}" style="display:inline-block;padding:10px 20px;'
        f"font-family:{FONT};font-size:14px;font-weight:600;color:#ffffff;"
        f'background:{ACCENT};border-radius:8px;text-decoration:none;">{escape(label)}</a>'
    )
