import os

from core.sidebar_ui import ensure_bootstrap_icons, render_sidebar
from core.supabase_client import restore_supabase_session
# Load .env locally (Render already injects env vars, so this is safe)
if os.path.exists(".env"):
    from dotenv import load_dotenv
    load_dotenv()
import streamlit as st

APP_NAME = "D+ Agora"
TAGLINE = "Conversational Intelligence for Organizations"

st.set_page_config(page_title=APP_NAME, page_icon="./static/shield-lock.svg", layout="wide")
ensure_bootstrap_icons()
render_sidebar(app_title=APP_NAME)

# ------------------------- Auth -------------------------
restore_supabase_session()

def _legal_footer() -> None:
    st.markdown(
        """
---
**Legal**

- [Privacy Policy](Privacy)
- [Terms & Conditions](Terms)
"""
    )

user = st.session_state.get("user")
role = st.session_state.get("role", "user")

if not user:
    st.title(APP_NAME)
    st.caption(TAGLINE)

    st.markdown(
        """
**D+ Agora permite transformar experiencia acumulada en capacidad instalada.**  
Lo que antes estaba disperso en documentos y equipos, ahora se convierte en diálogo estructurado que acompaña la acción.

Las organizaciones que impulsan liderazgo político y fortalecimiento democrático generan conocimiento valioso: metodologías,
aprendizajes, marcos conceptuales y experiencias territoriales. Sin embargo, ese conocimiento muchas veces queda fragmentado,
difícil de transferir o dependiente de personas específicas.

D+ Agora convierte ese acervo en una infraestructura de inteligencia conversacional para que tu organización pueda consultar,
entender y aplicar su conocimiento con claridad y coherencia.
        """
    )

    c1, c2 = st.columns([1, 2], gap="small")
    with c1:
        if st.button("Go to Login", type="primary", use_container_width=True):
            st.switch_page("pages/0_Login.py")
    _legal_footer()
    st.stop()

# Home page is NOT admin-only; admin checks should be on admin pages only.

st.title(f"{APP_NAME} — Democracia+")
st.caption(TAGLINE)

st.markdown(
    """
D+ Agora organiza el conocimiento institucional y lo vuelve accesible en tiempo real a través de conversación.

**Secciones**

- **Chat** — Interactúa con la base de conocimiento y obtén respuestas contextualizadas.
- **Admin → Users** — Gestiona cuentas y roles.
- **Admin → Data** — Gestiona documentos y procesamiento.
- **Admin → Model** — Configura modelos y parámetros de recuperación.

Usa la barra lateral para navegar.
"""
)

_legal_footer()

if role == "admin":
    missing = []
    for k in ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        if not os.environ.get(k):
            missing.append(k)

    if missing:
        st.warning("Missing env vars: " + ", ".join(missing))
    else:
        st.success("Environment looks good.")
