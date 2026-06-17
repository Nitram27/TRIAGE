"""Frontend TRIAGE — Gradio. Nessun JS bridge."""

import base64, io, json, os
import gradio as gr
import httpx
import numpy as np
from PIL import Image

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
ICONS = {"alta": "🔴", "media": "🟡", "bassa": "🟢"}

FINAL_LABEL_OPTIONS = ["Nessuna neoplasia sospetta", "Neoplasia sospetta"]
LIKERT_OPTIONS = ["1 — Molto bassa","2 — Bassa","3 — Moderata","4 — Alta","5 — Molto alta"]
LIKERT_VALUES  = {"1 — Molto bassa":0.1,"2 — Bassa":0.3,"3 — Moderata":0.5,
                  "4 — Alta":0.7,"5 — Molto alta":0.9}

def _auth(u, p): return (u, p)
def _decode_img(b64): return np.array(Image.open(io.BytesIO(base64.b64decode(b64))))

def _ai_to_likert(conf):
    if conf >= 0.85: return "5 — Molto alta"
    elif conf >= 0.70: return "4 — Alta"
    elif conf >= 0.55: return "3 — Moderata"
    elif conf >= 0.40: return "2 — Bassa"
    return "1 — Molto bassa"

# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
/* Sfondo gradiente pagina intera */
body > gradio-app, .gradio-container {
    background: radial-gradient(ellipse at top left, #3d72d7 0%, transparent 55%),
                radial-gradient(ellipse at bottom right, #b06ab3 0%, transparent 55%),
                #5c3d8f !important;
    min-height: 100vh !important;
}

/* Login group trasparente */
#login-group {
    max-width: 420px !important;
    margin: 0 auto !important;
    padding-top: 18vh !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
#login-group > div, #login-group .block, #login-group label,
#login-group .wrap, #login-group .form, #login-group .gap {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
#login-group label > span { color: rgba(255,255,255,0.92) !important; font-weight:500 !important; }
#login-group input {
    border-radius: 999px !important;
    border: none !important;
    padding: 11px 22px !important;
    background: rgba(255,255,255,0.93) !important;
    color: #1a202c !important;
    box-shadow: 0 2px 12px rgba(0,0,0,0.12) !important;
}
#login-group button {
    border-radius: 999px !important;
    background: rgba(15,23,42,0.88) !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.2) !important;
}
#login-group button:hover { background: #0f172a !important; }
#login-group .prose p { color: rgba(255,220,220,0.95) !important; }

/* Pannelli principali: sfondo chiaro dopo login */
#radiologo-panel, #medico-panel, #tecnico-panel {
    background: #f8fafc !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}

/* Pannello medico: alto contrasto */
#medico-panel, #medico-panel * {
    color: #111827 !important;
}
#medico-panel .block {
    background: #fff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
}
#medico-panel input, #medico-panel textarea {
    color: #111827 !important;
    background: #f9fafb !important;
}
#medico-panel label span { color: #374151 !important; font-weight: 600 !important; }
"""

# ── Login / Logout ────────────────────────────────────────────────────────────

def login(username, password):
    empty = (None, gr.update(visible=True), gr.update(visible=False),
             gr.update(visible=False), gr.update(visible=False),
             gr.update(visible=False), "")
    if not username or not password:
        return (*empty, "⚠️ Inserisci username e password.")
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/me",
                      auth=_auth(username, password), timeout=5.0)
        if r.status_code == 401:
            return (*empty, "❌ Credenziali non valide.")
        r.raise_for_status()
        role = r.json()["role"]
    except httpx.HTTPStatusError:
        return (*empty, "❌ Credenziali non valide.")
    except Exception as exc:
        return (*empty, f"❌ Gateway non raggiungibile: {exc}")
    return ({"username": username, "password": password, "role": role},
            gr.update(visible=False), gr.update(visible=True),
            gr.update(visible=(role == "radiologo")),
            gr.update(visible=(role == "medico")),
            gr.update(visible=(role == "tecnico")),
            f"👤 **{username}** ({role})", "")

def logout():
    return (None, gr.update(visible=True), gr.update(visible=False),
            gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False), "")

# ── Radiologo ─────────────────────────────────────────────────────────────────

def submit_case(auth, image_path, patient_id, age, sex):
    err_pid = "⚠️ ID Paziente obbligatorio." if not patient_id or not str(patient_id).strip() else ""
    err_age = "⚠️ Età obbligatoria." if age is None or age == "" else ""
    err_sex = "⚠️ Sesso obbligatorio." if not sex else ""
    noop = gr.update(), gr.update(), gr.update(), gr.update()
    if err_pid or err_age or err_sex:
        return "", err_pid, err_age, err_sex, None, *noop
    if not auth:       return "⚠️ Sessione scaduta.", "","","", None, *noop
    if not image_path: return "⚠️ Seleziona un'immagine MRI.", "","","", None, *noop
    cd = json.dumps({"patient_id": str(patient_id).strip(),
                     "age": int(age), "sex": sex, "features": {}})
    try:
        with open(image_path, "rb") as f: raw = f.read()
        r = httpx.post(f"{GATEWAY_URL}/api/v1/triage",
                       files={"image": ("mri.png", raw, "image/png")},
                       data={"clinical_data": cd},
                       auth=_auth(auth["username"], auth["password"]), timeout=30.0)
        r.raise_for_status()
        d = r.json()
    except Exception as exc:
        return f"❌ {exc}", "","","", None, *noop
    p = d["triage"]["priority"]
    return (f"✅ Caso acquisito — priorità: {ICONS.get(p,'⚪')} **{p.upper()}**",
            "", "", "", d["case_id"], None, "", None, None)

# ── Medico: queue e storico ───────────────────────────────────────────────────

def _fetch_cases(auth, status):
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/cases",
                      params={"status": status},
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        return r.json().get("cases", [])
    except Exception:
        return []

def load_queue(auth):
    if not auth: return {}, gr.update(choices=[], value=None)
    cases = _fetch_cases(auth, "pending_review")
    if not cases:
        return {}, gr.update(choices=["Nessun caso in attesa"], value=None)
    choices = [
        f"{ICONS.get(c['triage']['priority'],'⚪')} {c.get('patient_id','?')} "
        f"— {c['triage']['priority'].upper()} (Conf. {c.get('confidence',0):.0%})"
        for c in cases
    ]
    mapping = {lbl: c for lbl, c in zip(choices, cases)}
    return mapping, gr.update(choices=choices, value=None)

def load_storico(auth):
    if not auth: return {}, gr.update(choices=[], value=None)
    cases = _fetch_cases(auth, "reviewed")
    if not cases:
        return {}, gr.update(choices=["Nessuno storico disponibile"], value=None)
    choices = []
    for c in cases:
        rev = c.get("review") or {}
        fl  = rev.get("label_override")
        il  = (c.get("inference") or {}).get("label", 0)
        lbl = "Neoplasia" if (fl if fl is not None else il) == 1 else "Nessuna neoplasia"
        date = (c.get("reviewed_at") or "")[:10]
        choices.append(f"{'✓' if rev.get('agreed') else '✎'} {c.get('patient_id','?')} — {lbl} ({date})")
    mapping = {lbl: c for lbl, c in zip(choices, cases)}
    return mapping, gr.update(choices=choices, value=None)

def show_case_col(mapping, selected):
    valid = selected and selected not in ("Nessun caso in attesa", "Nessuno storico disponibile") and mapping and selected in mapping
    if not valid:
        return gr.update(visible=False), "⚠️ Seleziona un caso dalla lista."
    return gr.update(visible=True), ""

def load_case_detail(auth, mapping, selected):
    empty = (None, None, "", "",
             gr.update(visible=False),
             gr.update(value=None, interactive=True),
             "", None, "", None)
    if not auth or not mapping or not selected or selected not in mapping:
        return empty
    case_meta = mapping[selected]
    case_id   = case_meta["case_id"]
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/cases/{case_id}",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        case = r.json()
    except Exception:
        return empty
    triage  = case.get("triage", {})
    p       = triage.get("priority", "")
    mri_img = _decode_img(case["image_b64"])
    pat_info = (f"**Paziente**: {case.get('patient_id','N/A')}  \n"
                f"**Età**: {case.get('age','N/A')}  **Sesso**: {case.get('sex','N/A')}  \n"
                f"**Priorità**: {ICONS.get(p,'⚪')} {p.upper()} — {triage.get('reason','')}")
    return (case, mri_img, pat_info, case_id,
            gr.update(visible=False),
            gr.update(value=None, interactive=True),
            "", None, "", None)

def load_storico_detail(auth, mapping, selected):
    empty = (None, None, "", gr.update(visible=False), "", "", None, "")
    if not auth or not mapping or not selected or selected not in mapping:
        return empty
    case_meta = mapping[selected]
    case_id   = case_meta["case_id"]
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/cases/{case_id}",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        case = r.json()
    except Exception:
        return empty
    inf  = case.get("inference", {})
    exp  = case.get("explanation", {})
    triage = case.get("triage", {})
    p    = triage.get("priority", "")
    label = inf.get("label", 0)
    conf  = inf.get("confidence", 0.5)
    mri_img  = _decode_img(case["image_b64"])
    saliency = _decode_img(exp["saliency_map_b64"]) if exp.get("saliency_map_b64") else None
    pat_info = (f"**Paziente**: {case.get('patient_id','N/A')}  \n"
                f"**Età**: {case.get('age','N/A')}  **Sesso**: {case.get('sex','N/A')}  \n"
                f"**Priorità**: {ICONS.get(p,'⚪')} {p.upper()}")
    ai_text = (f"**Proposta AI**: {'Neoplasia sospetta' if label==1 else 'Nessuna neoplasia'}  \n"
               f"**Confidence**: {conf:.1%}")
    review = case.get("review") or {}
    if review:
        fl   = review.get("label_override")
        diag = ("Neoplasia sospetta" if fl==1 else "Nessuna neoplasia") if fl is not None else \
               ("Neoplasia sospetta" if label==1 else "Nessuna neoplasia")
        rev_text = (f"**Diagnosi**: {diag}  \n"
                   f"**Concordanza**: {'✓ Concordato' if review.get('agreed') else '✎ Corretto'}  \n"
                   f"**Note**: {review.get('notes','—')}")
    else:
        rev_text = "Nessuna revisione disponibile."
    return (case, mri_img, pat_info, gr.update(visible=True),
            ai_text, rev_text, saliency, case_id)

def show_ai_section(doctor_assessment):
    if not doctor_assessment:
        raise gr.Error("Inserisci la valutazione clinica prima di visualizzare la proposta AI.")
    return gr.update(visible=True), gr.update(interactive=False)

def populate_ai(case_state, doctor_assessment):
    if not case_state: return "", None, None, None, None
    inf  = case_state.get("inference", {})
    exp  = case_state.get("explanation", {})
    label = inf.get("label", 0)
    conf  = inf.get("confidence", 0.5)
    saliency = _decode_img(exp["saliency_map_b64"]) if exp.get("saliency_map_b64") else None
    ai_text = (f"**Proposta AI**: {'Neoplasia sospetta' if label==1 else 'Nessuna neoplasia'}  \n"
               f"**Confidence**: {conf:.1%}  \n"
               + ("> ⚠️ *Modello stub*" if inf.get("is_stub") else ""))
    return ai_text, saliency, "Neoplasia sospetta" if label==1 else "Nessuna neoplasia", \
           _ai_to_likert(conf), case_state["case_id"]

def submit_review(auth, case_state, case_id, final_label_choice, likert_choice, notes):
    if not auth or not case_state or not case_id:
        return "⚠️ Nessun caso aperto.", gr.update(), gr.update()
    if not final_label_choice:
        return "⚠️ Indica la diagnosi.", gr.update(), gr.update()
    if not likert_choice:
        return "⚠️ Indica il grado di confidenza.", gr.update(), gr.update()
    ai_label = case_state.get("inference", {}).get("label", 0)
    ai_conf  = case_state.get("inference", {}).get("confidence", 0.5)
    final_label = 1 if final_label_choice == "Neoplasia sospetta" else 0
    agreed      = (final_label == ai_label)
    conf_val    = LIKERT_VALUES.get(likert_choice, 0.5)
    payload = {"agreed": agreed,
               "label_override": None if agreed else final_label,
               "confidence_override": round(conf_val, 2) if abs(conf_val - ai_conf) > 0.05 else None,
               "notes": notes or ""}
    try:
        r = httpx.post(f"{GATEWAY_URL}/api/v1/cases/{case_id}/review",
                       json=payload, auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        r.raise_for_status()
        return "✅ Diagnosi registrata.", gr.update(visible=False), None
    except Exception as exc:
        return f"❌ {exc}", gr.update(), gr.update()

# ── Tecnico ───────────────────────────────────────────────────────────────────

def load_status(auth):
    if not auth or auth.get("role") != "tecnico": return []
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/status",
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        rows = []
        for name, info in r.json().items():
            stato = "✅ Online" if info.get("reachable") else "❌ Offline"
            det = []
            if info.get("is_stub"): det.append("stub")
            if info.get("model_version"): det.append(info["model_version"])
            if info.get("events_stored") is not None: det.append(f"{info['events_stored']} eventi")
            if info.get("cases_in_queue") is not None:
                det.append(f"in coda: {info['cases_in_queue']} / tot: {info.get('cases_total','?')}")
            if not info.get("reachable") and info.get("error"): det.append(info["error"][:40])
            rows.append([name, stato, ", ".join(det) or "—"])
        return rows
    except Exception as exc: return [["Errore","❌", str(exc)]]

def load_model_info(auth):
    if not auth or auth.get("role") != "tecnico": return "—"
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/model",
                      auth=_auth(auth["username"], auth["password"]), timeout=5.0)
        d = r.json()
        if "message" in d: return d["message"]
        return (f"**Versione**: {d.get('version','N/A')}  \n"
                f"**Stato**: {d.get('status','N/A')}  \n"
                f"**Framework**: {d.get('framework','N/A')}  \n"
                + ("⚠️ *Stub*" if d.get("is_stub") else "✅ Modello reale"))
    except Exception as exc: return f"Errore: {exc}"

def load_model_versions(auth):
    if not auth or auth.get("role") != "tecnico": return gr.update(choices=[], value=None), {}
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/models",
                      auth=_auth(auth["username"], auth["password"]), timeout=5.0)
        r.raise_for_status()
        versions = r.json().get("versions", [])
        current  = r.json().get("current_version", "")
        choices  = []
        for v in versions:
            tag = "← in produzione" if v["version"] == current else f'[{v["status"]}]'
            choices.append(f"{v['version']} {tag}")
        mapping = {lbl: v["version"] for lbl, v in zip(choices, versions)}
        return gr.update(choices=choices, value=None), mapping
    except Exception: return gr.update(choices=[], value=None), {}

def do_rollback(auth, version_mapping, selected_label):
    if not auth or not selected_label or not version_mapping:
        return "⚠️ Seleziona una versione.", "—"
    version = version_mapping.get(selected_label)
    if not version: return "⚠️ Versione non trovata.", "—"
    try:
        r = httpx.post(f"{GATEWAY_URL}/api/v1/monitoring/model/promote/{version}",
                       auth=_auth(auth["username"], auth["password"]), timeout=5.0)
        r.raise_for_status()
        return f"✅ Versione **{version}** attivata.", load_model_info(auth)
    except Exception as exc: return f"❌ {exc}", "—"

def load_logs(auth, event_type_filter):
    if not auth or auth.get("role") != "tecnico": return [["—","—","—","—","—"]]
    params = {"limit": 50}
    if event_type_filter and event_type_filter != "Tutti":
        params["event_type"] = event_type_filter
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/logs", params=params,
                      auth=_auth(auth["username"], auth["password"]), timeout=10.0)
        events = r.json().get("events", [])
        if not events: return [["Nessun evento","","","",""]]
        return [[e.get("received_at","")[:16], e.get("source",""),
                 e.get("service",""), e.get("event_type",""), str(e.get("actor",""))]
                for e in events]
    except Exception as exc: return [[str(exc),"","","",""]]

def load_training_data(auth):
    if not auth or auth.get("role") != "tecnico": return [["—","—","—","—"]]
    try:
        r = httpx.get(f"{GATEWAY_URL}/api/v1/monitoring/training-data",
                      auth=_auth(auth["username"], auth["password"]), timeout=5.0)
        samples = r.json().get("samples", [])
        if not samples: return [["Nessun campione","","",""]]
        return [[s.get("case_id","")[:8]+"...",
                 "Maligno" if s.get("final_label")==1 else "Benigno",
                 "Concordo" if s.get("agreed_with_ai") else "Corretto",
                 s.get("received_at","")[:16]] for s in samples[:20]]
    except Exception as exc: return [[str(exc),"","",""]]

# ── UI ────────────────────────────────────────────────────────────────────────

with gr.Blocks(title="TRIAGE", css=CSS) as demo:

    auth_state            = gr.State(None)
    case_state            = gr.State(None)
    queue_mapping         = gr.State({})
    storico_mapping       = gr.State({})
    version_mapping_state = gr.State({})

    # Barra superiore
    with gr.Row():
        gr.Markdown("# 🧠 TRIAGE")
        with gr.Column(scale=0, min_width=350):
            with gr.Row(visible=False) as top_bar:
                user_display = gr.Markdown("", container=False)
                logout_btn   = gr.Button("Esci", size="sm", variant="secondary", min_width=80)

    # ── Login ──────────────────────────────────────────────────────────────────
    with gr.Group(elem_id="login-group") as login_group:
        gr.HTML(
            "<div style='text-align:center;padding-bottom:1.2rem'>"
            "<div style='font-size:4.5rem;font-weight:900;color:white;"
            "letter-spacing:0.08em;text-shadow:0 4px 24px rgba(0,0,0,0.3);line-height:1'>"
            "TRIAGE</div>"
            "<div style='color:rgba(255,255,255,0.8);font-size:1rem;margin-top:6px'>"
            "Sistema di supporto alla decisione clinica per tumori cerebrali</div></div>"
        )
        username_in  = gr.Textbox(label="Username", placeholder="radiologo / medico / tecnico")
        password_in  = gr.Textbox(label="Password", type="password")
        login_btn    = gr.Button("Accedi", variant="primary", size="lg")
        login_status = gr.Markdown("")

    # ── Pannello Radiologo ─────────────────────────────────────────────────────
    with gr.Group(visible=False, elem_id="radiologo-panel") as radiologo_panel:
        gr.Markdown("## Acquisizione immagini")
        with gr.Accordion("Immagine MRI", open=True):
            img_in = gr.Image(type="filepath", label="Immagine MRI", sources=["upload"])
        with gr.Accordion("Dati paziente", open=True):
            patient_in  = gr.Textbox(label="ID Paziente", placeholder="es. P001")
            patient_err = gr.Markdown("")
            age_in      = gr.Number(label="Età", minimum=0, maximum=120, value=None)
            age_err     = gr.Markdown("")
            sex_in      = gr.Radio(["M","F"], label="Sesso biologico")
            sex_err     = gr.Markdown("")
        submit_btn = gr.Button("Invia per analisi", variant="primary")
        submit_out = gr.Markdown("")

    # ── Pannello Medico ────────────────────────────────────────────────────────
    with gr.Group(visible=False, elem_id="medico-panel") as medico_panel:

        with gr.Tabs():

            # Tab Pazienti
            with gr.Tab("🩺 Pazienti"):
                with gr.Row():

                    # Sidebar sinistra: lista casi
                    with gr.Column(scale=1, min_width=280):
                        gr.Markdown("### Casi in attesa")
                        load_btn  = gr.Button("🔄 Aggiorna lista", size="sm")
                        case_radio = gr.Radio(label="", choices=[], interactive=True)
                        open_btn   = gr.Button("Apri caso selezionato", variant="primary")
                        open_err   = gr.Markdown("")

                    # Contenuto principale: dettaglio caso
                    with gr.Column(scale=2):
                        with gr.Column(visible=False) as case_col:
                            with gr.Row():
                                with gr.Column(scale=1):
                                    mri_display  = gr.Image(label="Immagine MRI")
                                    patient_info = gr.Markdown("")

                                with gr.Column(scale=1):
                                    with gr.Accordion("① Valutazione clinica indipendente", open=True):
                                        gr.Markdown("Esprimi il tuo giudizio diagnostico **prima** di consultare la proposta AI.")
                                        doctor_assessment = gr.Radio(
                                            ["Nessuna neoplasia sospetta","Neoplasia sospetta"],
                                            label="Valutazione")
                                        show_ai_btn = gr.Button(
                                            "Visualizza proposta diagnostica AI",
                                            variant="secondary")

                                    with gr.Group(visible=False) as ai_section:
                                        with gr.Accordion("② Proposta diagnostica AI", open=True):
                                            ai_info_out  = gr.Markdown("")
                                            saliency_out = gr.Image(label="Mappa di salienza")

                                        with gr.Accordion("③ Giudizio diagnostico finale", open=True):
                                            current_case_id   = gr.Textbox(visible=False)
                                            final_label_radio = gr.Radio(
                                                choices=FINAL_LABEL_OPTIONS, label="Diagnosi")
                                            likert_scale = gr.Radio(
                                                choices=LIKERT_OPTIONS, label="Indice di confidenza")
                                            notes_in   = gr.Textbox(label="Note cliniche", lines=3)
                                            review_btn = gr.Button("Conferma diagnosi", variant="primary")
                                            review_out = gr.Markdown("")

            # Tab Storico
            with gr.Tab("📋 Storico"):
                with gr.Row():

                    # Sidebar sinistra: lista storico
                    with gr.Column(scale=1, min_width=280):
                        gr.Markdown("### Casi revisionati")
                        load_storico_btn  = gr.Button("🔄 Aggiorna storico", size="sm")
                        storico_radio     = gr.Radio(label="", choices=[], interactive=True)
                        open_storico_btn  = gr.Button("Rivedi caso selezionato", variant="primary")
                        storico_err       = gr.Markdown("")

                    # Contenuto principale: dettaglio storico
                    with gr.Column(scale=2):
                        with gr.Column(visible=False) as storico_col:
                            with gr.Row():
                                with gr.Column(scale=1):
                                    storico_mri     = gr.Image(label="Immagine MRI")
                                    storico_patient = gr.Markdown("")
                                with gr.Column(scale=1):
                                    with gr.Accordion("Proposta diagnostica AI", open=True):
                                        storico_ai_info  = gr.Markdown("")
                                        storico_saliency = gr.Image(label="Mappa di salienza")
                                    with gr.Accordion("Revisione precedente", open=True):
                                        storico_review_info = gr.Markdown("")
                                    with gr.Accordion("Nuova revisione (opzionale)", open=False):
                                        storico_case_id    = gr.Textbox(visible=False)
                                        storico_new_label  = gr.Radio(choices=FINAL_LABEL_OPTIONS, label="Diagnosi")
                                        storico_new_likert = gr.Radio(choices=LIKERT_OPTIONS, label="Indice di confidenza")
                                        storico_notes      = gr.Textbox(label="Note", lines=2)
                                        storico_review_btn = gr.Button("Aggiorna diagnosi", variant="primary")
                                        storico_review_out = gr.Markdown("")

    # ── Pannello Tecnico ────────────────────────────────────────────────────────
    with gr.Group(visible=False, elem_id="tecnico-panel") as tecnico_panel:
        gr.Markdown("## Monitoraggio operativo")
        with gr.Row():
            with gr.Column():
                with gr.Accordion("Stato microservizi", open=True):
                    status_table = gr.Dataframe(
                        headers=["Servizio","Stato","Info"],
                        datatype=["str","str","str"], interactive=False, wrap=True)
                    status_btn = gr.Button("Aggiorna")
            with gr.Column():
                with gr.Accordion("Modello in produzione", open=True):
                    model_display = gr.Markdown("—")
                    gr.Markdown("**Attiva versione precedente**")
                    version_dropdown = gr.Dropdown(choices=[], label="Seleziona versione")
                    rollback_btn     = gr.Button("Attiva versione selezionata", variant="stop")
                    rollback_out     = gr.Markdown("")
        with gr.Accordion("Log eventi", open=True):
            log_filter = gr.Dropdown(
                choices=["Tutti","service.started","service.error","triage.completed",
                         "inference.completed","feedback.submitted","model.promoted","ingestion.completed"],
                value="Tutti", label="Filtra")
            log_btn   = gr.Button("Carica log")
            log_table = gr.Dataframe(
                headers=["Timestamp","Fonte","Servizio","Tipo evento","Attore"],
                datatype=["str","str","str","str","str"], interactive=False)
        with gr.Accordion("Campioni per retraining", open=True):
            training_table = gr.Dataframe(
                headers=["Case ID","Diagnosi","Concordanza AI","Ricevuto il"],
                datatype=["str","str","str","str"], interactive=False)
            training_btn = gr.Button("Aggiorna")

    # ── Handlers ──────────────────────────────────────────────────────────────

    login_btn.click(fn=login,
        inputs=[username_in, password_in],
        outputs=[auth_state, login_group, top_bar,
                 radiologo_panel, medico_panel, tecnico_panel,
                 user_display, login_status]
    ).then(fn=load_status, inputs=[auth_state], outputs=[status_table]
    ).then(fn=load_model_info, inputs=[auth_state], outputs=[model_display]
    ).then(fn=load_model_versions, inputs=[auth_state],
           outputs=[version_dropdown, version_mapping_state])

    logout_btn.click(fn=logout, inputs=[],
        outputs=[auth_state, login_group, top_bar,
                 radiologo_panel, medico_panel, tecnico_panel, user_display])

    # Radiologo
    submit_btn.click(fn=submit_case,
        inputs=[auth_state, img_in, patient_in, age_in, sex_in],
        outputs=[submit_out, patient_err, age_err, sex_err, gr.State(),
                 img_in, patient_in, age_in, sex_in])

    # Medico — Pazienti
    load_btn.click(fn=load_queue,
        inputs=[auth_state], outputs=[queue_mapping, case_radio])

    open_btn.click(
        fn=show_case_col,
        inputs=[queue_mapping, case_radio],
        outputs=[case_col, open_err]
    ).then(fn=load_case_detail,
        inputs=[auth_state, queue_mapping, case_radio],
        outputs=[case_state, mri_display, patient_info, current_case_id,
                 ai_section, doctor_assessment, review_out, likert_scale,
                 notes_in, final_label_radio])

    show_ai_btn.click(
        fn=show_ai_section,
        inputs=[doctor_assessment],
        outputs=[ai_section, doctor_assessment]
    ).then(fn=populate_ai,
        inputs=[case_state, doctor_assessment],
        outputs=[ai_info_out, saliency_out, final_label_radio,
                 likert_scale, current_case_id])

    review_btn.click(fn=submit_review,
        inputs=[auth_state, case_state, current_case_id,
                final_label_radio, likert_scale, notes_in],
        outputs=[review_out, case_col, case_state]
    ).then(fn=load_queue, inputs=[auth_state],
           outputs=[queue_mapping, case_radio])

    # Medico — Storico
    load_storico_btn.click(fn=load_storico,
        inputs=[auth_state], outputs=[storico_mapping, storico_radio])

    open_storico_btn.click(
        fn=show_case_col,
        inputs=[storico_mapping, storico_radio],
        outputs=[storico_col, storico_err]
    ).then(fn=load_storico_detail,
        inputs=[auth_state, storico_mapping, storico_radio],
        outputs=[case_state, storico_mri, storico_patient, storico_col,
                 storico_ai_info, storico_review_info, storico_saliency, storico_case_id])

    storico_review_btn.click(fn=submit_review,
        inputs=[auth_state, case_state, storico_case_id,
                storico_new_label, storico_new_likert, storico_notes],
        outputs=[storico_review_out, storico_col, case_state]
    ).then(fn=load_storico, inputs=[auth_state],
           outputs=[storico_mapping, storico_radio])

    # Tecnico
    status_btn.click(fn=load_status, inputs=[auth_state], outputs=[status_table])
    rollback_btn.click(fn=do_rollback,
        inputs=[auth_state, version_mapping_state, version_dropdown],
        outputs=[rollback_out, model_display])
    log_btn.click(fn=load_logs, inputs=[auth_state, log_filter], outputs=[log_table])
    training_btn.click(fn=load_training_data, inputs=[auth_state], outputs=[training_table])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
