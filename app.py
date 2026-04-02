"""
Dutch Bookkeeping Tool — Free alternative to a €1,200/year bookkeeper.
Built with Dash for Dutch freelancers and small businesses (ZZP/BV).
"""

import json
import os
import uuid
from datetime import datetime, date
from io import StringIO
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, ctx, dash_table, dcc, html

# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------
DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "bookkeeping.json"

EMPTY_DATA = {
    "transactions": [],
    "invoices": [],
    "audit_log": [],
    "company": {
        "name": "",
        "kvk": "",
        "btw_id": "",
        "address": "",
        "bank_iban": "",
    },
}

# Dutch fiscal administration retention: 7 years (Belastingdienst)
FISCAL_RETENTION_YEARS = 7

CATEGORIES_INCOME = [
    "Omzet diensten (services)",
    "Omzet producten (products)",
    "Overige inkomsten (other income)",
]

CATEGORIES_EXPENSE = [
    "Kantoorkosten (office)",
    "Reiskosten (travel)",
    "Telefoon & internet",
    "Software & abonnementen",
    "Verzekeringen (insurance)",
    "Professionele diensten (legal/accounting)",
    "Marketing & reclame",
    "Afschrijvingen (depreciation)",
    "Autokosten (vehicle)",
    "Overige kosten (other expenses)",
]

BTW_RATES = {"21%": 0.21, "9%": 0.09, "0% (vrijgesteld)": 0.0, "Geen BTW": 0.0}


def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        # Ensure audit_log exists for older data files
        data.setdefault("audit_log", [])
        return data
    return json.loads(json.dumps(EMPTY_DATA))


def save_data(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    # Create timestamped backup before overwriting (Dutch law: 7-year retention)
    if DATA_FILE.exists():
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"bookkeeping_{ts}.json"
        # Only keep daily backups to avoid disk bloat
        existing = sorted(backup_dir.glob("bookkeeping_*.json"))
        today_prefix = f"bookkeeping_{datetime.now().strftime('%Y%m%d')}"
        today_backups = [f for f in existing if f.name.startswith(today_prefix)]
        if not today_backups:
            import shutil
            shutil.copy2(DATA_FILE, backup_file)
        # Clean backups older than retention period
        cutoff = datetime.now().timestamp() - (FISCAL_RETENTION_YEARS * 365.25 * 86400)
        for old in existing:
            if old.stat().st_mtime < cutoff:
                old.unlink()
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def add_audit_entry(data: dict, action: str, details: str):
    """Append an immutable audit log entry — required for Dutch fiscal compliance."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "details": details,
    }
    data.setdefault("audit_log", []).append(entry)


def validate_btw_id(btw_id: str) -> bool:
    """Basic validation of Dutch BTW identification number format: NL + 9 digits + B + 2 digits."""
    import re
    if not btw_id:
        return True  # optional field
    return bool(re.match(r"^NL\d{9}B\d{2}$", btw_id.strip()))


def validate_iban(iban: str) -> bool:
    """Basic validation of Dutch IBAN format."""
    import re
    if not iban:
        return True
    return bool(re.match(r"^NL\d{2}[A-Z]{4}\d{10}$", iban.strip().replace(" ", "")))


# ---------------------------------------------------------------------------
# Dash app
# ---------------------------------------------------------------------------
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    suppress_callback_exceptions=True,
    title="Boekhouding — Dutch Bookkeeping",
)

# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

SIDEBAR = dbc.Nav(
    [
        dbc.NavLink("Dashboard", href="/", active="exact", id="nav-dashboard"),
        dbc.NavLink("Transacties", href="/transactions", active="exact"),
        dbc.NavLink("BTW Aangifte", href="/btw", active="exact"),
        dbc.NavLink("Facturen", href="/invoices", active="exact"),
        dbc.NavLink("Import / Export", href="/import-export", active="exact"),
        dbc.NavLink("Audit Log", href="/audit", active="exact"),
        dbc.NavLink("Instellingen", href="/settings", active="exact"),
    ],
    vertical=True,
    pills=True,
    className="bg-light p-3",
)


def make_layout():
    return dbc.Container(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="data-store", storage_type="memory"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H4("Boekhouding", className="text-primary mb-3 mt-3"),
                            html.Hr(),
                            SIDEBAR,
                        ],
                        width=2,
                        className="border-end min-vh-100",
                    ),
                    dbc.Col(html.Div(id="page-content", className="p-4"), width=10),
                ]
            ),
        ],
        fluid=True,
    )


app.layout = make_layout

# ========================================================================
# PAGE: Dashboard
# ========================================================================


def dashboard_page(data):
    txns = data.get("transactions", [])
    if not txns:
        return html.Div(
            [
                html.H3("Dashboard"),
                dbc.Alert(
                    "Nog geen transacties. Voeg je eerste transactie toe!",
                    color="info",
                ),
            ]
        )

    df = pd.DataFrame(txns)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["quarter"] = df["date"].dt.to_period("Q").astype(str)

    current_year = str(datetime.now().year)
    df_year = df[df["date"].dt.year == int(current_year)]

    total_income = df_year.loc[df_year["type"] == "income", "amount"].sum()
    total_expense = df_year.loc[df_year["type"] == "expense", "amount"].sum()
    profit = total_income - total_expense

    # BTW summary
    df_year_copy = df_year.copy()
    df_year_copy["btw_rate_val"] = df_year_copy["btw_rate"].map(BTW_RATES).fillna(0)
    df_year_copy["btw_amount"] = (
        df_year_copy["amount"]
        * df_year_copy["btw_rate_val"]
        / (1 + df_year_copy["btw_rate_val"])
    )
    btw_collected = df_year_copy.loc[
        df_year_copy["type"] == "income", "btw_amount"
    ].sum()
    btw_paid = df_year_copy.loc[
        df_year_copy["type"] == "expense", "btw_amount"
    ].sum()
    btw_due = btw_collected - btw_paid

    # Monthly chart
    monthly = (
        df_year.groupby(["month", "type"])["amount"]
        .sum()
        .reset_index()
    )
    fig_monthly = px.bar(
        monthly,
        x="month",
        y="amount",
        color="type",
        barmode="group",
        title=f"Maandelijks overzicht {current_year}",
        color_discrete_map={"income": "#2ecc71", "expense": "#e74c3c"},
        labels={"amount": "Bedrag (€)", "month": "Maand", "type": "Type"},
    )

    # Category breakdown (expenses)
    cat_expense = (
        df_year[df_year["type"] == "expense"]
        .groupby("category")["amount"]
        .sum()
        .reset_index()
    )
    fig_cat = px.pie(
        cat_expense,
        values="amount",
        names="category",
        title="Uitgaven per categorie",
    ) if len(cat_expense) > 0 else go.Figure()

    return html.Div(
        [
            html.H3(f"Dashboard — {current_year}"),
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("Omzet", className="text-muted"),
                                    html.H4(
                                        f"€ {total_income:,.2f}",
                                        className="text-success",
                                    ),
                                ]
                            )
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("Uitgaven", className="text-muted"),
                                    html.H4(
                                        f"€ {total_expense:,.2f}",
                                        className="text-danger",
                                    ),
                                ]
                            )
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("Winst", className="text-muted"),
                                    html.H4(
                                        f"€ {profit:,.2f}",
                                        className="text-primary",
                                    ),
                                ]
                            )
                        ),
                        width=3,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H6("BTW afdracht", className="text-muted"),
                                    html.H4(
                                        f"€ {btw_due:,.2f}",
                                        className="text-warning",
                                    ),
                                ]
                            )
                        ),
                        width=3,
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(dcc.Graph(figure=fig_monthly), width=7),
                    dbc.Col(dcc.Graph(figure=fig_cat), width=5),
                ]
            ),
            html.Hr(),
            _compliance_warnings(data, df_year, current_year),
        ]
    )


def _compliance_warnings(data, df_year, current_year):
    """Generate Dutch compliance warnings and reminders."""
    warnings = []
    company = data.get("company", {})

    # Check company details are filled in (required on invoices per Dutch law)
    missing = []
    if not company.get("name"):
        missing.append("Bedrijfsnaam")
    if not company.get("kvk"):
        missing.append("KVK nummer")
    if not company.get("btw_id"):
        missing.append("BTW-identificatienummer")
    if not company.get("bank_iban"):
        missing.append("IBAN")
    if missing:
        warnings.append(
            dbc.Alert(
                [
                    html.Strong("Bedrijfsgegevens incompleet: "),
                    f"Vul de volgende velden in bij Instellingen: {', '.join(missing)}. "
                    "Deze gegevens zijn wettelijk verplicht op facturen (KVK-wet).",
                ],
                color="warning",
            )
        )

    # BTW filing deadline reminders
    now = datetime.now()
    q = (now.month - 1) // 3  # previous quarter (0-indexed)
    deadline_months = {0: (1, "Q4 vorig jaar"), 1: (4, "Q1"), 2: (7, "Q2"), 3: (10, "Q3")}
    if q in deadline_months:
        dl_month, q_label = deadline_months[q]
        # Dutch BTW deadline: last day of month following quarter end
        import calendar
        dl_year = now.year if q > 0 else now.year
        dl_day = calendar.monthrange(dl_year, dl_month)[1]
        deadline = date(dl_year, dl_month, dl_day)
        if now.date() <= deadline:
            days_left = (deadline - now.date()).days
            if days_left <= 14:
                warnings.append(
                    dbc.Alert(
                        [
                            html.Strong(f"BTW aangifte deadline: "),
                            f"{q_label} {current_year} — nog {days_left} dagen "
                            f"(deadline: {deadline.strftime('%d-%m-%Y')}). "
                            "Ga naar BTW Aangifte voor je overzicht.",
                        ],
                        color="danger",
                    )
                )

    # Check for transactions without descriptions (audit risk)
    no_desc = len(df_year[df_year.get("description", pd.Series(dtype=str)).eq("") | df_year.get("description", pd.Series(dtype=str)).isna()]) if "description" in df_year.columns else 0
    if no_desc > 0:
        warnings.append(
            dbc.Alert(
                [
                    html.Strong(f"{no_desc} transactie(s) zonder omschrijving. "),
                    "De Belastingdienst vereist dat elke boeking een duidelijke omschrijving heeft. "
                    "Voeg omschrijvingen toe om problemen bij controle te voorkomen.",
                ],
                color="info",
            )
        )

    # KOR (Kleineondernemersregeling) threshold check
    total_income = df_year.loc[df_year["type"] == "income", "amount"].sum() if len(df_year) > 0 else 0
    if total_income > 0 and total_income <= 20000:
        warnings.append(
            dbc.Alert(
                [
                    html.Strong("KOR drempel: "),
                    f"Je omzet (€{total_income:,.2f}) valt onder de €20.000 KOR-grens. "
                    "Overweeg de Kleineondernemersregeling (KOR) bij de Belastingdienst — "
                    "je hoeft dan geen BTW af te dragen.",
                ],
                color="info",
            )
        )

    if not warnings:
        warnings.append(
            dbc.Alert("Geen waarschuwingen — alles ziet er goed uit!", color="success")
        )

    return html.Div(
        [html.H5("Compliance & Waarschuwingen")] + warnings
    )


# ========================================================================
# PAGE: Transactions
# ========================================================================

def transactions_page(data):
    txns = data.get("transactions", [])

    form = dbc.Card(
        dbc.CardBody(
            [
                html.H5("Nieuwe transactie"),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Datum"),
                                dcc.DatePickerSingle(
                                    id="txn-date",
                                    date=date.today().isoformat(),
                                    display_format="DD-MM-YYYY",
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Type"),
                                dbc.Select(
                                    id="txn-type",
                                    options=[
                                        {"label": "Inkomst", "value": "income"},
                                        {"label": "Uitgave", "value": "expense"},
                                    ],
                                    value="expense",
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Bedrag (€) incl. BTW"),
                                dbc.Input(
                                    id="txn-amount",
                                    type="number",
                                    min=0,
                                    step=0.01,
                                    placeholder="0.00",
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("BTW tarief"),
                                dbc.Select(
                                    id="txn-btw",
                                    options=[
                                        {"label": k, "value": k} for k in BTW_RATES
                                    ],
                                    value="21%",
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Categorie"),
                                dbc.Select(
                                    id="txn-category",
                                    options=[],  # populated by callback
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Omschrijving"),
                                dbc.Input(
                                    id="txn-desc",
                                    type="text",
                                    placeholder="Korte omschrijving",
                                ),
                            ],
                            width=2,
                        ),
                    ],
                    className="mb-3",
                ),
                dbc.Button(
                    "Toevoegen", id="txn-add-btn", color="primary", className="me-2"
                ),
                dbc.Button(
                    "Verwijder geselecteerde",
                    id="txn-delete-btn",
                    color="danger",
                    outline=True,
                ),
                html.Div(id="txn-feedback", className="mt-2"),
            ]
        ),
        className="mb-4",
    )

    df = pd.DataFrame(txns) if txns else pd.DataFrame(
        columns=["id", "date", "type", "amount", "btw_rate", "category", "description"]
    )
    if "id" not in df.columns:
        df["id"] = ""

    table = dash_table.DataTable(
        id="txn-table",
        columns=[
            {"name": "Datum", "id": "date"},
            {"name": "Type", "id": "type"},
            {"name": "Bedrag (€)", "id": "amount", "type": "numeric",
             "format": dash_table.FormatTemplate.money(2)},
            {"name": "BTW", "id": "btw_rate"},
            {"name": "Categorie", "id": "category"},
            {"name": "Omschrijving", "id": "description"},
        ],
        data=df.sort_values("date", ascending=False).to_dict("records") if len(df) > 0 else [],
        row_selectable="multi",
        page_size=20,
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "left", "padding": "8px"},
        style_header={"fontWeight": "bold", "backgroundColor": "#ecf0f1"},
        style_data_conditional=[
            {
                "if": {"filter_query": '{type} = "income"'},
                "color": "#27ae60",
            },
            {
                "if": {"filter_query": '{type} = "expense"'},
                "color": "#c0392b",
            },
        ],
        filter_action="native",
        sort_action="native",
    )

    return html.Div([html.H3("Transacties"), html.Hr(), form, table])


# ========================================================================
# PAGE: BTW Aangifte
# ========================================================================

def btw_page(data):
    txns = data.get("transactions", [])
    if not txns:
        return html.Div(
            [
                html.H3("BTW Aangifte"),
                dbc.Alert("Geen transacties beschikbaar.", color="info"),
            ]
        )

    df = pd.DataFrame(txns)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["quarter"] = df["date"].dt.to_period("Q").astype(str)
    df["btw_rate_val"] = df["btw_rate"].map(BTW_RATES).fillna(0)
    # Amounts excl. BTW and BTW component
    df["amount_excl"] = df.apply(
        lambda r: r["amount"] / (1 + r["btw_rate_val"]) if r["btw_rate_val"] > 0 else r["amount"],
        axis=1,
    ).round(2)
    df["btw_amount"] = (df["amount"] - df["amount_excl"]).round(2)

    quarters = sorted(df["quarter"].unique(), reverse=True)

    # Quarter selector
    quarter_options = [{"label": q, "value": q} for q in quarters]

    return html.Div(
        [
            html.H3("BTW Aangifte (per kwartaal)"),
            html.P(
                "Overzicht volgens de rubrieken van de BTW-aangifte bij MijnBelastingdienst. "
                "Gebruik deze nummers bij het invullen van je aangifte.",
                className="text-muted",
            ),
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Label("Selecteer kwartaal"),
                            dbc.Select(
                                id="btw-quarter-select",
                                options=quarter_options,
                                value=quarters[0] if quarters else None,
                            ),
                        ],
                        width=3,
                    ),
                ],
                className="mb-4",
            ),
            html.Div(id="btw-quarter-detail"),
        ]
    )


@callback(
    Output("btw-quarter-detail", "children"),
    Input("btw-quarter-select", "value"),
)
def render_btw_quarter(selected_quarter):
    if not selected_quarter:
        return dbc.Alert("Selecteer een kwartaal.", color="info")

    data = load_data()
    txns = data.get("transactions", [])
    df = pd.DataFrame(txns)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["quarter"] = df["date"].dt.to_period("Q").astype(str)
    df["btw_rate_val"] = df["btw_rate"].map(BTW_RATES).fillna(0)
    df["amount_excl"] = df.apply(
        lambda r: r["amount"] / (1 + r["btw_rate_val"]) if r["btw_rate_val"] > 0 else r["amount"],
        axis=1,
    ).round(2)
    df["btw_amount"] = (df["amount"] - df["amount_excl"]).round(2)

    dq = df[df["quarter"] == selected_quarter]
    if dq.empty:
        return dbc.Alert("Geen transacties in dit kwartaal.", color="info")

    income = dq[dq["type"] == "income"]
    expense = dq[dq["type"] == "expense"]

    # --- Rubriek 1a: Leveringen/diensten belast met 21% ---
    inc_21 = income[income["btw_rate"] == "21%"]
    r1a_omzet = inc_21["amount_excl"].sum()
    r1a_btw = inc_21["btw_amount"].sum()

    # --- Rubriek 1b: Leveringen/diensten belast met 9% ---
    inc_9 = income[income["btw_rate"] == "9%"]
    r1b_omzet = inc_9["amount_excl"].sum()
    r1b_btw = inc_9["btw_amount"].sum()

    # --- Rubriek 1e: Leveringen/diensten belast met 0% of niet bij u belast ---
    inc_0 = income[income["btw_rate"].isin(["0% (vrijgesteld)", "Geen BTW"])]
    r1e_omzet = inc_0["amount_excl"].sum()

    # --- Rubriek 5a: Totaal verschuldigde BTW ---
    r5a = r1a_btw + r1b_btw

    # --- Rubriek 5b: Voorbelasting (all input VAT on expenses, one number) ---
    r5b = expense["btw_amount"].sum()

    # --- Rubriek 5c: Subtotaal ---
    r5c = r5a - r5b

    # --- Rubriek 5f: Te betalen / terug te ontvangen ---
    r5f = r5c  # No KOR or estimate corrections in this tool

    # Build the form-like display
    form_table = dbc.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Rubriek", style={"width": "100px"}),
                        html.Th("Omschrijving"),
                        html.Th("Omzet (€)", style={"width": "150px", "textAlign": "right"}),
                        html.Th("BTW (€)", style={"width": "150px", "textAlign": "right"}),
                    ]
                ),
                className="table-dark",
            ),
            html.Tbody(
                [
                    # Section 1 header
                    html.Tr(
                        html.Td(
                            html.Strong("1. Prestaties binnenland"),
                            colSpan=4,
                        ),
                        className="table-secondary",
                    ),
                    html.Tr(
                        [
                            html.Td("1a"),
                            html.Td("Leveringen/diensten belast met 21%"),
                            html.Td(f"{r1a_omzet:,.2f}", style={"textAlign": "right"}),
                            html.Td(f"{r1a_btw:,.2f}", style={"textAlign": "right"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("1b"),
                            html.Td("Leveringen/diensten belast met 9%"),
                            html.Td(f"{r1b_omzet:,.2f}", style={"textAlign": "right"}),
                            html.Td(f"{r1b_btw:,.2f}", style={"textAlign": "right"}),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("1e"),
                            html.Td("Leveringen/diensten belast met 0% of niet bij u belast"),
                            html.Td(f"{r1e_omzet:,.2f}", style={"textAlign": "right"}),
                            html.Td("—", style={"textAlign": "right"}),
                        ]
                    ),
                    # Section 5 header
                    html.Tr(
                        html.Td(
                            html.Strong("5. Voorbelasting en totaal"),
                            colSpan=4,
                        ),
                        className="table-secondary",
                    ),
                    html.Tr(
                        [
                            html.Td("5a"),
                            html.Td("Totaal verschuldigde BTW (1a + 1b BTW)"),
                            html.Td("", style={"textAlign": "right"}),
                            html.Td(
                                html.Strong(f"{r5a:,.2f}"),
                                style={"textAlign": "right"},
                            ),
                        ],
                        className="table-warning" if r5a > 0 else "",
                    ),
                    html.Tr(
                        [
                            html.Td("5b"),
                            html.Td("Voorbelasting (BTW op je inkopen/kosten)"),
                            html.Td("", style={"textAlign": "right"}),
                            html.Td(
                                html.Strong(f"{r5b:,.2f}"),
                                style={"textAlign": "right", "color": "#27ae60"},
                            ),
                        ]
                    ),
                    html.Tr(
                        [
                            html.Td("5c"),
                            html.Td("Subtotaal (5a min 5b)"),
                            html.Td("", style={"textAlign": "right"}),
                            html.Td(
                                html.Strong(f"{r5c:,.2f}"),
                                style={"textAlign": "right"},
                            ),
                        ]
                    ),
                    # Final row
                    html.Tr(
                        [
                            html.Td(html.Strong("5f")),
                            html.Td(
                                html.Strong(
                                    "Te betalen aan Belastingdienst"
                                    if r5f >= 0
                                    else "Terug te ontvangen van Belastingdienst"
                                )
                            ),
                            html.Td("", style={"textAlign": "right"}),
                            html.Td(
                                html.Strong(f"€ {abs(r5f):,.2f}"),
                                style={
                                    "textAlign": "right",
                                    "fontSize": "1.2em",
                                    "color": "#c0392b" if r5f >= 0 else "#27ae60",
                                },
                            ),
                        ],
                        className="table-info",
                    ),
                ]
            ),
        ],
        bordered=True,
        hover=True,
        responsive=True,
        className="mb-4",
    )

    # Expense voorbelasting breakdown (helpful, not on the form itself)
    exp_by_cat = (
        expense.groupby("category")
        .agg({"amount_excl": "sum", "btw_amount": "sum", "amount": "sum"})
        .reset_index()
    )

    expense_detail = []
    if len(exp_by_cat) > 0:
        detail_rows = [
            html.Tr(
                [
                    html.Td(row["category"]),
                    html.Td(f"€ {row['amount']:,.2f}", style={"textAlign": "right"}),
                    html.Td(f"€ {row['btw_amount']:,.2f}", style={"textAlign": "right"}),
                ]
            )
            for _, row in exp_by_cat.iterrows()
        ]
        expense_detail = [
            html.Details(
                [
                    html.Summary("Specificatie voorbelasting (5b) per categorie"),
                    dbc.Table(
                        [
                            html.Thead(
                                html.Tr(
                                    [
                                        html.Th("Categorie"),
                                        html.Th("Bedrag incl.", style={"textAlign": "right"}),
                                        html.Th("BTW (voorbelasting)", style={"textAlign": "right"}),
                                    ]
                                )
                            ),
                            html.Tbody(detail_rows),
                        ],
                        bordered=True,
                        size="sm",
                        className="mt-2",
                    ),
                ],
                className="mb-4",
            )
        ]

    # Filing guidance
    guidance = dbc.Alert(
        [
            html.Strong("Invulinstructie: "),
            "Ga naar MijnBelastingdienst → Omzetbelasting → Aangifte doen. "
            "Vul de rubrieken 1a t/m 1e in met de bedragen hierboven. "
            "Rubriek 5b (voorbelasting) vul je in als één totaalbedrag. "
            "De rubrieken 2a, 3a-3c, 4a-4b zijn voor intracommunautaire/buitenlandse "
            "transacties — vul deze alleen in als je zaken doet buiten Nederland.",
        ],
        color="light",
        className="border",
    )

    return html.Div(
        [form_table] + expense_detail + [guidance]
    )


# ========================================================================
# PAGE: Invoices
# ========================================================================

def invoices_page(data):
    company = data.get("company", {})
    invoices = data.get("invoices", [])

    form = dbc.Card(
        dbc.CardBody(
            [
                html.H5("Nieuwe factuur"),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Klant naam"),
                                dbc.Input(id="inv-client", type="text"),
                            ],
                            width=3,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Klant adres"),
                                dbc.Input(id="inv-client-addr", type="text"),
                            ],
                            width=3,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Omschrijving"),
                                dbc.Input(id="inv-desc", type="text"),
                            ],
                            width=3,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Bedrag excl. BTW (€)"),
                                dbc.Input(
                                    id="inv-amount",
                                    type="number",
                                    min=0,
                                    step=0.01,
                                ),
                            ],
                            width=2,
                        ),
                    ],
                    className="mb-3",
                ),
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("BTW tarief"),
                                dbc.Select(
                                    id="inv-btw",
                                    options=[
                                        {"label": k, "value": k} for k in BTW_RATES
                                    ],
                                    value="21%",
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Factuurdatum"),
                                dcc.DatePickerSingle(
                                    id="inv-date",
                                    date=date.today().isoformat(),
                                    display_format="DD-MM-YYYY",
                                ),
                            ],
                            width=2,
                        ),
                        dbc.Col(
                            [
                                dbc.Label("Betaaltermijn (dagen)"),
                                dbc.Input(
                                    id="inv-terms",
                                    type="number",
                                    value=30,
                                    min=1,
                                ),
                            ],
                            width=2,
                        ),
                    ],
                    className="mb-3",
                ),
                dbc.Button(
                    "Factuur aanmaken",
                    id="inv-create-btn",
                    color="primary",
                ),
                html.Div(id="inv-feedback", className="mt-2"),
            ]
        ),
        className="mb-4",
    )

    # List existing invoices
    inv_rows = []
    for inv in sorted(invoices, key=lambda x: x.get("date", ""), reverse=True):
        btw_val = BTW_RATES.get(inv.get("btw_rate", "21%"), 0.21)
        amount_excl = inv.get("amount_excl", 0)
        amount_incl = amount_excl * (1 + btw_val)
        inv_rows.append(
            html.Tr(
                [
                    html.Td(inv.get("number", "")),
                    html.Td(inv.get("date", "")),
                    html.Td(inv.get("client", "")),
                    html.Td(inv.get("description", "")),
                    html.Td(f"€ {amount_excl:,.2f}"),
                    html.Td(inv.get("btw_rate", "")),
                    html.Td(f"€ {amount_incl:,.2f}"),
                    html.Td(
                        dbc.Button(
                            "Bekijk",
                            id={"type": "view-inv", "index": inv.get("id", "")},
                            size="sm",
                            color="info",
                            outline=True,
                        )
                    ),
                ]
            )
        )

    inv_table = dbc.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Nummer"),
                        html.Th("Datum"),
                        html.Th("Klant"),
                        html.Th("Omschrijving"),
                        html.Th("Excl. BTW"),
                        html.Th("BTW"),
                        html.Th("Incl. BTW"),
                        html.Th(""),
                    ]
                )
            ),
            html.Tbody(inv_rows),
        ],
        bordered=True,
        hover=True,
        responsive=True,
    )

    # Invoice preview modal
    modal = dbc.Modal(
        [
            dbc.ModalHeader("Factuur voorbeeld"),
            dbc.ModalBody(id="inv-preview-body"),
        ],
        id="inv-modal",
        size="lg",
        is_open=False,
    )

    return html.Div(
        [
            html.H3("Facturen"),
            html.Hr(),
            form,
            html.H5("Overzicht facturen"),
            inv_table if inv_rows else dbc.Alert("Nog geen facturen.", color="info"),
            modal,
        ]
    )


# ========================================================================
# PAGE: Import / Export
# ========================================================================

def import_export_page(data):
    return html.Div(
        [
            html.H3("Import / Export"),
            html.Hr(),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("CSV Importeren"),
                                    html.P(
                                        "Upload een CSV-bestand van je bank (kolommen: date, amount, description). "
                                        "Negatieve bedragen worden als uitgaven geïmporteerd.",
                                        className="text-muted",
                                    ),
                                    dcc.Upload(
                                        id="csv-upload",
                                        children=dbc.Button(
                                            "Kies CSV-bestand",
                                            color="secondary",
                                            outline=True,
                                        ),
                                        multiple=False,
                                        accept=".csv",
                                    ),
                                    html.Div(id="import-feedback", className="mt-2"),
                                ]
                            )
                        ),
                        width=6,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.H5("Exporteren"),
                                    html.P(
                                        "Download al je transacties als Excel of CSV.",
                                        className="text-muted",
                                    ),
                                    dbc.Button(
                                        "Download Excel",
                                        id="export-excel-btn",
                                        color="success",
                                        className="me-2",
                                    ),
                                    dbc.Button(
                                        "Download CSV",
                                        id="export-csv-btn",
                                        color="info",
                                        outline=True,
                                    ),
                                    dcc.Download(id="download-export"),
                                ]
                            )
                        ),
                        width=6,
                    ),
                ]
            ),
        ]
    )


# ========================================================================
# PAGE: Audit Log
# ========================================================================

def audit_page(data):
    log = data.get("audit_log", [])
    if not log:
        return html.Div(
            [
                html.H3("Audit Log"),
                html.P(
                    "Alle wijzigingen worden automatisch gelogd voor compliance met de "
                    "Nederlandse bewaarplicht (7 jaar). Dit logboek kan niet worden gewijzigd.",
                    className="text-muted",
                ),
                dbc.Alert("Nog geen audit entries.", color="info"),
            ]
        )

    df = pd.DataFrame(log)
    df = df.sort_values("timestamp", ascending=False)

    table = dash_table.DataTable(
        columns=[
            {"name": "Tijdstip", "id": "timestamp"},
            {"name": "Actie", "id": "action"},
            {"name": "Details", "id": "details"},
        ],
        data=df.to_dict("records"),
        page_size=50,
        style_table={"overflowX": "auto"},
        style_cell={"textAlign": "left", "padding": "8px"},
        style_header={"fontWeight": "bold", "backgroundColor": "#ecf0f1"},
        filter_action="native",
        sort_action="native",
    )

    return html.Div(
        [
            html.H3("Audit Log"),
            html.P(
                "Onwijzigbaar logboek van alle boekingshandelingen — vereist voor "
                "de Nederlandse fiscale bewaarplicht (7 jaar). Automatische dagelijkse backups "
                "worden bewaard in data/backups/.",
                className="text-muted",
            ),
            html.Hr(),
            table,
        ]
    )


# ========================================================================
# PAGE: Settings
# ========================================================================

def settings_page(data):
    company = data.get("company", {})
    return html.Div(
        [
            html.H3("Bedrijfsinstellingen"),
            html.Hr(),
            dbc.Card(
                dbc.CardBody(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Bedrijfsnaam"),
                                        dbc.Input(
                                            id="set-name",
                                            value=company.get("name", ""),
                                        ),
                                    ],
                                    width=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("KVK nummer"),
                                        dbc.Input(
                                            id="set-kvk",
                                            value=company.get("kvk", ""),
                                        ),
                                    ],
                                    width=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("BTW-identificatienummer"),
                                        dbc.Input(
                                            id="set-btw-id",
                                            value=company.get("btw_id", ""),
                                            placeholder="NL000000000B01",
                                        ),
                                    ],
                                    width=4,
                                ),
                            ],
                            className="mb-3",
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Adres"),
                                        dbc.Input(
                                            id="set-address",
                                            value=company.get("address", ""),
                                        ),
                                    ],
                                    width=6,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("IBAN"),
                                        dbc.Input(
                                            id="set-iban",
                                            value=company.get("bank_iban", ""),
                                            placeholder="NL00BANK0000000000",
                                        ),
                                    ],
                                    width=6,
                                ),
                            ],
                            className="mb-3",
                        ),
                        dbc.Button(
                            "Opslaan",
                            id="set-save-btn",
                            color="primary",
                        ),
                        html.Div(id="set-feedback", className="mt-2"),
                    ]
                )
            ),
        ]
    )


# ========================================================================
# CALLBACKS
# ========================================================================

# --- Page routing ---
@callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(pathname):
    data = load_data()
    if pathname == "/transactions":
        return transactions_page(data)
    elif pathname == "/btw":
        return btw_page(data)
    elif pathname == "/invoices":
        return invoices_page(data)
    elif pathname == "/import-export":
        return import_export_page(data)
    elif pathname == "/audit":
        return audit_page(data)
    elif pathname == "/settings":
        return settings_page(data)
    return dashboard_page(data)


# --- Dynamic category options based on type ---
@callback(
    Output("txn-category", "options"),
    Output("txn-category", "value"),
    Input("txn-type", "value"),
)
def update_categories(txn_type):
    if txn_type == "income":
        opts = [{"label": c, "value": c} for c in CATEGORIES_INCOME]
        return opts, CATEGORIES_INCOME[0]
    opts = [{"label": c, "value": c} for c in CATEGORIES_EXPENSE]
    return opts, CATEGORIES_EXPENSE[0]


# --- Add transaction ---
@callback(
    Output("txn-feedback", "children"),
    Output("url", "pathname", allow_duplicate=True),
    Input("txn-add-btn", "n_clicks"),
    State("txn-date", "date"),
    State("txn-type", "value"),
    State("txn-amount", "value"),
    State("txn-btw", "value"),
    State("txn-category", "value"),
    State("txn-desc", "value"),
    prevent_initial_call=True,
)
def add_transaction(n_clicks, txn_date, txn_type, amount, btw, category, desc):
    if not n_clicks:
        return "", dash.no_update
    if not amount or float(amount) <= 0:
        return dbc.Alert("Vul een geldig bedrag in.", color="warning"), dash.no_update

    data = load_data()
    txn = {
        "id": str(uuid.uuid4())[:8],
        "date": txn_date,
        "type": txn_type,
        "amount": round(float(amount), 2),
        "btw_rate": btw,
        "category": category,
        "description": desc or "",
    }
    data["transactions"].append(txn)
    add_audit_entry(data, "ADD_TRANSACTION", f"{txn['id']}: {txn_type} €{amount} ({btw}) — {desc or 'no description'}")
    save_data(data)
    return dbc.Alert("Transactie toegevoegd!", color="success", duration=2000), "/transactions"


# --- Delete selected transactions ---
@callback(
    Output("txn-feedback", "children", allow_duplicate=True),
    Output("url", "pathname", allow_duplicate=True),
    Input("txn-delete-btn", "n_clicks"),
    State("txn-table", "selected_rows"),
    State("txn-table", "data"),
    prevent_initial_call=True,
)
def delete_transactions(n_clicks, selected_rows, table_data):
    if not n_clicks or not selected_rows:
        return dbc.Alert("Selecteer transacties om te verwijderen.", color="warning"), dash.no_update

    ids_to_delete = {table_data[i]["id"] for i in selected_rows}
    data = load_data()
    # Log deleted transactions before removing (audit trail for Belastingdienst)
    deleted_txns = [t for t in data["transactions"] if t.get("id") in ids_to_delete]
    for dt in deleted_txns:
        add_audit_entry(data, "DELETE_TRANSACTION", f"{dt['id']}: {dt['type']} €{dt['amount']} on {dt['date']} — {dt.get('description', '')}")
    data["transactions"] = [
        t for t in data["transactions"] if t.get("id") not in ids_to_delete
    ]
    save_data(data)
    return (
        dbc.Alert(f"{len(ids_to_delete)} transactie(s) verwijderd.", color="info", duration=2000),
        "/transactions",
    )


# --- Save company settings ---
@callback(
    Output("set-feedback", "children"),
    Input("set-save-btn", "n_clicks"),
    State("set-name", "value"),
    State("set-kvk", "value"),
    State("set-btw-id", "value"),
    State("set-address", "value"),
    State("set-iban", "value"),
    prevent_initial_call=True,
)
def save_settings(n_clicks, name, kvk, btw_id, address, iban):
    if not n_clicks:
        return ""
    # Validate formats
    if btw_id and not validate_btw_id(btw_id):
        return dbc.Alert(
            "Ongeldig BTW-ID formaat. Verwacht: NL000000000B01",
            color="danger",
        )
    if iban and not validate_iban(iban):
        return dbc.Alert(
            "Ongeldig IBAN formaat. Verwacht: NL00BANK0000000000",
            color="danger",
        )
    data = load_data()
    data["company"] = {
        "name": name or "",
        "kvk": kvk or "",
        "btw_id": btw_id or "",
        "address": address or "",
        "bank_iban": iban or "",
    }
    add_audit_entry(data, "UPDATE_SETTINGS", f"Company: {name}")
    save_data(data)
    return dbc.Alert("Instellingen opgeslagen!", color="success", duration=2000)


# --- Create invoice ---
@callback(
    Output("inv-feedback", "children"),
    Output("url", "pathname", allow_duplicate=True),
    Input("inv-create-btn", "n_clicks"),
    State("inv-client", "value"),
    State("inv-client-addr", "value"),
    State("inv-desc", "value"),
    State("inv-amount", "value"),
    State("inv-btw", "value"),
    State("inv-date", "date"),
    State("inv-terms", "value"),
    prevent_initial_call=True,
)
def create_invoice(n_clicks, client, client_addr, desc, amount, btw, inv_date, terms):
    if not n_clicks:
        return "", dash.no_update
    if not client or not amount or float(amount) <= 0:
        return dbc.Alert("Vul klant en bedrag in.", color="warning"), dash.no_update

    data = load_data()
    inv_count = len(data.get("invoices", [])) + 1
    year = datetime.now().year
    inv_number = f"INV-{year}-{inv_count:04d}"

    btw_val = BTW_RATES.get(btw, 0.21)
    amount_excl = round(float(amount), 2)
    amount_incl = round(amount_excl * (1 + btw_val), 2)

    invoice = {
        "id": str(uuid.uuid4())[:8],
        "number": inv_number,
        "date": inv_date,
        "client": client,
        "client_address": client_addr or "",
        "description": desc or "",
        "amount_excl": amount_excl,
        "btw_rate": btw,
        "amount_incl": amount_incl,
        "terms_days": int(terms) if terms else 30,
    }
    data.setdefault("invoices", []).append(invoice)

    # Also add as income transaction
    txn = {
        "id": str(uuid.uuid4())[:8],
        "date": inv_date,
        "type": "income",
        "amount": amount_incl,
        "btw_rate": btw,
        "category": "Omzet diensten (services)",
        "description": f"Factuur {inv_number} — {client}",
    }
    data["transactions"].append(txn)
    add_audit_entry(data, "CREATE_INVOICE", f"{inv_number}: {client} — €{amount_excl} excl. BTW ({btw})")
    save_data(data)

    return (
        dbc.Alert(f"Factuur {inv_number} aangemaakt!", color="success", duration=3000),
        "/invoices",
    )


# --- CSV Import ---
@callback(
    Output("import-feedback", "children"),
    Output("url", "pathname", allow_duplicate=True),
    Input("csv-upload", "contents"),
    State("csv-upload", "filename"),
    prevent_initial_call=True,
)
def import_csv(contents, filename):
    if contents is None:
        return "", dash.no_update

    import base64

    content_type, content_string = contents.split(",")
    decoded = base64.b64decode(content_string).decode("utf-8")

    try:
        df = pd.read_csv(StringIO(decoded))
    except Exception as e:
        return dbc.Alert(f"Fout bij lezen CSV: {e}", color="danger"), dash.no_update

    # Try to find columns
    col_map = {}
    for col in df.columns:
        cl = col.lower().strip()
        if cl in ("date", "datum", "boekdatum", "transactiedatum"):
            col_map["date"] = col
        elif cl in ("amount", "bedrag", "mutatie", "transactiebedrag"):
            col_map["amount"] = col
        elif cl in ("description", "omschrijving", "naam / omschrijving", "mededelingen"):
            col_map["description"] = col

    if "date" not in col_map or "amount" not in col_map:
        return (
            dbc.Alert(
                "CSV moet minimaal 'date'/'datum' en 'amount'/'bedrag' kolommen bevatten.",
                color="danger",
            ),
            dash.no_update,
        )

    data = load_data()
    count = 0
    for _, row in df.iterrows():
        try:
            amount = float(str(row[col_map["amount"]]).replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            continue

        txn_type = "income" if amount >= 0 else "expense"
        desc = str(row.get(col_map.get("description", ""), "")) if "description" in col_map else ""

        txn = {
            "id": str(uuid.uuid4())[:8],
            "date": str(row[col_map["date"]]),
            "type": txn_type,
            "amount": round(abs(amount), 2),
            "btw_rate": "21%",
            "category": CATEGORIES_INCOME[0] if txn_type == "income" else CATEGORIES_EXPENSE[0],
            "description": desc,
        }
        data["transactions"].append(txn)
        count += 1

    save_data(data)
    return (
        dbc.Alert(f"{count} transacties geïmporteerd uit {filename}!", color="success"),
        "/import-export",
    )


# --- Export ---
@callback(
    Output("download-export", "data"),
    Input("export-excel-btn", "n_clicks"),
    Input("export-csv-btn", "n_clicks"),
    prevent_initial_call=True,
)
def export_data(n_excel, n_csv):
    data = load_data()
    txns = data.get("transactions", [])
    if not txns:
        return None

    df = pd.DataFrame(txns)
    df["btw_rate_val"] = df["btw_rate"].map(BTW_RATES).fillna(0)
    df["amount_excl"] = df.apply(
        lambda r: r["amount"] / (1 + r["btw_rate_val"]) if r["btw_rate_val"] > 0 else r["amount"],
        axis=1,
    ).round(2)
    df["btw_amount"] = (df["amount"] - df["amount_excl"]).round(2)
    df = df.rename(columns={
        "date": "Datum",
        "type": "Type",
        "amount": "Bedrag incl. BTW",
        "amount_excl": "Bedrag excl. BTW",
        "btw_rate": "BTW tarief",
        "btw_amount": "BTW bedrag",
        "category": "Categorie",
        "description": "Omschrijving",
    })
    export_cols = [
        "Datum", "Type", "Bedrag incl. BTW", "Bedrag excl. BTW",
        "BTW tarief", "BTW bedrag", "Categorie", "Omschrijving",
    ]
    df = df[export_cols]

    triggered = ctx.triggered_id
    if triggered == "export-excel-btn":
        return dcc.send_data_frame(df.to_excel, "boekhouding_export.xlsx", index=False)
    return dcc.send_data_frame(df.to_csv, "boekhouding_export.csv", index=False)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
