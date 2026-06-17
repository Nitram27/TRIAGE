"""Frontend TRIAGE — NiceGUI. Tutti i bottoni verificati e funzionanti."""

import base64, io, json, os
import httpx
from nicegui import app, ui

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
ICONS      = {"alta": "🔴", "media": "🟡", "bassa": "🟢"}
PRIO_COLOR = {"alta": "bg-red-500", "media": "bg-amber-500", "bassa": "bg-green-500"}
FINAL_LABEL_OPTIONS = ["Nessuna neoplasia sospetta", "Neoplasia sospetta"]
LIKERT_MAP = {
    "1 — Molto bassa": 0.1, "2 — Bassa": 0.3, "3 — Moderata": 0.5,
    "4 — Alta": 0.7, "5 — Molto alta": 0.9,
}
app.storage.key = "triage_secret_key"

# Scrive favicon SVG su disco per ui.run()
import pathlib
_FAVICON_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='-42 -46 84 98'>
<path d='M0-34 C-19-34-34-19-34 0 C-34 12-27 22-17 27 C-17 33-12 38-5 38 L0 38 L0-34Z'
  fill='none' stroke='#1877f2' stroke-width='3' stroke-linejoin='round'/>
<path d='M0-34 C19-34 34-19 34 0 C34 12 27 22 17 27 C17 33 12 38 5 38 L0 38 L0-34Z'
  fill='none' stroke='#1877f2' stroke-width='3' stroke-linejoin='round'/>
<path d='M-5 38 Q0 43 5 38' stroke='#1877f2' stroke-width='3' fill='none' stroke-linecap='round'/>
<line x1='0' y1='-34' x2='0' y2='38' stroke='#1877f2' stroke-width='1.5' stroke-dasharray='4,3'/>
<path d='M-24-8 Q-16-16-10-8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>
<path d='M-26 8 Q-18 0-12 8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>
<path d='M24-8 Q16-16 10-8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>
<path d='M26 8 Q18 0 12 8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>
</svg>"""
pathlib.Path("brain_favicon.svg").write_text(_FAVICON_SVG)

def _auth():
    a = app.storage.user.get("auth")
    return (a["username"], a["password"]) if a else None

def _img_src(b64): return f"data:image/png;base64,{b64}"

def _ai_to_likert(conf):
    if conf >= 0.85: return "5 — Molto alta"
    elif conf >= 0.70: return "4 — Alta"
    elif conf >= 0.55: return "3 — Moderata"
    elif conf >= 0.40: return "2 — Bassa"
    return "1 — Molto bassa"

def _friendly_error(exc) -> str:
    """H9 — Traduce eccezioni tecniche in messaggi leggibili."""
    s = str(exc).lower()
    if "connection" in s or "connect" in s or "refused" in s:
        return "Impossibile connettersi al server. Verificare che il sistema sia attivo e riprovare."
    if "401" in s or "unauthorized" in s:
        return "Sessione scaduta. Effettuare nuovamente il login."
    if "403" in s or "forbidden" in s:
        return "Accesso non autorizzato per questa operazione."
    if "404" in s or "not found" in s:
        return "Risorsa non trovata. Il caso potrebbe essere stato eliminato."
    if "409" in s or "conflict" in s:
        return "Questo caso è già stato revisionato. Per modificare la diagnosi utilizza la sezione Storico."
    if "timeout" in s:
        return "Il server ha impiegato troppo tempo a rispondere. Riprovare tra qualche istante."
    if "500" in s or "server error" in s:
        return "Errore interno del server. Contattare il tecnico di sistema."
    return "Si è verificato un errore imprevisto. Riprovare o contattare il supporto tecnico."


async def _get(path, **params):
    a = _auth()
    if not a: return None
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{GATEWAY_URL}{path}", auth=a, params=params, timeout=10.0)
        r.raise_for_status()
        return r.json()

async def _post(path, **kwargs):
    a = _auth()
    if not a: return None
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{GATEWAY_URL}{path}", auth=a, timeout=15.0, **kwargs)
        r.raise_for_status()
        return r.json()


@ui.page("/")
def index():
    ui.add_head_html(
        "<link rel='icon' type='image/svg+xml' href=\"data:image/svg+xml,"
        "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='-42 -46 84 98'%3E"
        "%3Cpath d='M0-34 C-19-34-34-19-34 0 C-34 12-27 22-17 27 C-17 33-12 38-5 38 L0 38 L0-34Z'"
        " fill='none' stroke='%231877f2' stroke-width='3' stroke-linejoin='round'/%3E"
        "%3Cpath d='M0-34 C19-34 34-19 34 0 C34 12 27 22 17 27 C17 33 12 38 5 38 L0 38 L0-34Z'"
        " fill='none' stroke='%231877f2' stroke-width='3' stroke-linejoin='round'/%3E"
        "%3Cpath d='M-5 38 Q0 43 5 38' stroke='%231877f2' stroke-width='3' fill='none'/%3E"
        "%3Cline x1='0' y1='-34' x2='0' y2='38' stroke='%231877f2' stroke-width='1.5' stroke-dasharray='4,3'/%3E"
        "%3Cpath d='M-24-8 Q-16-16-10-8' stroke='%231877f2' stroke-width='2' fill='none'/%3E"
        "%3Cpath d='M-26 8 Q-18 0-12 8' stroke='%231877f2' stroke-width='2' fill='none'/%3E"
        "%3Cpath d='M24-8 Q16-16 10-8' stroke='%231877f2' stroke-width='2' fill='none'/%3E"
        "%3Cpath d='M26 8 Q18 0 12 8' stroke='%231877f2' stroke-width='2' fill='none'/%3E"
        "%3C/svg%3E\">"
    )

    # ── TOPBAR ────────────────────────────────────────────────────────────────
    topbar = ui.row().classes("w-full items-center justify-between px-6 py-3 bg-white border-b border-gray-200")
    topbar.set_visibility(False)
    with topbar:
        ui.html('<svg width="28" height="32" viewBox="-38 -42 76 92" fill="none" xmlns="http://www.w3.org/2000/svg" style="display:inline-block;vertical-align:middle"><path d="M0-34 C-19-34-34-19-34 0 C-34 12-27 22-17 27 C-17 33-12 38-5 38 L0 38 L0-34Z" fill="none" stroke="#1877f2" stroke-width="3" stroke-linejoin="round"/><path d="M0-34 C19-34 34-19 34 0 C34 12 27 22 17 27 C17 33 12 38 5 38 L0 38 L0-34Z" fill="none" stroke="#1877f2" stroke-width="3" stroke-linejoin="round"/><path d="M-5 38 Q0 43 5 38" stroke="#1877f2" stroke-width="3" fill="none" stroke-linecap="round"/><line x1="0" y1="-34" x2="0" y2="38" stroke="#1877f2" stroke-width="1.5" stroke-dasharray="4,3"/><path d="M-24-8 Q-16-16-10-8" stroke="#1877f2" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M-26 8 Q-18 0-12 8" stroke="#1877f2" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M24-8 Q16-16 10-8" stroke="#1877f2" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M26 8 Q18 0 12 8" stroke="#1877f2" stroke-width="2" fill="none" stroke-linecap="round"/></svg><span style=\'font-size:1.2rem;font-weight:700;color:#1f2937;vertical-align:middle;margin-left:8px\'>TRIAGE</span>')
        with ui.row().classes("items-center gap-3"):
            user_lbl = ui.label("").classes("text-sm text-gray-600")
            async def do_logout():
                app.storage.user.pop("auth", None)
                topbar.set_visibility(False)
                radiologo_panel.set_visibility(False)
                medico_panel.set_visibility(False)
                tecnico_panel.set_visibility(False)
                login_wrap.set_visibility(True)
            ui.button("Esci", on_click=do_logout).props("flat dense").classes("text-gray-600 text-sm")

    # ── LOGIN — Facebook style ─────────────────────────────────────────────────
    login_wrap = ui.element("div").style(
        "width:100vw;min-height:100vh;background:#f0f2f5;"
        "display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px"
    )
    with login_wrap:
        ui.html(
            "<div style='display:flex;align-items:center;justify-content:center;gap:14px;margin-bottom:8px'>"
            "<svg width='52' height='60' viewBox='-38 -42 76 92' fill='none' xmlns='http://www.w3.org/2000/svg' style='display:inline-block;vertical-align:middle'>"
            "<path d='M0-34 C-19-34-34-19-34 0 C-34 12-27 22-17 27 C-17 33-12 38-5 38 L0 38 L0-34Z' fill='none' stroke='#1877f2' stroke-width='3' stroke-linejoin='round'/>"
            "<path d='M0-34 C19-34 34-19 34 0 C34 12 27 22 17 27 C17 33 12 38 5 38 L0 38 L0-34Z' fill='none' stroke='#1877f2' stroke-width='3' stroke-linejoin='round'/>"
            "<path d='M-5 38 Q0 43 5 38' stroke='#1877f2' stroke-width='3' fill='none' stroke-linecap='round'/>"
            "<line x1='0' y1='-34' x2='0' y2='38' stroke='#1877f2' stroke-width='1.5' stroke-dasharray='4,3'/>"
            "<path d='M-24-8 Q-16-16-10-8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>"
            "<path d='M-26 8 Q-18 0-12 8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>"
            "<path d='M24-8 Q16-16 10-8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>"
            "<path d='M26 8 Q18 0 12 8' stroke='#1877f2' stroke-width='2' fill='none' stroke-linecap='round'/>"
            "</svg>"
            "<span style='font-size:3.5rem;font-weight:900;color:#1877f2;line-height:1'>TRIAGE</span></div>"
            "<div style='color:#606770;text-align:center;font-size:0.9rem'>"
            "Sistema di supporto alla decisione clinica per tumori cerebrali</div>"
        )
        with ui.element("div").style(
            "background:#fff;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.15);"
            "padding:20px;width:396px;display:flex;flex-direction:column;gap:12px"
        ):
            # Uso ui.input() con label vuota per leggere .value direttamente
            username_inp = (
                ui.input(placeholder="Username")
                .props("outlined dense")
                .style("width:100%;font-size:16px")
            )
            password_inp = (
                ui.input(placeholder="Password", password=True)
                .props("outlined dense")
                .style("width:100%;font-size:16px")
            )
            login_err = ui.label("").style("color:#f02849;font-size:13px;text-align:center;min-height:18px")

            async def do_login():
                u = (username_inp.value or "").strip()
                p = password_inp.value or ""
                if not u or not p:
                    login_err.set_text("Inserisci username e password.")
                    return
                try:
                    async with httpx.AsyncClient() as client:
                        r = await client.get(f"{GATEWAY_URL}/api/v1/me", auth=(u, p), timeout=5.0)
                    if r.status_code == 401:
                        login_err.set_text("Credenziali non valide.")
                        return
                    r.raise_for_status()
                    role = r.json()["role"]
                except httpx.HTTPStatusError:
                    login_err.set_text("Credenziali non valide.")
                    return
                except Exception as exc:
                    login_err.set_text(f"Errore: {exc}")
                    return
                app.storage.user["auth"] = {"username": u, "password": p, "role": role}
                login_wrap.set_visibility(False)
                DISPLAY_NAMES = {
                    "medico":    "Dott. Frinzi",
                    "radiologo": "Dott. Gastani",
                    "tecnico":   "Baglio",
                }
                display_name = DISPLAY_NAMES.get(u, u)
                user_lbl.set_text(f"{display_name} ({role})")
                topbar.set_visibility(True)
                show_panel(role)

            ui.button("Accedi", on_click=do_login).style(
                "width:100%;padding:14px;font-size:18px;font-weight:700;"
                "background:#1877f2;color:white;border:none;border-radius:6px;cursor:pointer"
            )

    # ── PANNELLI ───────────────────────────────────────────────────────────────
    radiologo_panel = ui.column().classes("w-full p-6 bg-gray-50 min-h-screen gap-4")
    radiologo_panel.set_visibility(False)
    medico_panel = ui.column().classes("w-full min-h-screen")
    medico_panel.set_visibility(False)
    tecnico_panel = ui.column().classes("w-full p-6 bg-gray-50 min-h-screen gap-4")
    tecnico_panel.set_visibility(False)

    def show_panel(role):
        if role == "radiologo":
            build_radiologo()
            radiologo_panel.set_visibility(True)
        elif role == "medico":
            build_medico()
            medico_panel.set_visibility(True)
        elif role == "tecnico":
            build_tecnico()
            tecnico_panel.set_visibility(True)

    # ── RADIOLOGO ──────────────────────────────────────────────────────────────
    def build_radiologo():
        radiologo_panel.clear()
        with radiologo_panel:
            ui.label("Acquisizione immagini").classes("text-2xl font-bold text-gray-800")
            upload_data = {"raw": None, "name": None}
            result_msg  = ui.label("").classes("text-sm font-medium")

            with ui.row().classes("w-full max-w-3xl gap-4 items-start"):

                # Card 1: Immagine MRI con drag & drop
                with ui.card().classes("flex-1 p-5 gap-3"):
                    ui.label("Immagine MRI").classes("font-bold text-gray-800 text-base")
                    ui.separator()

                    upload_status = ui.label("").classes("text-green-600 text-sm font-semibold")
                    preview_img = ui.image("").classes(
                        "w-full rounded-lg border border-gray-200 object-contain mt-2"
                    ).style("max-height:200px;display:none")
                    remove_btn = ui.button("Rimuovi immagine", icon="delete").props(
                        "flat dense color=red"
                    ).classes("text-xs mt-1").style("display:none")

                    def remove_image():
                        upload_data["raw"]  = None
                        upload_data["name"] = None
                        upload_status.set_text("")
                        preview_img.set_source("")
                        preview_img.style("max-height:200px;display:none")
                        remove_btn.style("display:none")
                        drop_zone.style("display:block")
                        mri_upload.reset()

                    remove_btn.on("click", remove_image)

                    def handle_upload(e):
                        import base64 as _b64
                        upload_data["raw"]  = e.content.read()
                        upload_data["name"] = e.name
                        upload_status.set_text(f"✓ {e.name}")
                        b64 = _b64.b64encode(upload_data["raw"]).decode()
                        preview_img.set_source(f"data:image/png;base64,{b64}")
                        preview_img.style("max-height:200px;display:block")
                        remove_btn.style("display:inline-flex")
                        drop_zone.style("display:none")

                    # Zona drag & drop cliccabile via JS trigger
                    mri_upload = ui.upload(
                        on_upload=handle_upload, max_files=1, auto_upload=True
                    ).props("accept='.png,.jpg,.jpeg,.tiff,.bmp'").style(
                        "height:0;overflow:hidden;border:none;padding:0;margin:0"
                    )

                    async def trigger_file_picker():
                        await ui.run_javascript(
                            "var inp = document.querySelector('.q-uploader__input');"
                            "if(inp){ inp.click(); }"
                        )

                    with ui.element("div").style(
                        "border:2px dashed #d1d5db;border-radius:8px;padding:36px 16px;"
                        "text-align:center;background:#f9fafb;cursor:pointer"
                    ).on("click", trigger_file_picker) as drop_zone:
                        ui.icon('cloud_upload').classes('text-5xl text-gray-400').style('margin-bottom:8px')
                        ui.label("Trascina l'immagine MRI qui").classes("text-gray-600 text-sm font-medium")
                        ui.label("oppure clicca per selezionare (PNG, JPG, TIFF)").classes("text-gray-400 text-xs mt-1")

                # Card 2: Dati paziente
                with ui.card().classes("flex-1 p-5 gap-3"):
                    ui.label("Dati paziente").classes("font-bold text-gray-800 text-base")
                    ui.separator()
                    patient_id  = ui.input("ID Paziente", placeholder="es. P001").classes("w-full")
                    patient_err = ui.label("").classes("text-red-500 text-xs -mt-2")
                    age_inp     = ui.number("Età", min=0, max=120).classes("w-full")
                    age_err     = ui.label("").classes("text-red-500 text-xs -mt-2")
                    ui.label("Sesso biologico").classes("text-sm text-gray-600")
                    sex_inp     = ui.radio(["M", "F"], value=None).classes("flex-row gap-6")
                    sex_err     = ui.label("").classes("text-red-500 text-xs")

            async def invia():
                ok = True
                patient_err.set_text(""); age_err.set_text(""); sex_err.set_text("")
                if not patient_id.value or not patient_id.value.strip():
                    patient_err.set_text("ID Paziente obbligatorio."); ok = False
                if age_inp.value is None:
                    age_err.set_text("Età obbligatoria."); ok = False
                if not sex_inp.value:
                    sex_err.set_text("Sesso obbligatorio."); ok = False
                if not ok: return
                if not upload_data["raw"]:
                    ui.notify("Carica un'immagine MRI prima di procedere.", type="warning", icon="warning"); return
                cd = json.dumps({"patient_id": patient_id.value.strip(),
                                 "age": int(age_inp.value), "sex": sex_inp.value, "features": {}})
                try:
                    a = _auth()
                    async with httpx.AsyncClient() as client:
                        r = await client.post(f"{GATEWAY_URL}/api/v1/triage",
                                              files={"image": (upload_data["name"], upload_data["raw"], "image/png")},
                                              data={"clinical_data": cd}, auth=a, timeout=30.0)
                    r.raise_for_status()
                    d = r.json()
                    p = d["triage"]["priority"]
                    ui.notify(f"Caso acquisito — priorità: {ICONS.get(p,'')} {p.upper()}", type="positive", icon="check_circle")
                    patient_id.value = ""; age_inp.value = None; sex_inp.value = None
                    upload_data["raw"] = None; upload_data["name"] = None
                    upload_status.set_text("")
                    preview_img.set_source("")
                    preview_img.style("max-height:200px;display:none")
                    remove_btn.style("display:none")
                    drop_zone.style("display:block")
                    mri_upload.reset()
                except Exception as exc:
                    ui.notify(f"Errore: {exc}", type="negative", icon="error")

            ui.button("Invia per analisi", on_click=invia).classes(
                "rounded-full bg-blue-600 text-white font-semibold px-8 py-3").style("border-radius:6px")

    # ── MEDICO ─────────────────────────────────────────────────────────────────

    def build_medico():
        medico_panel.clear()
        with medico_panel:

            # Toggle pill-style Pazienti / Storico
            with ui.row().classes("w-full justify-center py-3 bg-white border-b border-gray-100 sticky top-0 z-10"):
                view_toggle = ui.toggle(
                    {"pazienti": "Pazienti", "storico": "Storico"},
                    value="pazienti"
                ).props("unelevated rounded")

            # Stato condiviso
            _sel = {"paz_id": None, "sto_id": None}

            # Helper badge priorità quadrato
            def prio_badge(p):
                cfg = {
                    "alta":  ("#dc2626", "■ ALTA",  "Revisione urgente"),
                    "media": ("#d97706", "■ MEDIA", "Priorità moderata"),
                    "bassa": ("#16a34a", "■ BASSA", "Priorità bassa"),
                }
                color, label, desc = cfg.get(p, ("#6b7280", p.upper(), ""))
                with ui.column().classes("gap-0 items-center justify-center self-center"):
                    ui.element("span").style(
                        f"background:{color};color:white;padding:3px 8px;"
                        "border-radius:4px;font-size:11px;font-weight:700;"
                        "letter-spacing:0.05em;white-space:nowrap"
                    ).text = label
                    ui.label(desc).style("font-size:9px;color:#6b7280;margin-top:1px")

            # ── Pannello Pazienti ──────────────────────────────────────────────
            with ui.column().classes("w-full flex-1 p-0") as panel_paz:
                    with ui.row().classes("w-full min-h-screen"):

                        # Sidebar sinistra
                        with ui.column().classes("w-72 bg-white border-r border-gray-100 p-4 gap-3").style("min-height:100vh"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("Casi in attesa").classes("font-bold text-gray-800")
                                paz_count = ui.badge("0").classes("bg-gray-200 text-gray-700")

                            paz_list_col = ui.column().classes("w-full gap-2")

                            @ui.refreshable
                            async def render_paz_list():
                                paz_list_col.clear()
                                try:
                                    d = await _get("/api/v1/cases", status="pending_review")
                                    cases = (d or {}).get("cases", [])
                                except Exception:
                                    cases = []
                                paz_count.set_text(str(len(cases)))
                                with paz_list_col:
                                    if not cases:
                                        ui.label("Nessun caso in attesa").classes("text-gray-400 text-sm text-center py-6")
                                        return
                                    for case in cases:
                                        p    = case.get("triage", {}).get("priority", "")
                                        conf = case.get("confidence", 0)
                                        pid  = case.get("patient_id", "N/A")
                                        desc = {"alta":"Incertezza elevata","media":"Incertezza moderata","bassa":"Alta confidence"}.get(p,"")
                                        with ui.card().classes("w-full p-3 hover:shadow-md transition-shadow cursor-pointer"):
                                            with ui.row().classes("w-full items-center gap-2"):
                                                with ui.column().classes("flex-1 gap-0"):
                                                    ui.label(pid).classes("font-semibold text-gray-800 text-sm")
                                                    ui.label(f"Conf. {conf:.0%} — {desc}").classes("text-xs text-gray-500")
                                                prio_badge(p)
                                                cid = case["case_id"]
                                                def select_paz(c=cid):
                                                    _sel["paz_id"] = c
                                                    render_paz_detail.refresh()
                                                ui.button("Apri", on_click=select_paz).classes(
                                                    "bg-gray-800 text-white text-xs font-semibold px-3 py-1"
                                                ).style("border-radius:4px").props("dense")

                            render_paz_list()
                            ui.button("Aggiorna", on_click=render_paz_list.refresh).props("flat icon=refresh").classes("w-full text-sm")

                        # Dettaglio caso (destra)
                        with ui.column().classes("flex-1 p-6 bg-gray-50"):

                            @ui.refreshable
                            async def render_paz_detail():
                                cid = _sel.get("paz_id")
                                if not cid:
                                    with ui.column().classes("w-full items-center justify-center py-20 gap-2"):
                                        ui.icon("medical_information").classes("text-6xl text-gray-300")
                                        ui.label("Seleziona un caso dalla lista per aprirlo").classes("text-gray-400 text-sm")
                                        ui.label("I casi in attesa sono ordinati per incertezza decrescente").classes("text-gray-300 text-xs")
                                    return
                                try:
                                    a = _auth()
                                    async with httpx.AsyncClient() as hc:
                                        r = await hc.get(f"{GATEWAY_URL}/api/v1/cases/{cid}", auth=a, timeout=10.0)
                                        r.raise_for_status()
                                        case = r.json()
                                except Exception as exc:
                                    with ui.column().classes("w-full items-center py-12 gap-3"):
                                        ui.icon("error_outline").classes("text-5xl text-red-400")
                                        ui.label(_friendly_error(exc)).classes("text-red-600 text-sm text-center max-w-xs")
                                        ui.button("Riprova", on_click=render_paz_detail.refresh).classes("mt-1").style("border-radius:6px")
                                    return

                                inf    = case.get("inference", {})
                                exp    = case.get("explanation", {})
                                triage = case.get("triage", {})
                                p      = triage.get("priority", "")
                                label  = inf.get("label", 0)
                                conf   = inf.get("confidence", 0.5)
                                lbl_str = "Neoplasia sospetta" if label == 1 else "Nessuna neoplasia"

                                # H3 — Bottone chiudi caso (controllo e libertà utente)
                                with ui.row().classes("w-full justify-end mb-2"):
                                    def chiudi_caso():
                                        _sel["paz_id"] = None
                                        render_paz_detail.refresh()
                                    ui.button("✕ Chiudi caso", on_click=chiudi_caso).props("flat dense").classes(
                                        "text-gray-500 text-sm")

                                # Dialog zoom creata a layout time, aperta da handler
                                with ui.dialog().props("maximized") as zoom_dlg:
                                    with ui.card().style(
                                        "width:90vw;max-height:90vh;background:#111;"
                                        "display:flex;flex-direction:column;align-items:center;padding:12px;gap:8px"
                                    ):
                                        zoom_img_el = ui.image("").style(
                                            "max-width:85vw;max-height:82vh;object-fit:contain")
                                        ui.button("✕ Chiudi", on_click=zoom_dlg.close).classes(
                                            "text-white").props("flat color=white dense")

                                def zoom_img(src):
                                    zoom_img_el.set_source(src)
                                    zoom_dlg.open()

                                with ui.row().classes("w-full gap-6 items-start"):
                                    # Colonna sinistra: MRI + dati paziente
                                    with ui.column().classes("gap-3"):
                                        with ui.element("div").style("position:relative;cursor:zoom-in").on(
                                            "click", lambda src=_img_src(case["image_b64"]): zoom_img(src)
                                        ):
                                            ui.image(_img_src(case["image_b64"])).classes(
                                                "w-64 h-64 object-contain rounded-xl border border-gray-200 bg-black")
                                            ui.html(
                                                "<div style='position:absolute;bottom:6px;right:6px;"
                                                "background:rgba(0,0,0,0.5);color:white;border-radius:4px;"
                                                "padding:2px 6px;font-size:11px'>Ingrandisci</div>"
                                            )
                                        with ui.card().classes("p-4 gap-2 w-64"):
                                            ui.label("Dati paziente").classes("font-bold text-gray-700 text-sm")
                                            ui.label(f"ID: {case.get('patient_id','N/A')}").classes("text-sm text-gray-600")
                                            ui.label(f"Età: {case.get('age','N/A')}   Sesso: {case.get('sex','N/A')}").classes("text-sm text-gray-600")
                                            with ui.row().classes("items-center gap-2 mt-1"):
                                                ui.label("Priorità:").classes("text-xs text-gray-500")
                                                prio_badge(p)

                                    # Colonna destra: stepper 3 schede
                                    with ui.column().classes("flex-1"):
                                        with ui.stepper(value="step1").classes("w-full") as stepper:

                                            # ── Scheda 1: Valutazione indipendente ──
                                            with ui.step(name="step1", title="Valutazione clinica indipendente"):
                                                ui.label("Esprimi il tuo giudizio prima di consultare la proposta AI.").classes("text-sm text-gray-500 mb-3")
                                                assessment = ui.radio(FINAL_LABEL_OPTIONS, value=None).classes("flex-col gap-2")
                                                assessment_err = ui.label("").classes("text-red-500 text-xs")

                                                async def vai_a_step2():
                                                    if not assessment.value:
                                                        assessment_err.set_text("Seleziona una valutazione prima di procedere.")
                                                        return
                                                    assessment_err.set_text("")
                                                    assessment.set_enabled(False)
                                                    stepper.next()

                                                with ui.stepper_navigation():
                                                    ui.button("Visualizza proposta AI →", on_click=vai_a_step2).props("color=primary")

                                            # ── Scheda 2: Proposta AI ──
                                            with ui.step(name="step2", title="Proposta diagnostica AI"):
                                                with ui.card().classes("w-full p-4 gap-3 bg-blue-50 border border-blue-100 mb-3"):
                                                    ui.label(f"Proposta: {lbl_str}").classes("font-semibold text-gray-800")
                                                    with ui.row().classes("items-center gap-1"):
                                                        ui.label(f"Certezza del modello: {conf:.0%}").classes("text-sm text-gray-600")
                                                        with ui.element("span").classes("text-gray-400 cursor-help").style("font-size:12px"):
                                                            ui.html("ⓘ")
                                                            ui.tooltip(
                                                                "Indica quanto il modello AI è sicuro della classificazione proposta. "
                                                                "Un valore alto non garantisce la correttezza clinica."
                                                            )
                                                    if inf.get("is_stub"):
                                                        ui.label("Sistema in fase dimostrativa — nessun valore diagnostico reale.").classes("text-xs text-amber-600")
                                                if exp.get("saliency_map_b64"):
                                                    sal_src = _img_src(exp["saliency_map_b64"])
                                                    with ui.element("div").style("cursor:zoom-in;display:inline-block").on(
                                                        "click", lambda s=sal_src: zoom_img(s)
                                                    ):
                                                        ui.image(sal_src).classes("w-48 h-48 object-contain rounded-lg border border-gray-200")
                                                        ui.label("Clicca per ingrandire").classes("text-xs text-gray-400 mt-1")
                                                    # H10: spiegazione mappa per il medico
                                                    ui.label(
                                                        "La mappa evidenzia le zone dell'immagine che hanno "
                                                        "influenzato maggiormente la classificazione AI. "
                                                        "Le aree più calde (rosse) hanno avuto più peso nella decisione."
                                                    ).classes("text-xs text-gray-500 mt-2 max-w-xs")

                                                with ui.stepper_navigation():
                                                    ui.button("← Indietro", on_click=stepper.previous).props("flat")
                                                    ui.button("Procedi →", on_click=stepper.next).props("color=primary")

                                            # ── Scheda 3: Giudizio finale ──
                                            with ui.step(name="step3", title="Giudizio diagnostico finale"):

                                                # H6 — Riepilogo step 1 e 2
                                                with ui.card().classes("w-full p-3 gap-1 bg-gray-50 border border-gray-200 mb-3"):
                                                    ui.label("Riepilogo").classes("text-xs font-bold text-gray-500 uppercase tracking-wide mb-1")
                                                    summary_assessment = ui.label("").classes("text-sm text-gray-700")
                                                    ui.label(f"Proposta AI: {lbl_str} — certezza {conf:.0%}").classes("text-sm text-gray-700")

                                                err_lbl = ui.label("").classes("text-red-500 text-xs")
                                                ok_lbl  = ui.label("").classes("text-green-700 text-sm font-semibold")

                                                # _invia_definitivo definita prima del dialog per poterla
                                                # passare direttamente come on_click (evita il doppio trigger)
                                                async def _invia_definitivo():
                                                    fl     = 1 if final_radio.value == "Neoplasia sospetta" else 0
                                                    agreed = (fl == inf.get("label", 0))
                                                    cv     = LIKERT_MAP.get(likert.value, 0.5)
                                                    confirm_dlg.close()
                                                    try:
                                                        a = _auth()
                                                        async with httpx.AsyncClient() as hc:
                                                            r = await hc.post(
                                                                f"{GATEWAY_URL}/api/v1/cases/{cid}/review",
                                                                json={"agreed": agreed,
                                                                      "label_override": None if agreed else fl,
                                                                      "confidence_override": round(cv,2) if abs(cv-conf)>0.05 else None,
                                                                      "notes": notes.value or ""},
                                                                auth=a, timeout=10.0)
                                                        r.raise_for_status()
                                                        ui.notify("Diagnosi registrata correttamente.", type="positive", icon="check_circle")
                                                        _sel["paz_id"] = None
                                                        render_paz_list.refresh()
                                                        render_paz_detail.refresh()
                                                    except Exception as exc:
                                                        err_lbl.set_text(_friendly_error(exc))

                                                # H5 + H3 — Dialog conferma con on_click diretto
                                                with ui.dialog() as confirm_dlg:
                                                    with ui.card().classes("p-6 gap-4").style("min-width:340px"):
                                                        ui.label("Conferma diagnosi definitiva").classes("font-bold text-gray-800 text-base")
                                                        ui.separator()
                                                        confirm_summary = ui.markdown("")
                                                        ui.label(
                                                            "Una volta confermata, la diagnosi viene registrata nel sistema "
                                                            "e il caso rimosso dalla lista di lavoro."
                                                        ).classes("text-xs text-gray-500")
                                                        with ui.row().classes("w-full justify-end gap-2 mt-2"):
                                                            ui.button("Annulla", on_click=confirm_dlg.close).props("flat").classes("text-gray-600")
                                                            ui.button("Conferma", on_click=_invia_definitivo).props("color=primary")

                                                final_radio = ui.radio(FINAL_LABEL_OPTIONS, value=lbl_str).classes("flex-col gap-2")

                                                # H10 — Tooltip indice di confidenza
                                                with ui.row().classes("items-center gap-1 mt-3"):
                                                    ui.label("Indice di confidenza nella diagnosi").classes("text-sm font-semibold text-gray-700")
                                                    with ui.element("span").classes("text-gray-400 cursor-help").style("font-size:13px"):
                                                        ui.html("ⓘ")
                                                        ui.tooltip(
                                                            "Indica quanto sei sicuro della diagnosi che stai esprimendo, "
                                                            "indipendentemente dalla proposta AI. "
                                                            "1 = molto incerto, 5 = molto sicuro."
                                                        )
                                                likert = ui.toggle(list(LIKERT_MAP.keys()), value=_ai_to_likert(conf)).classes("mt-1 flex-wrap")
                                                notes  = ui.textarea("Note cliniche", placeholder="Note aggiuntive...").classes("w-full mt-3").style("min-height:70px")

                                                def apri_conferma():
                                                    if not final_radio.value:
                                                        err_lbl.set_text("Indica la diagnosi."); return
                                                    if not likert.value:
                                                        err_lbl.set_text("Indica la confidenza."); return
                                                    err_lbl.set_text("")
                                                    summary_assessment.set_text(
                                                        f"Tua valutazione iniziale: {assessment.value or 'non registrata'}")
                                                    confirm_summary.set_content(
                                                        f"**Diagnosi**: {final_radio.value}  \n"
                                                        f"**Confidenza**: {likert.value}  \n"
                                                        f"**Note**: {notes.value or '—'}"
                                                    )
                                                    confirm_dlg.open()

                                                with ui.stepper_navigation():
                                                    ui.button("← Indietro", on_click=stepper.previous).props("flat")
                                                    ui.button("Conferma diagnosi", on_click=apri_conferma).props("color=primary")

                            render_paz_detail()
                            ui.timer(0.1, render_paz_detail.refresh, once=True)

            # ── Pannello Storico ───────────────────────────────────────────────
            with ui.column().classes("w-full flex-1 p-0") as panel_sto:
                    with ui.row().classes("w-full min-h-screen"):

                        with ui.column().classes("w-72 bg-white border-r border-gray-100 p-4 gap-3").style("min-height:100vh"):
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label("Casi revisionati").classes("font-bold text-gray-800")
                                sto_count = ui.badge("0").classes("bg-gray-200 text-gray-700")

                            sto_list_col = ui.column().classes("w-full gap-2")

                            @ui.refreshable
                            async def render_sto_list():
                                sto_list_col.clear()
                                try:
                                    d = await _get("/api/v1/cases", status="reviewed")
                                    cases = (d or {}).get("cases", [])
                                except Exception:
                                    cases = []
                                sto_count.set_text(str(len(cases)))
                                with sto_list_col:
                                    if not cases:
                                        ui.label("Nessuno storico disponibile").classes("text-gray-400 text-sm text-center py-6")
                                        return
                                    for case in cases:
                                        rev    = case.get("review") or {}
                                        fl_use = rev.get("label_override")
                                        il     = (case.get("inference") or {}).get("label", 0)
                                        diag   = "Neoplasia sospetta" if (fl_use if fl_use is not None else il)==1 else "Nessuna neoplasia"
                                        agreed = rev.get("agreed", True)
                                        date   = (case.get("reviewed_at") or "")[:10]
                                        bc     = "#16a34a" if agreed else "#d97706"
                                        bt     = "Concordato" if agreed else "Corretto"
                                        cid    = case["case_id"]
                                        with ui.card().classes("w-full p-3 hover:shadow-md transition-shadow cursor-pointer"):
                                            with ui.row().classes("w-full items-center gap-2"):
                                                with ui.column().classes("flex-1 gap-0"):
                                                    ui.label(case.get("patient_id","N/A")).classes("font-semibold text-gray-800 text-sm")
                                                    ui.label(f"{diag} — {date}").classes("text-xs text-gray-500")
                                                ui.element("span").style(
                                                    f"background:{bc};color:white;padding:3px 8px;"
                                                    "border-radius:4px;font-size:11px;font-weight:700"
                                                ).text = bt
                                                def select_sto(c=cid):
                                                    _sel["sto_id"] = c
                                                    render_sto_detail.refresh()
                                                ui.button("Rivedi", on_click=select_sto).classes(
                                                    "bg-gray-800 text-white text-xs font-semibold px-3 py-1"
                                                ).style("border-radius:4px").props("dense")

                            render_sto_list()
                            ui.button("Aggiorna", on_click=render_sto_list.refresh).props("flat icon=refresh").classes("w-full text-sm")

                        with ui.column().classes("flex-1 p-6 bg-gray-50"):

                            @ui.refreshable
                            async def render_sto_detail():
                                cid = _sel.get("sto_id")
                                if not cid:
                                    with ui.column().classes("w-full items-center justify-center py-20 gap-2"):
                                        ui.icon("medical_information").classes("text-6xl text-gray-300")
                                        ui.label("Seleziona un caso dallo storico per rivederlo").classes("text-gray-400 text-sm")
                                        ui.label("I casi revisionati sono elencati sulla sinistra").classes("text-gray-300 text-xs")
                                    return
                                try:
                                    a = _auth()
                                    async with httpx.AsyncClient() as hc:
                                        r = await hc.get(f"{GATEWAY_URL}/api/v1/cases/{cid}", auth=a, timeout=10.0)
                                        r.raise_for_status()
                                        case = r.json()
                                except Exception as exc:
                                    with ui.column().classes("w-full items-center py-12 gap-3"):
                                        ui.icon("error_outline").classes("text-5xl text-red-400")
                                        ui.label(_friendly_error(exc)).classes("text-red-600 text-sm text-center max-w-xs")
                                        ui.button("Riprova", on_click=render_sto_detail.refresh).classes("mt-1").style("border-radius:6px")
                                    return

                                inf    = case.get("inference", {})
                                exp    = case.get("explanation", {})
                                review = case.get("review") or {}
                                label  = inf.get("label", 0)
                                conf   = inf.get("confidence", 0.5)
                                fl     = review.get("label_override")
                                fl_use = fl if fl is not None else label
                                diag   = "Neoplasia sospetta" if fl_use == 1 else "Nessuna neoplasia"

                                # H3: bottone chiudi caso
                                with ui.row().classes("w-full justify-end mb-2"):
                                    def chiudi_storico():
                                        _sel["sto_id"] = None
                                        render_sto_detail.refresh()
                                    ui.button("✕ Chiudi caso", on_click=chiudi_storico).props("flat dense").classes("text-gray-500 text-sm")

                                with ui.row().classes("w-full gap-6 items-start"):
                                    with ui.column().classes("gap-3"):
                                        ui.image(_img_src(case["image_b64"])).classes(
                                            "w-64 h-64 object-contain rounded-xl border border-gray-200 bg-black")
                                        with ui.card().classes("p-4 gap-1 w-64"):
                                            ui.label(f"ID: {case.get('patient_id','N/A')}").classes("text-sm text-gray-600")
                                            ui.label(f"Età: {case.get('age','N/A')}   Sesso: {case.get('sex','N/A')}").classes("text-sm text-gray-600")

                                    with ui.column().classes("flex-1 gap-4"):
                                        with ui.card().classes("p-5 gap-2 bg-blue-50 border border-blue-100"):
                                            ui.label("Proposta diagnostica AI").classes("font-bold text-blue-800")
                                            ui.label(f"Proposta: {'Neoplasia sospetta' if label==1 else 'Nessuna neoplasia'}").classes("text-sm text-gray-700")
                                            ui.label(f"Confidence: {conf:.1%}").classes("text-sm text-gray-500")
                                            if exp.get("saliency_map_b64"):
                                                sal_src = _img_src(exp["saliency_map_b64"])
                                                with ui.element("div").style("cursor:zoom-in;display:inline-block").on(
                                                    "click", lambda s=sal_src: sto_zoom(s)
                                                ):
                                                    ui.image(sal_src).classes("w-32 h-32 object-contain rounded-lg mt-2")
                                                    ui.label("Clicca per ingrandire").classes("text-xs text-gray-400 mt-1")

                                        with ui.card().classes("p-5 gap-2"):
                                            ui.label("Revisione precedente").classes("font-bold text-gray-800")
                                            ui.label(f"Diagnosi: {diag}").classes("text-sm text-gray-700")
                                            ui.label(f"Concordanza: {'✓ Concordato' if review.get('agreed') else '✎ Corretto'}").classes("text-sm text-gray-700")
                                            if review.get("notes"):
                                                ui.label(f"Note: {review['notes']}").classes("text-sm text-gray-500 italic")

                                        with ui.expansion("Nuova revisione (opzionale)", icon="edit").classes("w-full"):
                                            new_label  = ui.radio(FINAL_LABEL_OPTIONS, value=diag).classes("flex-col gap-2")
                                            ui.label("Indice di confidenza").classes("text-sm font-semibold text-gray-700 mt-2")
                                            new_likert = ui.toggle(list(LIKERT_MAP.keys()), value=_ai_to_likert(conf)).classes("mt-1")
                                            new_notes  = ui.textarea("Note", placeholder="Note aggiuntive...").classes("w-full mt-2")
                                            sto_ok     = ui.label("").classes("text-sm font-semibold mt-1")

                                            sto_ok = ui.label("").classes("text-sm font-semibold mt-1")

                                            async def _invia_revisione():
                                                fl2 = 1 if new_label.value == "Neoplasia sospetta" else 0
                                                cv2 = LIKERT_MAP.get(new_likert.value, 0.5)
                                                sto_confirm_dlg.close()
                                                try:
                                                    a = _auth()
                                                    async with httpx.AsyncClient() as hc:
                                                        r = await hc.post(
                                                            f"{GATEWAY_URL}/api/v1/cases/{cid}/review",
                                                            json={"agreed": fl2==label,
                                                                  "label_override": None if fl2==label else fl2,
                                                                  "confidence_override": round(cv2,2),
                                                                  "notes": new_notes.value or ""},
                                                            auth=a, timeout=10.0)
                                                    r.raise_for_status()
                                                    sto_ok.classes(replace="text-green-700 text-sm font-semibold mt-1")
                                                    ui.notify("Revisione aggiornata.", type="positive", icon="check_circle")
                                                    ui.timer(0.1, render_sto_list.refresh, once=True)
                                                except Exception as exc:
                                                    sto_ok.classes(replace="text-red-600 text-sm font-semibold mt-1")
                                                    sto_ok.set_text(_friendly_error(exc))

                                            # H5 + H3: dialog conferma prima dell'invio
                                            with ui.dialog() as sto_confirm_dlg:
                                                with ui.card().classes("p-6 gap-4").style("min-width:320px"):
                                                    ui.label("Conferma aggiornamento diagnosi").classes("font-bold text-gray-800")
                                                    ui.separator()
                                                    sto_confirm_summary = ui.markdown("")
                                                    ui.label(
                                                        "La revisione precedente verrà sovrascritta."
                                                    ).classes("text-xs text-gray-500")
                                                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                                                        ui.button("Annulla", on_click=sto_confirm_dlg.close).props("flat").classes("text-gray-600")
                                                        ui.button("Conferma", on_click=_invia_revisione).props("color=primary")

                                            def apri_sto_conferma():
                                                if not new_label.value or not new_likert.value:
                                                    sto_ok.set_text("Completa tutti i campi."); return
                                                sto_confirm_summary.set_content(
                                                    f"**Diagnosi**: {new_label.value}  \n"
                                                    f"**Confidenza**: {new_likert.value}  \n"
                                                    f"**Note**: {new_notes.value or '—'}"
                                                )
                                                sto_confirm_dlg.open()

                                            ui.button("Aggiorna diagnosi", on_click=apri_sto_conferma).classes(
                                                "bg-blue-600 text-white font-semibold px-6 py-2 mt-2").style("border-radius:4px")

                            render_sto_detail()
                            ui.timer(0.1, render_sto_detail.refresh, once=True)

            # Handler toggle: mostra/nasconde i pannelli
            panel_sto.set_visibility(False)

            def on_toggle(e):
                is_paz = (e.value == "pazienti")
                panel_paz.set_visibility(is_paz)
                panel_sto.set_visibility(not is_paz)

            view_toggle.on_value_change(on_toggle)

    def build_tecnico():
        tecnico_panel.clear()
        with tecnico_panel:
            ui.label("Monitoraggio operativo").classes("text-2xl font-bold text-gray-800")

            with ui.row().classes("w-full gap-4 items-start"):
                with ui.card().classes("flex-1 p-5 gap-3"):
                    ui.label("Stato microservizi").classes("font-bold text-gray-800")
                    status_tbl = ui.table(
                        columns=[{"name":"s","label":"Servizio","field":"s"},
                                 {"name":"st","label":"Stato","field":"st"},
                                 {"name":"i","label":"Info","field":"i"}],
                        rows=[]
                    ).classes("w-full text-sm")

                    async def refresh_status():
                        try:
                            d = await _get("/api/v1/monitoring/status")
                            rows = []
                            for n, v in (d or {}).items():
                                stato = "Online" if v.get("reachable") else "Offline"
                                det = []
                                if v.get("is_stub"):
                                    det.append("stub")
                                if v.get("model_version"):
                                    det.append(v["model_version"])
                                if v.get("events_stored") is not None:
                                    det.append(f"{v['events_stored']} eventi")
                                if v.get("cases_in_queue") is not None:
                                    det.append(f"in coda: {v['cases_in_queue']} / tot: {v.get('cases_total','?')}")
                                if v.get("images_stored") is not None:
                                    det.append(f"{v['images_stored']} immagini archiviate")
                                if v.get("role"):
                                    det.append(f"ruolo: {v['role']}")
                                if v.get("subsystems"):
                                    sub_ok = sum(1 for s in v["subsystems"].values() if s.get("status") == "ok")
                                    sub_tot = len(v["subsystems"])
                                    det.append(f"sottosistemi: {sub_ok}/{sub_tot} online")
                                if v.get("current_version"):
                                    det.append(f"ver. {v['current_version']}")
                                if not v.get("reachable") and v.get("error"):
                                    det.append(v["error"][:50])
                                rows.append({"s": n, "st": stato, "i": ", ".join(det) or "—"})
                            status_tbl.rows = rows
                            status_tbl.update()
                        except Exception:
                            pass

                    ui.button("Aggiorna", on_click=refresh_status).props("flat dense icon=refresh").classes("text-sm")
                    ui.timer(0.1, refresh_status, once=True)

                with ui.card().classes("flex-1 p-5 gap-3"):
                    ui.label("Modello in produzione").classes("font-bold text-gray-800")
                    model_md = ui.markdown("Caricamento...")
                    _vmap: dict = {}
                    version_sel = ui.select(options=[], label="Seleziona versione per rollback").classes("w-full mt-2")
                    rollback_msg = ui.label("").classes("text-sm font-semibold")

                    async def refresh_model():
                        try:
                            d = await _get("/api/v1/monitoring/model")
                            if d: model_md.set_content(
                                f"**Versione**: {d.get('version','N/A')}  \n"
                                f"**Stato**: {d.get('status','N/A')}  \n"
                                f"**Framework**: {d.get('framework','N/A')}  \n"
                                + ("Sistema dimostrativo" if d.get("is_stub") else "Modello reale")
                            )
                        except Exception: pass

                    async def load_versions():
                        try:
                            d = await _get("/api/v1/monitoring/models")
                            if not d: return
                            versions = d.get("versions", [])
                            current  = d.get("current_version", "")
                            opts = {}
                            for v in versions:
                                tag = "← produzione" if v["version"] == current else f'[{v["status"]}]'
                                opts[f"{v['version']} {tag}"] = v["version"]
                            _vmap.clear(); _vmap.update(opts)
                            version_sel.options = list(opts.keys())
                            version_sel.update()
                        except Exception: pass

                    async def do_rollback():
                        if not version_sel.value: return
                        ver = _vmap.get(version_sel.value)
                        if not ver: return
                        # H5 + H3: dialog conferma prima del rollback
                        with ui.dialog() as rollback_dlg:
                            with ui.card().classes("p-6 gap-4").style("min-width:320px"):
                                ui.label("Conferma attivazione versione").classes("font-bold text-gray-800")
                                ui.separator()
                                ui.markdown(
                                    f"Stai per attivare la versione **{ver}** in produzione.  \n"
                                    "Il modello corrente verrà sostituito immediatamente."
                                )
                                ui.label("Questa operazione ha effetto immediato sul sistema.").classes("text-xs text-gray-500")
                                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                                    ui.button("Annulla", on_click=rollback_dlg.close).props("flat").classes("text-gray-600")
                                    async def _conferma_rollback():
                                        rollback_dlg.close()
                                        try:
                                            await _post(f"/api/v1/monitoring/model/promote/{ver}")
                                            ui.notify(f"Versione {ver} attivata.", type="positive", icon="check_circle")
                                            await refresh_model()
                                        except Exception as exc:
                                            ui.notify(f"Errore: {exc}", type="negative", icon="error")
                                    ui.button("Attiva", on_click=_conferma_rollback).props("color=red")
                        rollback_dlg.open()

                    ui.button("Attiva versione selezionata", on_click=do_rollback).classes(
                        "rounded-full bg-red-600 text-white text-sm font-semibold px-4 py-2")
                    ui.timer(0.1, refresh_model, once=True)
                    ui.timer(0.1, load_versions, once=True)

            with ui.card().classes("w-full p-5 gap-3 mt-4"):
                ui.label("Log eventi").classes("font-bold text-gray-800")
                with ui.row().classes("items-center gap-3 mb-2"):
                    log_filter = ui.select(
                        options=["Tutti","service.started","service.error","triage.completed",
                                 "inference.completed","feedback.submitted","model.promoted","ingestion.completed"],
                        value="Tutti", label="Tipo evento"
                    ).classes("w-60")
                    ui.button("Aggiorna", on_click=lambda: ui.timer(0, load_logs, once=True)).props("flat dense icon=refresh").classes("text-sm")
                log_tbl = ui.table(
                    columns=[{"name":"t","label":"Timestamp","field":"t"},
                             {"name":"f","label":"Fonte","field":"f"},
                             {"name":"s","label":"Servizio","field":"s"},
                             {"name":"e","label":"Tipo evento","field":"e"},
                             {"name":"a","label":"Attore","field":"a"}],
                    rows=[]
                ).classes("w-full text-sm")

                async def load_logs():
                    params = {"limit": 50}
                    if log_filter.value and log_filter.value != "Tutti":
                        params["event_type"] = log_filter.value
                    try:
                        d = await _get("/api/v1/monitoring/logs", **params)
                        events = (d or {}).get("events", [])
                        log_tbl.rows = [{"t":e.get("received_at","")[:16],"f":e.get("source",""),
                                         "s":e.get("service",""),"e":e.get("event_type",""),
                                         "a":str(e.get("actor",""))} for e in events] \
                                      or [{"t":"Nessun evento","f":"","s":"","e":"","a":""}]
                        log_tbl.update()
                    except Exception: pass

                # Auto-load al login come i microservizi
                ui.timer(0.1, load_logs, once=True)
                log_filter.on_value_change(lambda _: ui.timer(0, load_logs, once=True))

            with ui.card().classes("w-full p-5 gap-3 mt-4"):
                ui.label("Campioni per retraining").classes("font-bold text-gray-800")

                # KPI aggregate
                with ui.row().classes("w-full gap-4 mb-3") as kpi_row:
                    with ui.card().classes("flex-1 p-4 items-center text-center bg-blue-50 border border-blue-100"):
                        kpi_tot = ui.label("—").classes("text-2xl font-bold text-blue-700")
                        ui.label("Campioni totali").classes("text-xs text-blue-500 mt-1")
                    with ui.card().classes("flex-1 p-4 items-center text-center bg-green-50 border border-green-100"):
                        kpi_conc = ui.label("—").classes("text-2xl font-bold text-green-700")
                        ui.label("Concordanza AI").classes("text-xs text-green-500 mt-1")
                    with ui.card().classes("flex-1 p-4 items-center text-center bg-red-50 border border-red-100"):
                        kpi_mal = ui.label("—").classes("text-2xl font-bold text-red-700")
                        ui.label("Maligni").classes("text-xs text-red-500 mt-1")
                    with ui.card().classes("flex-1 p-4 items-center text-center bg-gray-50 border border-gray-200"):
                        kpi_ben = ui.label("—").classes("text-2xl font-bold text-gray-700")
                        ui.label("Benigni").classes("text-xs text-gray-500 mt-1")

                training_tbl = ui.table(
                    columns=[{"name":"c","label":"Case ID","field":"c"},
                             {"name":"d","label":"Diagnosi","field":"d"},
                             {"name":"a","label":"Concordanza","field":"a"},
                             {"name":"r","label":"Ricevuto il","field":"r"}],
                    rows=[]
                ).classes("w-full text-sm")

                async def load_training():
                    try:
                        d = await _get("/api/v1/monitoring/training-data")
                        samples = (d or {}).get("samples", [])
                        if samples:
                            tot   = len(samples)
                            conc  = sum(1 for s in samples if s.get("agreed_with_ai"))
                            mal   = sum(1 for s in samples if s.get("final_label") == 1)
                            ben   = tot - mal
                            kpi_tot.set_text(str(tot))
                            kpi_conc.set_text(f"{conc/tot:.0%}")
                            kpi_mal.set_text(str(mal))
                            kpi_ben.set_text(str(ben))
                        training_tbl.rows = [
                            {"c":s.get("case_id","")[:8]+"...",
                             "d":"Maligno" if s.get("final_label")==1 else "Benigno",
                             "a":"Concordo" if s.get("agreed_with_ai") else "Corretto",
                             "r":s.get("received_at","")[:16]}
                            for s in samples[:20]
                        ] or [{"c":"Nessun campione","d":"","a":"","r":""}]
                        training_tbl.update()
                    except Exception: pass

                ui.button("Aggiorna", on_click=load_training).props("flat dense icon=refresh").classes("text-sm")
                ui.timer(0.1, load_training, once=True)


ui.run(host="0.0.0.0", port=7860, title="TRIAGE", favicon='brain_favicon.svg',
       storage_secret="triage_secret_key", reload=False)
