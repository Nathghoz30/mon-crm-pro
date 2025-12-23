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

# --- GESTION DES COOKIES ET ÉTAT ---
cookie_manager = stx.CookieManager()

if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile' not in st.session_state:
    st.session_state.profile = None

# Compteurs pour les resets automatiques d'interface
if 'form_reset_id' not in st.session_state:
    st.session_state.form_reset_id = 0
if 'upload_reset_id' not in st.session_state:
    st.session_state.upload_reset_id = 0

# --- 1. DÉTECTION MODE RÉCUPÉRATION (V28 - PRIORITÉ) ---
# On regarde si l'URL contient "?type=recovery"
is_recovery_mode = st.query_params.get("type") == "recovery"

# --- 2. RECONNEXION AUTO (Sauf si on est en train de changer de mot de passe) ---
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
    time.sleep(0.5)
    st.rerun()

def upload_file(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(path, file_bytes, {"content-type": file.type, "upsert": "true"})
        return supabase.storage.from_("fichiers").get_public_url(path)
    except: return None

def merge_files_to_pdf(file_urls):
    merger = PdfWriter()
    for url in file_urls:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                f_data = io.BytesIO(response.content)
                if url.lower().endswith('.pdf'):
                    reader = PdfReader(f_data)
                    for page in reader.pages: merger.add_page(page)
                elif url.lower().endswith(('.png', '.jpg', '.jpeg')):
                    img = Image.open(f_data)
                    if img.mode == 'RGBA': img = img.convert('RGB')
                    img_pdf = io.BytesIO()
                    img.save(img_pdf, format='PDF')
                    img_pdf.seek(0)
                    merger.add_page(PdfReader(img_pdf).pages[0])
        except: continue
    output = io.BytesIO()
    merger.write(output)
    return output.getvalue()

# ==========================================
# 🔑 ÉCRAN RÉCUPÉRATION (V28)
# ==========================================
if is_recovery_mode:
    st.markdown("<h1 style='text-align: center;'>🔑 Nouveau mot de passe</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.info("Saisissez votre nouveau mot de passe ci-dessous pour sécuriser votre accès.")
        with st.form("recovery_form"):
            new_pass = st.text_input("Nouveau mot de passe", type="password")
            conf_pass = st.text_input("Confirmer le mot de passe", type="password")
            if st.form_submit_button("Valider le nouveau mot de passe", use_container_width=True):
                if len(new_pass) < 6:
                    st.error("Minimum 6 caractères.")
                elif new_pass != conf_pass:
                    st.error("Les mots de passe diffèrent.")
                else:
                    try:
                        # Mise à jour du mot de passe
                        supabase.auth.update_user({"password": new_pass})
                        st.success("✅ Mot de passe mis à jour !")
                        time.sleep(2)
                        # On nettoie tout et on renvoie au login propre
                        st.query_params.clear()
                        logout()
                    except Exception as e:
                        st.error(f"Erreur : {e}")
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
                    st.session_state.user = res.user
                    profile_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                    if profile_data:
                        st.session_state.profile = profile_data[0]
                        if res.session:
                            cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
                        st.rerun()
                except Exception as e:
                    st.error(f"Identifiants invalides ou compte non confirmé.")
    st.stop()

# ==========================================
# 🚀 CRM MAIN APP
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

# --- ONGLET 1 : CREATION ---
with tabs[0]:
    st.header("Créer un dossier")
    acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if acts:
        act_sel = st.selectbox("Activité", [a['name'] for a in acts])
        a_id = next(a['id'] for a in acts if a['name'] == act_sel)
        cols = supabase.table("collections").select("*").eq("activity_id", a_id).execute().data
        if cols:
            col_sel = st.selectbox("Modèle", [c['name'] for c in cols])
            s_col = next(c for c in cols if c['name'] == col_sel)
            f_id = st.session_state.form_reset_id
            
            data, f_map, m_addr = {}, {}, ""
            for i, f in enumerate(s_col['fields']):
                k = f"f_{s_col['id']}_{i}_{f['name']}_{f_id}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Texte Court":
                    val = st.text_input(f['name'], key=k)
                    data[f['name']] = val
                    if "adresse" in f['name'].lower() and "travaux" not in f['name'].lower(): m_addr = val
                elif f['type'] == "Adresse Travaux":
                    chk = st.checkbox(f"Copier siège ({m_addr})", key=f"chk_{k}")
                    if chk:
                        st.session_state[k] = m_addr
                        val = st.text_input(f['name'], key=k, disabled=True)
                    else: val = st.text_input(f['name'], key=k)
                    data[f['name']] = val
                elif f['type'] == "Fichier/Image": f_map[f['name']] = st.file_uploader(f['name'], accept_multiple_files=True, key=k)
                else: data[f['name']] = st.text_input(f['name'], key=k)

            if st.button("💾 ENREGISTRER", type="primary", use_container_width=True):
                for fn, fl in f_map.items():
                    urls = []
                    if fl:
                        for fi in fl:
                            u = upload_file(fi, f"{MY_COMPANY_ID}/{s_col['id']}/{int(time.time())}_{fi.name}")
                            if u: urls.append(u)
                    data[fn] = urls
                supabase.table("records").insert({"collection_id": s_col['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                st.session_state.form_reset_id += 1
                st.success("Dossier créé !")
                time.sleep(1)
                st.rerun()

# --- ONGLET 2 : GESTION ---
with tabs[1]:
    st.header("Dossiers")
    recs = supabase.table("records").select("*, collections(name, fields)").order('created_at', desc=True).execute().data
    if recs:
        s_map = {}
        for r in recs:
            d = r['data']
            cl = next((v for k, v in d.items() if "nom" in k.lower() and "entreprise" not in k.lower()), "Client")
            ent = next((v for k, v in d.items() if "raison" in k.lower() or "société" in k.lower()), "")
            lbl = f"👤 {cl} | 🏢 {ent} | 📄 {r['collections']['name']} | {r['created_at'][:10]}"
            s_map[lbl] = r
        sel = st.selectbox("Rechercher", list(s_map.keys()))
        if sel:
            r = s_map[sel]
            with st.form(f"ed_{r['id']}"):
                new_d = r['data'].copy()
                for f in r['collections']['fields']:
                    if f['type'] not in ["Fichier/Image", "Section/Titre"]:
                        new_d[f['name']] = st.text_input(f['name'], value=r['data'].get(f['name'], ""))
                if st.form_submit_button("Mettre à jour"):
                    supabase.table("records").update({"data": new_d}).eq("id", r['id']).execute()
                    st.rerun()
            
            # Fichiers
            a_urls, f_cnt = [], 0
            for f in [x for x in r['collections']['fields'] if x['type'] == "Fichier/Image"]:
                urls = r['data'].get(f['name'], [])
                a_urls += urls
                f_cnt += len(urls)
                with st.expander(f"📁 {f['name']} ({len(urls)})"):
                    for i, u in enumerate(urls):
                        col_v, col_d = st.columns([4, 1])
                        col_v.write(f"📄 [Fichier {i+1}]({u})")
                        if col_d.button("🗑️", key=f"del_{r['id']}_{f['name']}_{i}"):
                            urls.remove(u)
                            r['data'][f['name']] = urls
                            supabase.table("records").update({"data": r['data']}).eq("id", r['id']).execute()
                            st.rerun()
                    
                    up_k = f"up_{r['id']}_{f['name']}_{st.session_state.upload_reset_id}"
                    n_f = st.file_uploader("Ajouter", accept_multiple_files=True, key=up_k)
                    if n_f and st.button("Envoyer", key=f"bt_{r['id']}_{f['name']}"):
                        added = []
                        for nf in n_f:
                            u = upload_file(nf, f"{MY_COMPANY_ID}/{r['id']}_{int(time.time())}_{nf.name}")
                            if u: added.append(u)
                        r['data'][f['name']] = urls + added
                        supabase.table("records").update({"data": r['data']}).eq("id", r['id']).execute()
                        st.session_state.upload_reset_id += 1
                        st.rerun()
            
            if f_cnt >= 2:
                if st.button("📄 GÉNÉRER PDF COMPLET", type="primary", use_container_width=True):
                    pdf = merge_files_to_pdf(a_urls)
                    fname = re.sub(r'[^a-zA-Z0-9]', '_', f"Dossier_{r['id']}_{r['created_at'][:10]}") + ".pdf"
                    st.download_button("📥 Télécharger", data=pdf, file_name=fname, mime="application/pdf", use_container_width=True)

# --- ONGLET 4 : UTILISATEURS (V28) ---
if len(tabs) > 3:
    with tabs[3]:
        st.header("Gestion d'équipe")
        with st.expander("➕ Créer un compte"):
            with st.form("new_u"):
                u_e, u_p, u_r = st.text_input("Email"), st.text_input("Mot de passe temporaire"), st.selectbox("Rôle", ["user", "admin"])
                if st.form_submit_button("Ajouter"):
                    res = supabase.auth.sign_up({"email": u_e, "password": u_p})
                    supabase.table("profiles").insert({"id": res.user.id, "email": u_e, "company_id": MY_COMPANY_ID, "role": u_r, "full_name": u_e.split('@')[0]}).execute()
                    st.success("Compte créé !")
                    st.rerun()
        
        usrs = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if usrs:
            st.divider()
            c1, c2, c3 = st.columns([2, 1, 2])
            c1.write("**Collaborateur**"); c2.write("**Rôle**"); c3.write("**Actions**")
            for u in usrs:
                c1, c2, c3 = st.columns([2, 1, 2])
                c1.write(f"**{u['full_name']}**\n{u['email']}")
                c2.info(u['role'].upper())
                ac = c3.columns(3)
                if ac[0].button("📧", key=f"rc_{u['id']}", help="Renvoyer confirmation"):
                    supabase.auth.resend({"type": "signup", "email": u['email']})
                    st.toast("E-mail envoyé")
                if ac[1].button("🔑", key=f"rp_{u['id']}", help="Reset password"):
                    # REDIRECTION FORCÉE V28
                    app_url = st.secrets["APP_URL"] if "APP_URL" in st.secrets else "https://votre-url-streamlit.app"
                    supabase.auth.reset_password_for_email(u['email'], options={"redirect_to": f"{app_url}/?type=recovery"})
                    st.toast("Lien de reset envoyé")
                if u['id'] != st.session_state.user.id:
                    if ac[2].button("🗑️", key=f"du_{u['id']}", help="Supprimer"):
                        supabase.table("profiles").delete().eq("id", u['id']).execute()
                        st.rerun()
