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

# --- 1. LE PONT JAVASCRIPT (V29 - INDISPENSABLE) ---
# Ce code transforme l'URL de Supabase (#) en URL lisible par Streamlit (?)
components.html(
    """
    <script>
    var hash = window.location.hash;
    if (hash && (hash.includes('type=recovery') || hash.includes('access_token'))) {
        // On transforme le # en ? pour que Streamlit puisse lire les paramètres
        var newUrl = window.location.origin + window.location.pathname + hash.replace('#', '?');
        window.location.href = newUrl;
    }
    </script>
    """,
    height=0,
)

# --- GESTION DES COOKIES ET ÉTAT ---
cookie_manager = stx.CookieManager()

if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile' not in st.session_state:
    st.session_state.profile = None

# --- 2. DÉTECTION MODE RÉCUPÉRATION (LIT LES PARAMÈTRES ?) ---
# On vérifie si l'URL contient désormais "type=recovery"
is_recovery_mode = st.query_params.get("type") == "recovery"

# --- 3. RECONNEXION AUTO (Bloquée si on est en mode récupération) ---
if not st.session_state.user and not is_recovery_mode:
    time.sleep(0.1)
    refresh_token = cookie_manager.get("sb_refresh_token")
    if refresh_token:
        try:
            res = supabase.auth.refresh_session(refresh_token)
            if res.user and res.session:
                st.session_state.user = res.user
                profile_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                if profile_data:
                    st.session_state.profile = profile_data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
        except:
            cookie_manager.delete("sb_refresh_token")

# --- FONCTIONS UTILITAIRES ---
def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    st.query_params.clear()
    time.sleep(0.5)
    st.rerun()

# ==========================================
# 🔑 ÉCRAN RÉCUPÉRATION (V29)
# ==========================================
if is_recovery_mode:
    st.markdown("<h1 style='text-align: center;'>🔑 Nouveau mot de passe</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.info("Sécurité : Mode récupération activé. Veuillez définir votre nouveau mot de passe.")
        with st.form("recovery_form_v29"):
            new_pass = st.text_input("Nouveau mot de passe", type="password")
            conf_pass = st.text_input("Confirmer le mot de passe", type="password")
            if st.form_submit_button("Mettre à jour mon mot de passe", use_container_width=True):
                if len(new_pass) < 6:
                    st.error("Minimum 6 caractères.")
                elif new_pass != conf_pass:
                    st.error("Les mots de passe ne correspondent pas.")
                else:
                    try:
                        # Mise à jour du mot de passe
                        supabase.auth.update_user({"password": new_pass})
                        st.success("✅ Mot de passe mis à jour ! Redirection...")
                        time.sleep(2)
                        logout() # On déconnecte tout pour forcer le nouveau login
                    except Exception as e:
                        st.error(f"Erreur : {e}")
    st.stop()

# ==========================================
# 🔐 ÉCRAN CONNEXION (S'affiche si non connecté et pas en recovery)
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
                    st.session_state.user = res.user
                    profile_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                    if profile_data:
                        st.session_state.profile = profile_data[0]
                        if res.session:
                            cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
                        st.rerun()
                except:
                    st.error("Identifiants incorrects ou mail non confirmé.")
    st.stop()

# ==========================================
# 🚀 CRM MAIN APP (V26-V28 LOGIC)
# ==========================================
MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name')}")
    st.caption(f"Rôle : {MY_ROLE}")
    st.divider()
    if st.button("Se déconnecter", use_container_width=True, type="primary"):
        logout()

st.title("Universal CRM SaaS 🚀")

# Onglets par rôle
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin", "super_admin"]:
    tabs_list += ["3. ⚙️ Configuration", "4. 👥 Utilisateurs"]
tabs = st.tabs(tabs_list)

# (Reste du code identique à la V28 pour la gestion des dossiers, fichiers et utilisateurs...)
# [Insérer ici le code de l'onglet 1, 2, 3 et 4 de la version précédente]
