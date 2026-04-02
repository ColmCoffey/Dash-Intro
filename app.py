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
    "company": {
        "name": "",
        "kvk": "",
        "btw_id": "",
        "address": "",
        "bank_iban": "",
    },
}

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
            return json.load(f)
    return json.loads(json.dumps(EMPTY_DATA))


def save_data(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


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
        ]
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
    df["amount_excl"] = df["amount"] / (1 + df["btw_rate_val"])
    df["btw_amount"] = df["amount"] - df["amount_excl"]

    # Handle 0% rate division
    mask_zero = df["btw_rate_val"] == 0
    df.loc[mask_zero, "amount_excl"] = df.loc[mask_zero, "amount"]
    df.loc[mask_zero, "btw_amount"] = 0

    quarters = sorted(df["quarter"].unique(), reverse=True)
    cards = []

    for q in quarters:
        dq = df[df["quarter"] == q]
        income_excl = dq.loc[dq["type"] == "income", "amount_excl"].sum()
        expense_excl = dq.loc[dq["type"] == "expense", "amount_excl"].sum()
        btw_collected = dq.loc[dq["type"] == "income", "btw_amount"].sum()
        btw_deducted = dq.loc[dq["type"] == "expense", "btw_amount"].sum()
        btw_due = btw_collected - btw_deducted

        # Breakdown by rate for income
        rate_rows = []
        for rate_label, rate_val in BTW_RATES.items():
            mask = (dq["type"] == "income") & (dq["btw_rate"] == rate_label)
            if mask.any():
                rate_rows.append(
                    html.Tr(
                        [
                            html.Td(rate_label),
                            html.Td(f"€ {dq.loc[mask, 'amount_excl'].sum():,.2f}"),
                            html.Td(f"€ {dq.loc[mask, 'btw_amount'].sum():,.2f}"),
                        ]
                    )
                )

        card = dbc.Card(
            dbc.CardBody(
                [
                    html.H5(f"Kwartaal {q}"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.P(f"Omzet excl. BTW: € {income_excl:,.2f}"),
                                    html.P(f"Kosten excl. BTW: € {expense_excl:,.2f}"),
                                ],
                                width=4,
                            ),
                            dbc.Col(
                                [
                                    html.P(f"BTW ontvangen: € {btw_collected:,.2f}"),
                                    html.P(f"BTW betaald (voorbelasting): € {btw_deducted:,.2f}"),
                                ],
                                width=4,
                            ),
                            dbc.Col(
                                [
                                    html.H5(
                                        f"Te betalen: € {btw_due:,.2f}",
                                        className="text-danger" if btw_due > 0 else "text-success",
                                    ),
                                    html.Small(
                                        "Terug te ontvangen" if btw_due < 0 else "Af te dragen"
                                    ),
                                ],
                                width=4,
                            ),
                        ]
                    ),
                    html.Details(
                        [
                            html.Summary("BTW specificatie omzet"),
                            dbc.Table(
                                [
                                    html.Thead(
                                        html.Tr(
                                            [
                                                html.Th("Tarief"),
                                                html.Th("Omzet excl."),
                                                html.Th("BTW"),
                                            ]
                                        )
                                    ),
                                    html.Tbody(rate_rows),
                                ],
                                bordered=True,
                                size="sm",
                                className="mt-2",
                            ),
                        ]
                    ),
                ]
            ),
            className="mb-3",
        )
        cards.append(card)

    return html.Div(
        [
            html.H3("BTW Aangifte (per kwartaal)"),
            html.P(
                "Gebruik deze overzichten bij het invullen van je BTW aangifte op MijnBelastingdienst.",
                className="text-muted",
            ),
            html.Hr(),
        ]
        + cards
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
    data = load_data()
    data["company"] = {
        "name": name or "",
        "kvk": kvk or "",
        "btw_id": btw_id or "",
        "address": address or "",
        "bank_iban": iban or "",
    }
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
