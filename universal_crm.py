import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import io
import time
import re
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image
# --- FIX POUR L'ERREUR NAMEERROR COMPONENTS ---
import streamlit.components.v1 as components

# Import Gestion des Cookies
try:
    import extra_streamlit_components as stx
except ImportError:
    st.error("⚠️ Librairie manquante : 'extra-streamlit-components'.")
    st.stop()

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Librairie manquante : 'streamlit-sortables'.")
    st.stop()

# --- CONFIGURATION PAGE ---
st.set_page_config(page_title="Universal CRM SaaS", page_icon="🚀", layout="wide")

# --- INITIALISATION SUPABASE ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Erreur connexion Supabase : {e}")
        st.stop()

supabase = init_connection()

# --- PONT JAVASCRIPT (Transforme # en ? pour le Reset Password) ---
components.html(
    """
    <script>
    var hash = window.location.hash;
    if (hash && (hash.includes('type=recovery') || hash.includes('access_token'))) {
        var newUrl = window.location.origin + window.location.pathname + hash.replace('#', '?');
        window.location.href = newUrl;
    }
    </script>
    """, height=0
)

# --- GESTION DES COOKIES ET ÉTAT ---
cookie_manager = stx.CookieManager()

if 'user' not in st.session_state: st.session_state.user = None
if 'profile' not in st.session_state: st.session_state.profile = None

# Détection Mode Récupération
is_recovery_mode = st.query_params.get("type") == "recovery"

# --- RECONNEXION AUTO ---
if not st.session_state.user and not is_recovery_mode:
    time.sleep(0.1)
    refresh_token = cookie_manager.get("sb_refresh_token")
    if refresh_token:
        try:
            res = supabase.auth.refresh_session(refresh_token)
            if res.user and res.session:
                p_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                if p_data:
                    st.session_state.user = res.user
                    st.session_state.profile = p_data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
        except: cookie_manager.delete("sb_refresh_token")

# --- FONCTIONS ---
def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    st.query_params.clear()
    time.sleep(0.5)
    st.rerun()

# ==========================================
# 🔑 ÉCRAN RÉCUPÉRATION (RESET PASSWORD)
# ==========================================
if is_recovery_mode:
    st.markdown("<h1 style='text-align: center;'>🔑 Nouveau mot de passe</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("recovery_form"):
            new_p = st.text_input("Nouveau mot de passe", type="password")
            if st.form_submit_button("Mettre à jour mon mot de passe", use_container_width=True):
                try:
                    supabase.auth.update_user({"password": new_p})
                    st.success("✅ Mis à jour ! Veuillez vous connecter.")
                    time.sleep(2)
                    st.query_params.clear()
                    logout()
                except Exception as e: st.error(f"Erreur : {e}")
    st.stop()

# ==========================================
# 🔐 ÉCRAN CONNEXION
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    p_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                    if p_data:
                        st.session_state.user = res.user
                        st.session_state.profile = p_data[0]
                        if res.session:
                            cookie_manager.set("sb_refresh_token", res.session.refresh_token)
                        st.rerun()
                except: st.error("Identifiants incorrects ou mail non confirmé.")
    st.stop()

# ==========================================
# 🚀 APPLICATION PRINCIPALE
# ==========================================
MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name', 'Utilisateur')}")
    st.caption(f"Rôle : {MY_ROLE}")
    st.divider()
    if st.button("Se déconnecter", use_container_width=True, type="primary"): logout()

st.title("Universal CRM SaaS 🚀")

# Onglets par rôle
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin", "super_admin"]:
    tabs_list += ["3. ⚙️ Configuration", "4. 👥 Utilisateurs"]
tabs = st.tabs(tabs_list)

# --- REPRENDRE ICI VOS ONGLETS DE GESTION HABITUELS ---
with tabs[0]:
    st.info("Système débloqué. Vous pouvez créer des dossiers.")
