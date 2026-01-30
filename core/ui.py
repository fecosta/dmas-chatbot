import streamlit as st

_CSS = """
<style>
/* Global layout */
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1120px; }
section[data-testid="stSidebar"] { border-right: 1px solid rgba(15, 23, 42, 0.10); }

/* Typography */
h1, h2, h3 { letter-spacing: -0.02em; }
.muted { color: rgba(15,23,42,.65); }

/* Card */
.dplus-card {
  background: #fff;
  border: 1px solid rgba(15,23,42,.10);
  border-radius: 16px;
  padding: 14px 16px;
  box-shadow: 0 1px 10px rgba(2,6,23,.04);
}
.dplus-card + .dplus-card { margin-top: 10px; }

/* Pills */
.dplus-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid rgba(15,23,42,.12);
  background: rgba(15,23,42,.02);
}

/* Chat bubbles */
[data-testid="stChatMessage"]{
  border: 1px solid rgba(15,23,42,.08);
  border-radius: 16px;
  padding: 8px 10px;
  margin-bottom: 10px;
  background: #fff;
}
[data-testid="stChatMessage"] p { margin-bottom: 0.35rem; }
</style>
"""

def apply_ui() -> None:
    """Injects light CSS polish. Safe: no feature changes."""
    st.markdown(_CSS, unsafe_allow_html=True)

def sidebar_brand(title: str = "🗳️ D+ Chatbot", subtitle: str = "Democracia+ knowledge assistant") -> None:
    st.markdown(f"## {title}")
    st.caption(subtitle)
    st.markdown("---")

def page_header(title: str, subtitle: str = "") -> None:
    subtitle_html = f'<div class="muted" style="margin-top:6px;">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="dplus-card">
          <div style="font-size:24px;font-weight:800;line-height:1.2;">{title}</div>
          {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

def pill(label: str, value: str) -> None:
    st.markdown(
        f"""<span class="dplus-pill"><b style="margin-right:6px;">{label}:</b> {value}</span>""",
        unsafe_allow_html=True,
    )

def icon(name: str, size: str = "1em", color: str = "inherit") -> str:
    return f'<i class="bi bi-{name}" style="font-size:{size}; color:{color};"></i>'