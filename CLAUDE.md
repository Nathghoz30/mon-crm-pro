# CLAUDE.md — Mon CRM Pro

This file provides context for AI assistants working on this codebase.

---

## Project Overview

**Mon CRM Pro** is a no-code CRM and Document Management System (GED) built with Python, Streamlit, and Supabase. It allows businesses to manage client records, construction projects, or administrative files through dynamically configured forms — without modifying source code.

- **Language:** Python 3.9+
- **Framework:** Streamlit (web UI)
- **Backend:** Supabase (PostgreSQL + Auth + Storage)
- **License:** MIT
- **Author:** Nathan Ghozlan (Nathghoz30)

---

## Repository Structure

```
mon-crm-pro/
├── universal_crm.py     # Entire application — single monolithic file (423 lines)
├── requirements.txt     # Python dependencies (no version pinning)
├── README.md            # French-language user documentation
└── LICENSE              # MIT License
```

There is no `src/` directory, no test suite, no CI/CD pipeline, and no Docker setup. The project is intentionally lean.

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Configure Supabase credentials (see Secrets section below)

# Start the app
streamlit run universal_crm.py
```

The app runs on `http://localhost:8501` by default.

---

## Secrets & Configuration

There are **no `.env` files**. Streamlit's native secrets system is used.

Create `.streamlit/secrets.toml` (not tracked in git):

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-public-key"
```

These are loaded in the code via `st.secrets["SUPABASE_URL"]` and `st.secrets["SUPABASE_KEY"]`.

**Never commit `.streamlit/secrets.toml`** — it contains live credentials.

---

## Architecture

### Single-File Design

The entire application lives in `universal_crm.py`. It is organized into logical sections (not separate modules):

| Lines     | Section                          |
|-----------|----------------------------------|
| 1–42      | Imports & page config            |
| 44–48     | Session state initialization     |
| 51–128    | Core utility functions           |
| 130–175   | Authentication & role setup      |
| 177–266   | Tab 1 — Create Record            |
| 267–325   | Tab 2 — Manage Records           |
| 327–399   | Tab 3 — Configuration (admin)    |
| 400–423   | Tab 4 — User Management (admin)  |

### Supabase Connection

The Supabase client is a singleton created with `@st.cache_resource`:

```python
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()
```

Do not call `init_connection()` more than once per session; rely on the cached instance.

---

## Database Schema

All tables live in Supabase (PostgreSQL). The schema is defined in `README.md` and reproduced here.

### Tables

**`companies`**
```sql
id         BIGINT PRIMARY KEY
name       TEXT
```
One company per tenant. All data is scoped by `company_id`.

**`profiles`** (linked to Supabase Auth users)
```sql
id          UUID PRIMARY KEY   -- matches auth.users.id
email       TEXT
company_id  BIGINT REFERENCES companies(id)
role        TEXT               -- 'super_admin' | 'admin1' | 'admin2' | 'user'
full_name   TEXT
```

**`activities`** (top-level categories per company)
```sql
id          BIGINT PRIMARY KEY
name        TEXT NOT NULL UNIQUE
company_id  BIGINT
created_at  TIMESTAMPTZ
```

**`collections`** (record templates/models)
```sql
id          BIGINT PRIMARY KEY
name        TEXT NOT NULL
fields      JSONB NOT NULL     -- array of field definitions
activity_id BIGINT REFERENCES activities(id) ON DELETE CASCADE
created_at  TIMESTAMPTZ
```

**`records`** (user-created data entries)
```sql
id             BIGINT PRIMARY KEY
collection_id  BIGINT REFERENCES collections(id) ON DELETE CASCADE
data           JSONB NOT NULL   -- key-value map of field name → value
created_by     UUID             -- auth user id
created_at     TIMESTAMPTZ
```

### JSONB Field Schema

Each collection's `fields` column stores an array like:
```json
[
  {"name": "Raison Sociale", "type": "Texte Court"},
  {"name": "SIRET",           "type": "SIRET"},
  {"name": "Siège Social",    "type": "Adresse"},
  {"name": "Adresse Chantier","type": "Adresse Travaux"},
  {"name": "Remarques",       "type": "Texte Long"},
  {"name": "Documents",       "type": "Fichier/Image"},
  {"name": "1. Contact",      "type": "Section/Titre"}
]
```

### Supported Field Types

| Type             | Rendered As                                  |
|------------------|----------------------------------------------|
| `Texte Court`    | `st.text_input`                              |
| `Texte Long`     | `st.text_area`                               |
| `SIRET`          | `st.text_input` + SIRET auto-fill trigger    |
| `Adresse`        | `st.text_input` — captures to `address_buffer` |
| `Adresse Travaux`| `st.text_input` + checkbox to copy from `Adresse` |
| `Fichier/Image`  | `st.file_uploader` (multi-file) → Supabase Storage |
| `Section/Titre`  | `st.markdown` heading only (no data stored)  |

### Storage

Files are stored in the Supabase bucket `"fichiers"`.

Upload path pattern: `{company_id}/{collection_id}/{timestamp}_{filename}`

The bucket must be public with SELECT, INSERT, UPDATE, DELETE policies enabled.

---

## Role-Based Access Control

| Role          | Tab 1 | Tab 2 | Tab 3 Config | Tab 4 Users | Can add users | Can delete users |
|---------------|-------|-------|--------------|-------------|---------------|-----------------|
| `super_admin` | ✅    | ✅    | ✅           | ✅          | any role      | any user        |
| `admin1`      | ✅    | ✅    | ✅           | ✅          | admin2, user  | admin2, user    |
| `admin2`      | ✅    | ✅    | ❌           | ✅          | user only     | user only       |
| `user`        | ✅    | ✅    | ❌           | ❌          | —             | —               |

`super_admin` can also switch between companies via a selectbox rendered above the tabs.

---

## Key Functions

### `init_connection()` — `universal_crm.py:32`
Cached Supabase client. Uses `@st.cache_resource` for singleton behavior.

### `get_siret_info(siret)` — `universal_crm.py:51`
Calls the French government SIRET API:
```
GET https://recherche-entreprises.api.gouv.fr/search?q={siret}
```
Returns a dict with keys `NOM`, `ADRESSE`, `VILLE`, `CP` or `None` on failure.

### `login(email, password)` — `universal_crm.py:71`
Authenticates with Supabase Auth. Retries fetching the user `profiles` row up to 3 times (0.5s apart) to handle propagation delay after new user creation.

### `logout()` — `universal_crm.py:95`
Calls `supabase.auth.sign_out()`, clears session state, triggers rerun.

### `upload_file(file, path)` — `universal_crm.py:101`
Uploads a file to the `"fichiers"` Supabase Storage bucket and returns its public URL.

### `merge_files_to_pdf(file_urls)` — `universal_crm.py:108`
Downloads all files at the given URLs and merges them into a single PDF. Supports `.pdf`, `.png`, `.jpg`, `.jpeg`. RGBA images are converted to RGB before embedding.

---

## Session State Keys

| Key              | Type  | Purpose                                              |
|------------------|-------|------------------------------------------------------|
| `user`           | object| Supabase auth user object (None if logged out)       |
| `profile`        | dict  | Row from `profiles` table for current user           |
| `form_reset_id`  | int   | Incremented to force form fields to reset            |
| `config_updater` | int   | Incremented to force drag-and-drop widget re-render  |
| `t`              | list  | Temporary field list during new collection creation  |

Form field keys follow the pattern: `f_{model_id}_{field_index}_{field_name}_{form_reset_id}`

---

## Patterns & Conventions

### Streamlit Reruns
`st.rerun()` is called after any state-changing operation (insert, update, delete). This is the standard Streamlit pattern to reflect DB changes in the UI.

### Data Mutation Pattern
Records are never partially updated — the full `data` JSONB dict is re-sent on each update:
```python
supabase.table("records").update({"data": new_d}).eq("id", r['id']).execute()
```

### Error Handling
Most utility functions use broad `except` blocks returning `None` on failure. UI errors are shown via `st.error()`. This is acceptable for the current scale but should be improved if the codebase grows.

### Optional Imports
Two packages are guarded with `try/except ImportError` blocks that halt the app with a user-friendly error if missing: `extra-streamlit-components` and `streamlit-sortables`.

### No Tests
There is currently no test suite. All validation is done manually by running the app.

---

## Dependencies

```
streamlit               # Web UI framework
supabase                # Supabase Python client (Auth + DB + Storage)
pandas                  # DataFrame display in user management tab
requests                # HTTP calls to SIRET API and file downloads
streamlit-sortables     # Drag-and-drop field ordering
pypdf                   # PDF merging (PdfWriter, PdfReader)
Pillow                  # Image-to-PDF conversion
extra-streamlit-components  # Cookie manager (stx.CookieManager)
```

No versions are pinned in `requirements.txt`. If dependency issues arise, pin to known-good versions.

---

## Deployment

### Local
```bash
streamlit run universal_crm.py
```

### Streamlit Cloud
1. Push repo to GitHub
2. Connect at [share.streamlit.io](https://share.streamlit.io)
3. In **Advanced Settings**, paste secrets:
   ```
   SUPABASE_URL = "..."
   SUPABASE_KEY = "..."
   ```

---

## Development Guidelines for AI Assistants

1. **Read before editing.** The file is 423 lines. Read the full context around any function before modifying it.

2. **Single-file constraint.** All logic lives in `universal_crm.py`. Do not split into modules unless explicitly asked.

3. **Streamlit state awareness.** Streamlit reruns the entire script on each interaction. Any code outside conditionals or cached functions runs on every rerun. Be careful about infinite loops or duplicate operations.

4. **Form key uniqueness.** Form widget keys must be unique per render cycle. The `form_reset_id` and `config_updater` counters exist precisely to force Streamlit to re-render widgets after mutations.

5. **JSONB data model.** Fields in `collections.fields` are an ordered list (order matters — it controls form display order). `records.data` is a flat dict keyed by field name.

6. **Multi-tenancy.** Every query that returns company-specific data must filter by `company_id`. Never omit this filter.

7. **Role checks.** Before adding any admin feature, verify which roles should access it using the role hierarchy: `super_admin > admin1 > admin2 > user`.

8. **No test suite.** When making changes, manually verify the full CRUD flow: create an activity, create a collection with fields, create a record, edit it, delete it.

9. **French UI.** All UI labels, messages, and button text are in French. Keep this consistent.

10. **Avoid breaking address auto-fill.** The `address_buffer` variable (line 221) and the `Adresse Travaux` copy logic (lines 242–252) are fragile. Any refactor of the field rendering loop must preserve the sequential capture of `address_buffer` before it is consumed by `Adresse Travaux` fields.
