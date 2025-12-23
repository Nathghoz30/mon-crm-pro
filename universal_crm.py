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
    st.error("⚠️ Librairie manquante : 'extra-streamlit-components'. Ajoutez-la à requirements.txt")
    st.stop()

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Librairie manquante : 'streamlit-sortables'. Ajoutez-la à requirements.txt")
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
        st.error(f"Erreur technique connexion Supabase : {e}")
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

# --- DÉTECTION MODE RÉCUPÉRATION (V27) ---
# On vérifie si l'URL contient "type=recovery"
is_recovery_mode = st.query_params.get("type") == "recovery"

# --- RECONNEXION AUTO ---
if not st.session_state.user:
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

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user = res.user
        profile_data = supabase.table("profiles").select("*").eq("id", user.id).execute().data
        if profile_data:
            st.session_state.user = user
            st.session_state.profile = profile_data[0]
            if res.session:
                cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
            st.success("Connexion réussie !")
            time.sleep(0.5)
            st.rerun()
    except Exception as e:
        st.error(f"Erreur : {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    time.sleep(0.5)
    st.rerun()

def get_siret_info(siret):
    if not siret: return None
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={siret.replace(' ', '')}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            results = response.json().get('results')
            if results:
                ent = results[0]
                siege = ent.get('siege', {})
                return {
                    "NOM": ent.get('nom_complet'),
                    "ADRESSE": siege.get('adresse'),
                    "VILLE": siege.get('libelle_commune'),
                    "CP": siege.get('code_postal'),
                    "TVA": ent.get('numero_tva_intracommunautaire')
                }
    except: pass
    return None

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
                lower_url = url.lower()
                if lower_url.endswith('.pdf'):
                    reader = PdfReader(f_data)
                    for page in reader.pages: merger.add_page(page)
                elif lower_url.endswith(('.png', '.jpg', '.jpeg')):
                    img = Image.open(f_data)
                    if img.mode == 'RGBA': img = img.convert('RGB')
                    img_pdf_bytes = io.BytesIO()
                    img.save(img_pdf_bytes, format='PDF')
                    img_pdf_bytes.seek(0)
                    reader = PdfReader(img_pdf_bytes)
                    merger.add_page(reader.pages[0])
        except: continue
    output = io.BytesIO()
    merger.write(output)
    return output.getvalue()

# ==========================================
# 🔑 ÉCRAN DE RÉINITIALISATION (V27)
# ==========================================
if is_recovery_mode:
    st.markdown("<h1 style='text-align: center;'>🔑 Nouveau mot de passe</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.info("Saisissez votre nouveau mot de passe ci-dessous.")
        with st.form("reset_password_form"):
            new_password = st.text_input("Nouveau mot de passe", type="password")
            confirm_password = st.text_input("Confirmer le mot de passe", type="password")
            
            if st.form_submit_button("Mettre à jour mon mot de passe", use_container_width=True):
                if len(new_password) < 6:
                    st.error("Le mot de passe doit contenir au moins 6 caractères.")
                elif new_password != confirm_password:
                    st.error("Les mots de passe ne correspondent pas.")
                else:
                    try:
                        # Mise à jour effective du mot de passe dans Supabase
                        supabase.auth.update_user({"password": new_password})
                        st.success("✅ Mot de passe mis à jour ! Vous allez être redirigé vers la connexion.")
                        time.sleep(2)
                        # On nettoie l'URL et on déconnecte pour forcer le nouveau login
                        st.query_params.clear()
                        logout()
                    except Exception as e:
                        st.error(f"Erreur lors de la mise à jour : {e}")
    st.stop()

# ==========================================
# 🔐 ECRAN DE CONNEXION
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                login(email, password)
    st.stop()

# ==========================================
# 🚀 APPLICATION PRINCIPALE
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

# --- SUPER ADMIN : GESTION MULTI-TENANT ---
if MY_ROLE == "super_admin":
    sa_tabs = st.tabs(["🏢 Entreprises", "👀 Accéder au CRM"])
    with sa_tabs[0]:
        with st.form("create_comp"):
            c_name = st.text_input("Nom Entreprise")
            a_email = st.text_input("Email Admin")
            a_pass = st.text_input("Pass temporaire", type="password")
            if st.form_submit_button("Créer"):
                res_comp = supabase.table("companies").insert({"name": c_name}).execute()
                new_id = res_comp.data[0]['id']
                res_auth = supabase.auth.sign_up({"email": a_email, "password": a_pass})
                supabase.table("profiles").insert({"id": res_auth.user.id, "email": a_email, "company_id": new_id, "role": "admin", "full_name": c_name}).execute()
                st.success("Créé !")
    with sa_tabs[1]:
        all_comps = supabase.table("companies").select("*").execute().data
        comp_map = {c['name']: c['id'] for c in all_comps}
        target = st.selectbox("Voir en tant que :", list(comp_map.keys()))
        if target: MY_COMPANY_ID = comp_map[target]

# --- ONGLETS CRM ---
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin", "super_admin"]:
    tabs_list += ["3. ⚙️ Configuration", "4. 👥 Utilisateurs"]
tabs = st.tabs(tabs_list)

# ONGLET 1 : NOUVEAU
with tabs[0]:
    st.header("Créer un dossier")
    acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if acts:
        act_choice = st.selectbox("Activité", [a['name'] for a in acts])
        act_id = next(a['id'] for a in acts if a['name'] == act_choice)
        cols = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        if cols:
            col_choice = st.selectbox("Modèle", [c['name'] for c in cols])
            sel_col = next(c for c in cols if c['name'] == col_choice)
            fields = sel_col['fields']
            f_id = st.session_state.form_reset_id
            
            # SIRET AUTO-FILL
            if any(f['type'] == "SIRET" for f in fields):
                with st.expander("⚡ Remplissage SIRET"):
                    cs, cb = st.columns([3, 1])
                    s_in = cs.text_input("SIRET", key=f"s_s_{f_id}")
                    if cb.button("Remplir"):
                        inf = get_siret_info(s_in)
                        if inf:
                            for i, f in enumerate(fields):
                                k = f"f_{sel_col['id']}_{i}_{f['name']}_{f_id}"
                                n = f['name'].lower()
                                if f['type'] == 'SIRET': st.session_state[k] = s_in
                                elif "nom" in n or "sociale" in n: st.session_state[k] = inf['NOM']
                                elif "adresse" in n and "travaux" not in n: st.session_state[k] = inf['ADRESSE']
                            st.rerun()

            # FORMULAIRE
            data, f_map, main_addr = {}, {}, ""
            for i, f in enumerate(fields):
                k = f"f_{sel_col['id']}_{i}_{f['name']}_{f_id}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Texte Court":
                    val = st.text_input(f['name'], key=k)
                    data[f['name']] = val
                    if "adresse" in f['name'].lower() and "travaux" not in f['name'].lower(): main_addr = val
                elif f['type'] == "Adresse Travaux":
                    chk = st.checkbox(f"Identique au siège ({main_addr})", key=f"chk_{k}")
                    if chk:
                        st.session_state[k] = main_addr
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
                            u = upload_file(fi, f"{MY_COMPANY_ID}/{sel_col['id']}/{int(time.time())}_{fi.name}")
                            if u: urls.append(u)
                    data[fn] = urls
                supabase.table("records").insert({"collection_id": sel_col['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                st.session_state.form_reset_id += 1
                st.success("Dossier créé !")
                time.sleep(1)
                st.rerun()

# ONGLET 2 : GESTION
with tabs[1]:
    st.header("📂 Gestion")
    recs = supabase.table("records").select("*, collections(name, fields)").order('created_at', desc=True).execute().data
    if recs:
        s_map = {}
        for r in recs:
            d = r['data']
            cl = next((v for k, v in d.items() if "nom" in k.lower() and "entreprise" not in k.lower()), "Inconnu")
            ent = next((v for k, v in d.items() if "raison" in k.lower() or "société" in k.lower()), "")
            lbl = f"👤 {cl} | 🏢 {ent} | 📄 {r['collections']['name']} | 📅 {r['created_at'][:10]}"
            s_map[lbl] = r
        sel = st.selectbox("Choisir dossier", list(s_map.keys()))
        if sel:
            r = s_map[sel]
            with st.form(f"ed_{r['id']}"):
                new_d = r['data'].copy()
                for f in r['collections']['fields']:
                    if f['type'] != "Fichier/Image" and f['type'] != "Section/Titre":
                        new_d[f['name']] = st.text_input(f['name'], value=r['data'].get(f['name'], ""))
                if st.form_submit_button("Sauvegarder"):
                    supabase.table("records").update({"data": new_d}).eq("id", r['id']).execute()
                    st.rerun()
            
            # GESTION FICHIERS & FUSION
            all_urls, f_count = [], 0
            for f in [x for x in r['collections']['fields'] if x['type'] == "Fichier/Image"]:
                urls = r['data'].get(f['name'], [])
                all_urls += urls
                f_count += len(urls)
                with st.expander(f"📁 {f['name']} ({len(urls)})"):
                    for i, u in enumerate(urls):
                        c1, c2 = st.columns([4, 1])
                        c1.write(f"📄 [Fichier {i+1}]({u})")
                        if c2.button("❌", key=f"df_{r['id']}_{f['name']}_{i}"):
                            urls.remove(u)
                            r['data'][f['name']] = urls
                            supabase.table("records").update({"data": r['data']}).eq("id", r['id']).execute()
                            st.rerun()
                    up_k = f"up_{r['id']}_{f['name']}_{st.session_state.upload_reset_id}"
                    n_f = st.file_uploader(f"Ajouter", accept_multiple_files=True, key=up_k)
                    if n_f and st.button(f"Envoyer", key=f"bt_{r['id']}_{f['name']}"):
                        added = []
                        for nf in n_f:
                            u = upload_file(nf, f"{MY_COMPANY_ID}/{r['id']}_{int(time.time())}_{nf.name}")
                            if u: added.append(u)
                        r['data'][f['name']] = urls + added
                        supabase.table("records").update({"data": r['data']}).eq("id", r['id']).execute()
                        st.session_state.upload_reset_id += 1
                        st.rerun()
            
            if f_count >= 2:
                if st.button("📄 GENERER PDF COMPLET", use_container_width=True, type="primary"):
                    pdf = merge_files_to_pdf(all_urls)
                    d_data = r['data']
                    cl = next((v for k,v in d_data.items() if "nom" in k.lower() and "entreprise" not in k.lower()), "Dossier")
                    ent = next((v for k,v in d_data.items() if any(x in k.lower() for x in ["raison", "société"])), "")
                    fname = re.sub(r'[^a-zA-Z0-9]', '_', f"Dossier_Complet_{cl}_{ent}_{r['created_at'][:10]}") + ".pdf"
                    st.download_button("📥 Télécharger", data=pdf, file_name=fname, mime="application/pdf", use_container_width=True)

            if MY_ROLE in ["admin", "super_admin"]:
                with st.expander("🗑️ Supprimer Dossier"):
                    if st.button("💀 Confirmer Suppression"):
                        supabase.table("records").delete().eq("id", r['id']).execute()
                        st.rerun()

# ONGLET 3 : CONFIG (Dossiers/Activités)
if len(tabs) > 2:
    with tabs[2]:
        st.header("⚙️ Configuration")
        # Logique de gestion des activités et modèles (Tri dynamique via Key inclus)
        acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        with st.form("new_a"):
            na = st.text_input("Nouvelle activité")
            if st.form_submit_button("Ajouter"):
                supabase.table("activities").insert({"name": na, "company_id": MY_COMPANY_ID}).execute()
                st.rerun()
        if acts:
            a_sel = st.selectbox("Gérer Modèles pour :", [a['name'] for a in acts])
            a_id = next(a['id'] for a in acts if a['name'] == a_sel)
            with st.expander("➕ Nouveau Modèle"):
                m_n = st.text_input("Nom Modèle")
                if st.button("Créer Modèle Vide"):
                    supabase.table("collections").insert({"name": m_n, "activity_id": a_id, "fields": []}).execute()
                    st.rerun()
            
            ms = supabase.table("collections").select("*").eq("activity_id", a_id).execute().data
            for m in ms:
                with st.expander(f"📝 {m['name']}"):
                    t_k = f"tk_{m['id']}"
                    if t_k not in st.session_state: st.session_state[t_k] = 0
                    labels = [f"{f['name']} [{f['type']}]" for f in m['fields']]
                    sorted_l = sort_items(labels, key=f"s_{m['id']}_{st.session_state[t_k]}")
                    if st.button("💾 Sauver Ordre", key=f"sv_{m['id']}"):
                        new_f = []
                        for sl in sorted_l:
                            for f in m['fields']:
                                if f"{f['name']} [{f['type']}]" == sl: new_f.append(f); break
                        supabase.table("collections").update({"fields": new_f}).eq("id", m['id']).execute()
                        st.success("Trié !")

# ONGLET 4 : UTILISATEURS (Console de gestion V26)
if len(tabs) > 3:
    with tabs[3]:
        st.header("👥 Gestion de l'équipe")
        with st.expander("➕ Ajouter un collaborateur"):
            with st.form("add_u"):
                ue, up, ur = st.text_input("Email"), st.text_input("Pass temporaire", type="password"), st.selectbox("Rôle", ["user", "admin"])
                if st.form_submit_button("Créer"):
                    res = supabase.auth.sign_up({"email": ue, "password": up})
                    supabase.table("profiles").insert({"id": res.user.id, "email": ue, "company_id": MY_COMPANY_ID, "role": ur, "full_name": ue.split('@')[0]}).execute()
                    st.rerun()
        
        usrs = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if usrs:
            st.divider()
            cols = st.columns([2, 1, 2])
            cols[0].write("**Utilisateur**"); cols[1].write("**Rôle**"); cols[2].write("**Actions**")
            for u in usrs:
                c1, c2, c3 = st.columns([2, 1, 2])
                c1.write(f"**{u['full_name']}**\n{u['email']}")
                c2.info(u['role'].upper())
                ac = c3.columns(3)
                if ac[0].button("📧", key=f"rc_{u['id']}", help="Renvoyer confirmation"):
                    supabase.auth.resend({"type": "signup", "email": u['email']})
                    st.toast("E-mail renvoyé")
                if ac[1].button("🔑", key=f"rp_{u['id']}", help="Reset password"):
                    supabase.auth.reset_password_for_email(u['email'])
                    st.toast("Lien de reset envoyé")
                if u['id'] != st.session_state.user.id:
                    if ac[2].button("🗑️", key=f"du_{u['id']}", help="Supprimer"):
                        supabase.table("profiles").delete().eq("id", u['id']).execute()
                        st.rerun()
