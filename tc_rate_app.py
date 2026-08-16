"""
TC-rate calculator for a live fish carrier (brønnbåt) — Streamlit app.

Tabs:
    1. Vessel TC-rate    — required EBITDA (capex x yield) + vessel opex
    2. Lease spread       — leased equipment funded via bank debt, leased
                             out to the customer at a higher required return
    3. Combined TC-rate   — vessel TC-rate + the customer-facing lease
                             payment, on daily / monthly / annual basis

Run locally with:
    pip install streamlit pandas
    streamlit run tc_rate_app.py
"""

import json
import os
import re
from io import BytesIO

import altair as alt
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="TC-rate calculator — Live Fish Carrier",
    page_icon="⚓",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Auto-load a saved configuration, if one has been committed to the repo.
# This is what makes "your well-qualified inputs" the default everyone sees —
# see the "Configuration" section in the sidebar to save/load one.
# ---------------------------------------------------------------------------

CONFIG_FILE = "default_config.json"
CONFIG_EXCLUDE_KEYS = {"unlocked", "unlock_password_input", "_config_loaded", "_config_status", "config_uploader"}


def _is_excluded_key(key: str) -> bool:
    """Buttons (like the opex/service/price/voyage-cost '✕' remove buttons)
    can't have their session_state pre-set — Streamlit raises a
    StreamlitValueAssignmentNotAllowedError if you try, since buttons are
    trigger-only widgets. File uploader keys shouldn't be restored either.
    Match on "_remove_" anywhere in the key (not just a "remove_" prefix)
    so this catches every remove-button naming pattern used across the
    app (remove_{i}, service_remove_{i}, price_remove_{i}, spot_remove_{i},
    and any future ones), rather than needing a new prefix added here
    every time a new item list with its own remove button is built."""
    if key in CONFIG_EXCLUDE_KEYS:
        return True
    if key.startswith("remove_") or "_remove_" in key:
        return True
    return False


def _apply_config(config_dict):
    for k, v in config_dict.items():
        if _is_excluded_key(k):
            continue
        try:
            st.session_state[k] = v
        except Exception:
            pass  # skip any single key Streamlit won't allow, rather than crash the whole app


# Defensive cleanup, run every single pass (cheap — just a key filter):
# strip any session_state entries for button-only keys (remove_*,
# *_remove_*) that may have been set incorrectly by an older app version's
# config file, or any other means. Buttons are trigger-only widgets and
# can never legitimately hold a stored value; setting one raises
# StreamlitValueAssignmentNotAllowedError — but only when the button
# widget itself is created, not at assignment time, so _apply_config's
# own try/except above can't catch it. This runs unconditionally so any
# already-poisoned session (from before _is_excluded_key was widened to
# also exclude these keys) gets cleaned up immediately, without needing a
# brand-new session.
for _k in [k for k in list(st.session_state.keys()) if k.startswith("remove_") or "_remove_" in k]:
    del st.session_state[_k]

_config_status = None
if "_config_loaded" not in st.session_state:
    st.session_state["_config_loaded"] = True
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                _apply_config(json.load(f))
            _config_status = f"✅ Loaded {CONFIG_FILE} ({os.path.getsize(CONFIG_FILE)} bytes) from {os.path.abspath(CONFIG_FILE)}"
        except Exception as e:
            _config_status = f"❌ Found {CONFIG_FILE} but failed to load it: {e}"
    else:
        _config_status = f"⚠️ {CONFIG_FILE} not found at {os.path.abspath(CONFIG_FILE)} (cwd: {os.getcwd()})"
    st.session_state["_config_status"] = _config_status

st.title("⚓ TC-rate calculator — live fish carrier")

st.caption(
    "Vessel TC-rate, leased equipment financing, and the combined total — "
    "all on a daily / monthly / annual basis."
)

currency = st.text_input("Currency", value="NOK", key="currency_input").strip() or "NOK"

# ---------------------------------------------------------------------------
# Lock / unlock — colleagues get a read-only view by default; a password
# unlocks editing. Change UNLOCK_PASSWORD to whatever you want to use.
# ---------------------------------------------------------------------------

UNLOCK_PASSWORD = "trident2026"  # <-- change this to your own password

if "unlocked" not in st.session_state:
    st.session_state.unlocked = False


def _request_rerun():
    """Defer a rerun to the very end of the script, after every tab's
    widgets have had a chance to render normally in this pass. Calling
    st.rerun() directly mid-script cuts the current pass short before
    later tabs' widgets ever run — Streamlit can then treat those
    never-reached widgets as 'not seen this run' and wipe their saved
    values (the exact mechanism stateful_number_input's shadow-key
    protection works around for individual widgets). Deferring the
    actual rerun avoids the whole class of bug at its root, for every
    widget, without needing per-widget protection."""
    st.session_state["_pending_rerun"] = True


with st.sidebar:
    if st.session_state.get("spot_market_enabled", False):
        st.warning(
            "⚠️ **Spot market is ON.** The Financial Statements, Sources & "
            "Uses, and every downstream tab are running on spot-market "
            "revenue (Spot market tab), not the TC-rate. Turn it off there "
            "if that's not intended."
        )

with st.sidebar:
    st.subheader("🔄 Refresh")
    if st.button("Refresh calculations"):
        _request_rerun()
    st.caption(
        "A few figures (e.g. Tab 1's Sources & Uses guideline) are computed "
        "one script pass behind live edits elsewhere. If a number looks "
        "stale after changing inputs, click here instead of switching tabs."
    )
    if st.button("⚠️ Reset to script defaults (clears everything)"):
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        _request_rerun()
    st.caption(
        "Wipes all inputs — including anything typed in this session — "
        "and rebuilds the app entirely from the script's own hardcoded "
        "defaults, bypassing any leftover or corrupted session state. Use "
        "this if numbers look wrong in a way Refresh doesn't fix (e.g. "
        "fields showing their bare minimum value instead of the intended "
        "default)."
    )
    st.divider()
    st.subheader("🔒 Edit access")
    if st.session_state.unlocked:
        st.success("Unlocked — inputs are editable.")
        if st.button("Lock again"):
            st.session_state.unlocked = False
            _request_rerun()
    else:
        st.caption("All inputs are locked (view-only). Enter the password to edit.")
        pwd = st.text_input("Password", type="password", key="unlock_password_input")
        if st.button("Unlock"):
            if pwd == UNLOCK_PASSWORD:
                st.session_state.unlocked = True
                _request_rerun()
            else:
                st.error("Incorrect password.")

locked = not st.session_state.unlocked

with st.sidebar:
    if not locked:
        st.divider()
        st.subheader("💾 Configuration")
        st.caption(
            "Save your current inputs as the default everyone sees "
            "(including in locked view-only mode)."
        )

        config_to_save = {k: v for k, v in dict(st.session_state).items() if not _is_excluded_key(k)}
        config_json = json.dumps(config_to_save, default=str, indent=2)
        st.download_button(
            "Save current inputs as default",
            data=config_json,
            file_name=CONFIG_FILE,
            mime="application/json",
        )
        st.caption(
            f"Downloads **{CONFIG_FILE}** — commit it to the same GitHub repo "
            f"as `tc_rate_app.py` (same folder) and the app will auto-load it "
            f"for every visitor from then on."
        )

        uploaded_config = st.file_uploader("Or load a saved configuration", type="json", key="config_uploader")
        if uploaded_config is not None:
            try:
                loaded = json.load(uploaded_config)
                _apply_config(loaded)
                st.success("Configuration loaded.")
                _request_rerun()
            except Exception as e:
                st.error(f"Couldn't load that file: {e}")

if locked:
    st.info(
        "🔒 **View-only mode.** All figures below reflect the current saved "
        "assumptions. To change any input, enter the password in the sidebar."
    )

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def format_nok(n: float) -> str:
    """1234567 -> '1 234 567'"""
    return f"{n:,.0f}".replace(",", " ")


def parse_nok(s: str) -> float:
    """'1 234 567' or '1234567' -> 1234567.0"""
    cleaned = re.sub(r"[^\d.\-]", "", s or "")
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def nok_input(label: str, state_key: str, default: float, key: str, disabled: bool = False) -> float:
    """A text input that displays with thousand separators and re-formats
    itself every time the value changes (on Enter / click-away), rather
    than freezing on whatever was last typed."""
    if state_key not in st.session_state:
        st.session_state[state_key] = default
    if key not in st.session_state:
        st.session_state[key] = format_nok(st.session_state[state_key])

    def _on_change():
        value = parse_nok(st.session_state[key])
        st.session_state[state_key] = value
        st.session_state[key] = format_nok(value)

    st.text_input(label, key=key, on_change=_on_change, disabled=disabled)
    return st.session_state[state_key]


def stateful_number_input(label, key=None, value=0.0, **kwargs):
    """Drop-in replacement for st.number_input, protected against Streamlit
    wiping the widget's saved value when it briefly isn't rendered (e.g. the
    lock/unlock buttons call st.rerun() from partway through the script,
    before Tab 1's widgets run — Streamlit treats any widget key that wasn't
    freshly re-registered as 'gone' and clears it). A shadow key that's never
    itself a widget's key= holds the true value and survives that cleanup,
    the same protection nok_input already has via its separate state_key."""
    shadow_key = f"__shadow_{key}"
    if shadow_key not in st.session_state:
        st.session_state[shadow_key] = value
    if key not in st.session_state:
        st.session_state[key] = st.session_state[shadow_key]
    result = st.number_input(label, key=key, **kwargs)
    st.session_state[shadow_key] = result
    return result


def stateful_toggle(label, key=None, value=False, **kwargs):
    """Same shadow-key protection as stateful_number_input, for st.toggle."""
    shadow_key = f"__shadow_{key}"
    if shadow_key not in st.session_state:
        st.session_state[shadow_key] = value
    if key not in st.session_state:
        st.session_state[key] = st.session_state[shadow_key]
    result = st.toggle(label, key=key, **kwargs)
    st.session_state[shadow_key] = result
    return result


def fmt(n):
    return format_nok(n)  # currency shown once, via the field at the top — not repeated per number


def show_table(df: pd.DataFrame, label_col: str = None, **kwargs):
    """Display a numeric dataframe with right-aligned, thousands-separated
    columns (Streamlit only right-aligns numeric dtype columns — pre-formatted
    strings stay left-aligned regardless of styling, hence keeping values raw
    here and letting column_config handle the display format).
    If label_col is given, that column becomes the index (kept as text)."""
    display_df = df.set_index(label_col) if label_col else df
    config = {col: st.column_config.NumberColumn(format="%,d") for col in display_df.columns}
    st.dataframe(display_df, column_config=config, **kwargs)


NOK_AXIS_FORMAT = ",.0f"  # Vega-Lite doesn't support space thousands; comma is the closest built-in


def formatted_line_chart(df: pd.DataFrame, x_col: str, y_cols: list, height: int = 300):
    """Line chart with comma-separated axis labels and tooltips (Streamlit's
    built-in st.line_chart shows raw unformatted numbers on hover)."""
    melted = df.reset_index().melt(id_vars=[x_col], value_vars=y_cols, var_name="Series", value_name="Value")
    chart = (
        alt.Chart(melted)
        .mark_line()
        .encode(
            x=alt.X(f"{x_col}:Q", title=x_col),
            y=alt.Y("Value:Q", title=None, axis=alt.Axis(format=NOK_AXIS_FORMAT)),
            color=alt.Color("Series:N", title=None),
            tooltip=[
                alt.Tooltip(f"{x_col}:Q", title=x_col),
                alt.Tooltip("Series:N", title="Series"),
                alt.Tooltip("Value:Q", title="Value", format=NOK_AXIS_FORMAT),
            ],
        )
        .properties(height=height)
        .interactive()
    )
    st.altair_chart(chart, use_container_width=True)


def formatted_bar_chart(df: pd.DataFrame, category_col: str, value_col: str, height: int = 300):
    """Horizontal bar chart with comma-separated axis labels, tooltips, and
    a value label printed on each bar (space-thousands, matching the rest
    of the app's number formatting)."""
    plot_df = df.reset_index()
    plot_df["_label"] = plot_df[value_col].apply(format_nok)

    base = alt.Chart(plot_df).encode(
        y=alt.Y(f"{category_col}:N", title=None, sort=None),
        x=alt.X(f"{value_col}:Q", title=None, axis=alt.Axis(format=NOK_AXIS_FORMAT)),
    )
    bars = base.mark_bar().encode(
        tooltip=[
            alt.Tooltip(f"{category_col}:N", title=category_col),
            alt.Tooltip(f"{value_col}:Q", title=value_col, format=NOK_AXIS_FORMAT),
        ],
    )
    labels = base.mark_text(align="left", dx=5, color="black").encode(text="_label:N")
    chart = (bars + labels).properties(height=height)
    st.altair_chart(chart, use_container_width=True)


def annuity_monthly_payment(principal_nok: float, annual_rate_pct: float, num_months: int) -> float:
    """Level monthly annuity payment. Nominal monthly rate = annual rate / 12."""
    if num_months <= 0:
        return 0.0
    r = (annual_rate_pct / 100) / 12
    if r == 0:
        return principal_nok / num_months
    return principal_nok * r / (1 - (1 + r) ** -num_months)


def amortization_balances(principal_nok: float, annual_rate_pct: float, num_months: int, payment_basis_months: int = None) -> list:
    """Closing balance for each month (used to chart the paydown).

    If payment_basis_months is given and differs from num_months, the level
    payment is computed over the LONGER payback basis, but the schedule
    only runs for num_months — leaving a genuine, non-zero residual
    balance at the end (e.g. a lease rental priced on a 7-year payback but
    only actually collected over a 5-year customer contract)."""
    basis_months = payment_basis_months if payment_basis_months else num_months
    r = (annual_rate_pct / 100) / 12
    payment = annuity_monthly_payment(principal_nok, annual_rate_pct, basis_months)
    balance = principal_nok
    balances = []
    for month in range(1, num_months + 1):
        interest = balance * r
        principal_paid = payment - interest
        balance = balance - principal_paid
        if month == num_months and basis_months == num_months:
            balance = 0.0  # only force to zero when the schedule fully amortizes within num_months
        balances.append(balance)
    return balances


def amortization_schedule_full(principal_nok: float, annual_rate_pct: float, num_months: int, payment_basis_months: int = None) -> list:
    """Month-by-month: opening balance, payment, finance cost (interest),
    amortization (principal), closing balance.

    Same payment_basis_months mechanic as amortization_balances() above —
    see that docstring."""
    basis_months = payment_basis_months if payment_basis_months else num_months
    r = (annual_rate_pct / 100) / 12
    payment = annuity_monthly_payment(principal_nok, annual_rate_pct, basis_months)
    balance = principal_nok
    rows = []
    for month in range(1, num_months + 1):
        interest = balance * r
        principal_paid = payment - interest
        closing = balance - principal_paid
        if month == num_months and basis_months == num_months:
            closing = 0.0  # only force to zero when the schedule fully amortizes within num_months
        rows.append({
            "Month": month,
            "Opening balance": balance,
            "Finance cost": interest,
            "Amortization": principal_paid,
            "Payment": payment,
            "Closing balance": closing,
        })
        balance = closing
    return rows


# ---------------------------------------------------------------------------
# Session state — opex line items (persist across reruns)
# ---------------------------------------------------------------------------

if "opex_items" not in st.session_state:
    st.session_state.opex_items = [
        {"name": "Crewing", "value_nok": 21_500_000.0},
        {"name": "Other vessel opex", "value_nok": 6_500_000.0},
    ]


def add_opex_item():
    st.session_state.opex_items.append({"name": "New item", "value_nok": 0.0})


def remove_opex_item(index):
    st.session_state.opex_items.pop(index)


def _on_opex_value_change(index):
    raw = st.session_state[f"value_{index}"]
    value = parse_nok(raw)
    st.session_state.opex_items[index]["value_nok"] = value
    st.session_state[f"value_{index}"] = format_nok(value)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_vessel, tab_spot, tab_lease, tab_combined, tab_financials, tab_investment, tab_summary = st.tabs(
    ["Vessel TC-rate", "Spot market", "Lease spread", "Combined TC-rate", "Financial Statements", "Investment Analysis", "Summary"]
)

# ===========================================================================
# TAB 1 — Vessel TC-rate
# ===========================================================================
with tab_vessel:
    left, right = st.columns([1, 1.4], gap="large")

    with left:
        st.subheader("Capital & return")
        capex_nok = nok_input("Capex (NOK)", "capex_nok", 800_000_000.0, key="capex_input", disabled=locked)
        ebitda_yield_pct = stateful_number_input(
            "EBITDA-yield (%)", min_value=0.0, value=12.0, step=0.1, key="ebitda_yield", disabled=locked
        )
        operating_days = stateful_number_input(
            "Operating days / year", min_value=1, value=365, step=1, key="operating_days", disabled=locked
        )

        st.subheader("Vessel opex (annual, NOK)")
        for i, item in enumerate(st.session_state.opex_items):
            c1, c2, c3 = st.columns([2.2, 1.6, 0.4])
            with c1:
                item["name"] = st.text_input(
                    "Name", value=item["name"], key=f"name_{i}", label_visibility="collapsed",
                    disabled=locked
                )
            with c2:
                if f"value_{i}" not in st.session_state:
                    st.session_state[f"value_{i}"] = format_nok(item["value_nok"])
                st.text_input(
                    "Value (NOK)",
                    key=f"value_{i}",
                    label_visibility="collapsed",
                    on_change=_on_opex_value_change,
                    args=(i,),
                    disabled=locked,
                )
            with c3:
                st.button("✕", key=f"remove_{i}", on_click=remove_opex_item, args=(i,), disabled=locked)

        st.button("+ Add opex line item", on_click=add_opex_item, disabled=locked)

        opex_total = sum(item["value_nok"] for item in st.session_state.opex_items)
        st.markdown(f"**Total vessel opex:** {format_nok(opex_total)} NOK")

        st.subheader("Depreciation & maintenance")
        depreciation_rate_pct = stateful_number_input(
            "Vessel depreciation rate, annual (%)", min_value=0.0, value=2.5, step=0.1,
            key="depreciation_rate", disabled=locked
        )
        st.caption(
            "Straight-line, % of original vessel capex per year. Leased "
            "equipment (Tab 2) is depreciated separately, straight-line over "
            "the same number of months as its financing term — see the "
            "Lease spread tab."
        )
        annual_maintenance_capex_nok = nok_input(
            "Annual maintenance capex (NOK)", "maintenance_capex_nok", 4_300_000.0,
            key="maintenance_capex_input", disabled=locked
        )

    # --- calculations ---
    required_ebitda_annual = capex_nok * (ebitda_yield_pct / 100)
    vessel_tc_annual = required_ebitda_annual + opex_total
    vessel_tc_daily = vessel_tc_annual / operating_days if operating_days else 0
    vessel_tc_monthly = vessel_tc_annual / 12

    with right:
        header_col, req_col = st.columns([2, 1.3])
        with header_col:
            st.subheader("Rate build-up")
        with req_col:
            st.markdown(
                f"""
                <div style="text-align:right; padding-top:6px;">
                    <span style="font-size:12px; color:#888; text-transform:uppercase; letter-spacing:0.05em;">
                        TC-requirement, annual
                    </span><br>
                    <span style="font-size:22px; font-weight:700; color:#1a1a1a;">
                        {fmt(vessel_tc_annual)}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )

        chart_rows = [{"Component": "Required EBITDA", "NOK (annual)": required_ebitda_annual}]
        for item in st.session_state.opex_items:
            if item["value_nok"] > 0:
                chart_rows.append({"Component": item["name"], "NOK (annual)": item["value_nok"]})
        chart_df = pd.DataFrame(chart_rows)
        formatted_bar_chart(chart_df, "Component", "NOK (annual)")

        st.subheader("TC-rate")
        results_df = pd.DataFrame(
            [
                {
                    "Component": "Required EBITDA",
                    "Daily": required_ebitda_annual / operating_days,
                    "Monthly": required_ebitda_annual / 12,
                    "Annual": required_ebitda_annual,
                },
                {
                    "Component": "Vessel opex",
                    "Daily": opex_total / operating_days,
                    "Monthly": opex_total / 12,
                    "Annual": opex_total,
                },
                {
                    "Component": "TC-rate",
                    "Daily": vessel_tc_daily,
                    "Monthly": vessel_tc_monthly,
                    "Annual": vessel_tc_annual,
                },
            ]
        )
        show_table(results_df, "Component", width="stretch")

        m1, m2, m3 = st.columns(3)
        m1.metric("TC-rate, daily", fmt(vessel_tc_daily))
        m2.metric("TC-rate, monthly", fmt(vessel_tc_monthly))
        m3.metric("TC-rate, annual", fmt(vessel_tc_annual))

        st.caption(
            "**Scope:** this TC-rate covers capital return and vessel opex only. "
            "Fuel, lubrication oil, port fees, and other spot expenses are excluded "
            "and typically sit for charterer's account."
        )

    # =======================================================================
    # Debt financing (vessel)
    # =======================================================================
    st.divider()
    st.subheader("Debt financing")
    st.caption(
        "Debt sized off Year 1 EBITDA, at an implied LTV against capex. "
        "Finance cost = swap rate + credit spread, charged monthly on the "
        "outstanding balance; principal is repaid quarterly (straight-line), "
        "not monthly — the typical structure for shipping debt."
    )

    debt_left, debt_right = st.columns([1, 1.4], gap="large")

    with debt_left:
        debt_multiple = stateful_number_input(
            "Debt multiple (x Year 1 EBITDA)", min_value=0.0, value=6.0, step=0.5,
            key="debt_multiple", disabled=locked
        )
        amortization_years = stateful_number_input(
            "Amortization profile (years)", min_value=1, max_value=30, value=12, step=1,
            key="amortization_years", disabled=locked
        )
        swap_rate_pct = stateful_number_input(
            "Swap rate, annual (%)", min_value=0.0, value=4.0, step=0.1, key="swap_rate", disabled=locked
        )
        credit_spread_pct = stateful_number_input(
            "Credit spread, annual (%)", min_value=0.0, value=3.5, step=0.1, key="credit_spread", disabled=locked
        )

        debt_nok = debt_multiple * required_ebitda_annual
        implied_ltv_pct = (debt_nok / capex_nok * 100) if capex_nok else 0.0
        implied_equity_nok = capex_nok - debt_nok
        finance_cost_rate_pct = swap_rate_pct + credit_spread_pct

        st.markdown(f"**Debt:** {format_nok(debt_nok)} NOK")
        st.markdown(f"**Implied LTV:** {implied_ltv_pct:,.1f}%".replace(",", " "))
        st.markdown(f"**Implied equity (capex − debt):** {format_nok(implied_equity_nok)} NOK")
        st.caption(
            "This covers the vessel purchase only. For an additional "
            "operational cash buffer — sized off the worst point in the "
            "monthly cash flow — see the Financial Statements tab."
        )

        st.markdown("**Finance cost summary**")
        finance_cost_summary_df = pd.DataFrame(
            [
                {"Component": "Swap rate", "Rate (%)": swap_rate_pct},
                {"Component": "Credit spread", "Rate (%)": credit_spread_pct},
                {"Component": "Total finance cost", "Rate (%)": finance_cost_rate_pct},
            ]
        )
        st.dataframe(
            finance_cost_summary_df.set_index("Component"),
            column_config={"Rate (%)": st.column_config.NumberColumn(format="%.2f")},
            width="stretch",
        )

    # --- build monthly schedule: interest monthly, principal quarterly ---
    amortization_months = int(amortization_years) * 12
    quarterly_amortization_nok = debt_nok / (int(amortization_years) * 4) if amortization_years else 0.0
    monthly_rate = (finance_cost_rate_pct / 100) / 12

    debt_schedule = []
    balance = debt_nok
    for month in range(1, amortization_months + 1):
        opening_balance = balance
        monthly_finance_cost = opening_balance * monthly_rate
        is_quarter_end = (month % 3 == 0)
        principal_paid = quarterly_amortization_nok if is_quarter_end else 0.0
        # guard the very last month against floating point residue
        if month == amortization_months:
            principal_paid = opening_balance
        closing_balance = opening_balance - principal_paid

        debt_schedule.append({
            "Month": month,
            "Opening balance": opening_balance,
            "Monthly finance cost": monthly_finance_cost,
            "Quarterly amortization": principal_paid,
            "Closing balance": closing_balance,
        })
        balance = closing_balance

    with debt_right:
        first_year_finance_cost = sum(row["Monthly finance cost"] for row in debt_schedule[:12])
        first_month_finance_cost = debt_schedule[0]["Monthly finance cost"] if debt_schedule else 0.0

        m1, m2, m3 = st.columns(3)
        m1.metric("Monthly finance cost (month 1)", fmt(first_month_finance_cost))
        m2.metric("Quarterly amortization", fmt(quarterly_amortization_nok))
        m3.metric("Finance cost, Year 1", fmt(first_year_finance_cost))

        chart_df = pd.DataFrame(debt_schedule)[["Month", "Closing balance"]]
        formatted_line_chart(chart_df, "Month", ["Closing balance"])

        st.markdown("**Monthly schedule** (finance cost monthly, amortization quarterly)")
        debt_schedule_df = pd.DataFrame(debt_schedule)
        show_table(debt_schedule_df, "Month", width="stretch", height=300)

    st.divider()
    st.subheader("Sources & uses")
    su = st.session_state.get("_sources_uses")
    if su is None:
        st.caption(
            "Computing... this figure comes from the Financial Statements tab "
            "and will appear after the page finishes loading."
        )
        cover_operational_funding = False
        operational_equity_nok = 0.0
        operational_debt_nok = 0.0
    else:
        deficit_guideline = abs(su["min_cash_balance"]) if su["min_cash_balance"] < 0 else 0.0

        st.markdown("**Operational funding requirement**")
        st.caption(
            f"Guideline: {fmt(deficit_guideline)}, from the worst point in the monthly "
            f"cash flow assuming **zero** operational funding (month {su['min_cash_month']}). "
            f"This is a fixed target — it doesn't move depending on how much you "
            f"choose to fund below." if deficit_guideline > 0 else
            "Cash flow never dips negative — no operational funding is required."
        )
        cover_operational_funding = stateful_toggle(
            "Cover the operational funding requirement?", value=False,
            key="cover_operational_funding", disabled=locked
        )

        if cover_operational_funding and deficit_guideline > 0:
            operational_equity_raw = nok_input(
                "Operational funding — equity portion (NOK)", "operational_equity_nok", 0.0,
                key="operational_equity_input", disabled=locked
            )
            # IMPORTANT: never write a corrected/capped value back into this
            # widget's own state. The guideline above is computed on Tab 4
            # from a run forced to ZERO operational funding, so — unlike the
            # old design — it no longer moves depending on how much you fund
            # here; it only changes if some other input (capex, opex,
            # escalators, contracts, refinancing) was just edited on another
            # tab, in which case it's one script pass behind until you
            # switch tabs. Keep the raw typed amount untouched in the box
            # regardless, and only cap it for the calculations below,
            # recomputed fresh from the latest guideline every pass — so a
            # temporarily-stale guideline can never permanently discard
            # what the user typed.
            operational_equity_nok = min(operational_equity_raw, deficit_guideline)
            operational_debt_nok = deficit_guideline - operational_equity_nok
            if operational_equity_raw > deficit_guideline:
                st.caption(
                    f"⚠️ You entered {fmt(operational_equity_raw)}, which is more than the "
                    f"guideline ({fmt(deficit_guideline)}). Only {fmt(operational_equity_nok)} "
                    f"is being applied below — the remainder isn't needed unless another "
                    f"input on a different tab changes the guideline."
                )
            st.caption(
                f"The remaining {fmt(operational_debt_nok)} is automatically funded as "
                f"additional debt, at the same swap + credit spread rate and amortization "
                f"profile as the vessel debt above."
            )
        else:
            operational_equity_nok = 0.0
            operational_debt_nok = 0.0

        uncovered = 0.0 if cover_operational_funding else deficit_guideline

        uses_col, sources_col = st.columns(2)
        with uses_col:
            st.markdown("**Uses**")
            uses_df = pd.DataFrame([
                {"Item": "Vessel capex", "Amount": capex_nok},
                {"Item": "Equipment capex" + ("" if su["lease_enabled"] else " (off)"), "Amount": su["equipment_debt"] + su["equipment_equity"]},
                {"Item": "Operational funding — equity portion", "Amount": operational_equity_nok},
                {"Item": "Operational funding — debt portion", "Amount": operational_debt_nok},
                {"Item": "Uncovered operational fund requirement", "Amount": uncovered},
                {"Item": "Total uses", "Amount": capex_nok + su["equipment_debt"] + su["equipment_equity"] + operational_equity_nok + operational_debt_nok + uncovered},
            ])
            show_table(uses_df, "Item", width="stretch")
        with sources_col:
            st.markdown("**Sources**")
            sources_df = pd.DataFrame([
                {"Item": "Vessel debt", "Amount": su["vessel_debt"]},
                {"Item": "Equipment debt" + ("" if su["lease_enabled"] else " (off)"), "Amount": su["equipment_debt"]},
                {"Item": "Operational funding debt", "Amount": operational_debt_nok},
                {"Item": "Vessel equity", "Amount": su["vessel_equity"]},
                {"Item": "Equipment equity" + ("" if su["lease_enabled"] else " (off)"), "Amount": su["equipment_equity"]},
                {"Item": "Operational funding equity", "Amount": operational_equity_nok},
                {"Item": "Uncovered operational funding (equity or debt, TBD)", "Amount": uncovered},
                {"Item": "Total sources", "Amount": su["vessel_debt"] + su["equipment_debt"] + operational_debt_nok + su["vessel_equity"] + su["equipment_equity"] + operational_equity_nok + uncovered},
            ])
            show_table(sources_df, "Item", width="stretch")

        if uncovered > 0:
            st.warning(
                f"**{fmt(uncovered)} of the operational cash-deficit guideline is not "
                f"funded.** Turn on 'Cover the operational funding requirement?' above "
                f"to raise it as equity, debt, or a mix of both — otherwise it's left "
                f"to group liquidity to absorb."
            )

        # store for Tab 4 (cash flow / balance sheet) and Tab 5 (IRR) to pick up
        st.session_state["_operational_funding"] = {
            "equity": operational_equity_nok,
            "debt": operational_debt_nok,
        }

        if su["min_cash_balance"] < 0:
            st.caption(
                f"Operational equity buffer guideline: {fmt(abs(su['min_cash_balance']))}, "
                f"from the worst point in the monthly cash flow (month {su['min_cash_month']}) "
                f"— see the Financial Statements tab to adjust."
            )
        st.caption(
            "This section mirrors the Financial Statements tab. The guideline "
            "itself no longer depends on your funding choice above, so it "
            "won't shift as you adjust the equity/debt split. If a different "
            "input changes elsewhere (capex, opex, escalators, contracts, "
            "refinancing), this number auto-refreshes on its own — no need "
            "to switch tabs or click Refresh manually."
        )

# ===========================================================================
# TAB 1b — Spot market (alternative revenue basis, with transparent
#          voyage cost recovery)
# ===========================================================================
with tab_spot:
    st.subheader("Spot market revenue")
    st.caption(
        "An alternative to the TC-rate above: revenue is a market day-rate "
        "for vessel capacity, plus separate charge lines that recover "
        "voyage costs (fuel, lube oil, port fees, waste, farledsavgift, pH "
        "adjustment) from the customer — shown transparently against what "
        "each actually costs. Unlike a TC charter, these voyage costs sit "
        "for the **owner's** account, not the charterer's, which is why "
        "they need to be billed back explicitly rather than assumed away."
    )

    spot_market_enabled = stateful_toggle(
        "Use spot-market revenue instead of the TC-rate in the Financial Statements",
        value=False, key="spot_market_enabled", disabled=locked
    )
    if not spot_market_enabled:
        st.info(
            "Spot market is currently **off** — the Financial Statements tab "
            "still uses the vessel TC-rate (Tab 1). Inputs below are still "
            "editable so this is ready whenever you switch it on."
        )

    st.markdown("**Utilization & service mix**")
    st.caption(
        "Not every calendar day earns revenue — utilization sets what share "
        "of operating days are actually working. Of those working days, the "
        "service mix splits them across job types (treatment, smolt "
        "transport, harvest transport, etc.), each at its own day-rate. "
        "Vessel opex (crewing — Tab 1) is unaffected by utilization, since "
        "crew cost doesn't stop during idle days; voyage costs below scale "
        "with utilization the same way revenue does, since idle days don't "
        "burn fuel or incur port fees either."
    )

    st.markdown("**Service mix** (% of activity, by service type)")
    st.caption(
        "Set overall utilization once, then split it across services as a "
        "percentage — days/year are computed automatically from these two "
        "numbers rather than typed in directly. Same underlying math as "
        "before (days = utilization x operating days x share), just entered "
        "the way it's easiest to work through with the board or commercial "
        "team: '65% utilization, split 70/20/10', not a calculator."
    )

    spot_utilization_pct = stateful_number_input(
        "Utilization (%)", min_value=0.0, max_value=100.0, value=65.0, step=1.0,
        key="spot_utilization_pct", disabled=locked
    )
    _working_days_annual_target = operating_days * (spot_utilization_pct / 100)
    st.caption(f"= {fmt(_working_days_annual_target)} working days/year, out of {fmt(operating_days)} operating days (Tab 1) — this is the Year 1 baseline; see the Capacity schedule below to change it for later years.")

    if "spot_service_items" not in st.session_state:
        st.session_state.spot_service_items = [
            {"name": "Treatment of fish", "share_pct": 70.0, "rate_nok_day": 819_000.0, "escalator_pct": 3.0, "priced_at_baseline": False},
            {"name": "Smolt transport", "share_pct": 20.0, "rate_nok_day": 456_000.0, "escalator_pct": 2.0, "priced_at_baseline": False},
            {"name": "Harvest transport", "share_pct": 10.0, "rate_nok_day": 456_000.0, "escalator_pct": 2.0, "priced_at_baseline": False},
        ]

    st.markdown("**Fixed Voyage opex (annual budget, spread over working days)**")
    st.caption(
        "Unlike Tab 1's crewing/vessel opex — which is fixed and applies "
        "every calendar day, since crew salaries don't stop when idle — "
        "this treats fixed voyage opex as a separate **annual** budget "
        "that gets spread over however many days are actually worked. "
        "Defaults to 0 — this is a fuse for future overhead specific to "
        "running the spot-trade business (e.g. a dedicated spot-trade "
        "commercial hire), not currently modeled elsewhere. Change the "
        "annual figure, or change utilization above, and the resulting "
        "day-rate updates automatically either way — it's the day-rate "
        "that's derived, not the annual figure. While spot mode is active, "
        "this **replaces** Tab 1's opex for the vessel's P&L (Tab 1's own "
        "figures stay as they are, for the TC-mode scenario)."
    )
    spot_opex_annual_nok = nok_input(
        "Fixed Voyage opex (NOK/year, total)", "spot_opex_annual_nok", 1_000_000.0,
        key="spot_opex_annual_input", disabled=locked
    )
    _opex_esc_col1, _opex_esc_col2 = st.columns(2)
    with _opex_esc_col1:
        spot_opex_escalator_pct = stateful_number_input(
            "Fixed Voyage opex escalator (%/yr)", min_value=-100.0, value=2.0, step=0.5,
            key="spot_opex_escalator", disabled=locked
        )
    with _opex_esc_col2:
        spot_variable_opex_escalator_pct = stateful_number_input(
            "Variable Voyage opex escalator (%/yr)", min_value=-100.0, value=2.0, step=0.5,
            key="spot_variable_opex_escalator", disabled=locked,
            help="Drives the Smolt/Harvest/Treatment build-up tools' own "
                 "voyage costs (fuel, additional opex/hr) — decoupled from "
                 "both the Fixed line above and each segment's own revenue "
                 "escalator on the Service mix table, so cost and revenue "
                 "can grow at different rates."
        )
    spot_opex_rate_nok_day = (
        spot_opex_annual_nok / _working_days_annual_target if _working_days_annual_target else 0.0
    )
    st.metric(
        "Implied day-rate (derived)",
        fmt(spot_opex_rate_nok_day) + "/day",
        help=f"{fmt(spot_opex_annual_nok)}/year ÷ {fmt(_working_days_annual_target)} working days/year."
    )

    st.markdown("**Year 1–12 planning** (utilization by year, and revenue indexation by segment)")
    st.caption(
        "Utilization set individually for each year — no staging concept, "
        "just type the number you expect for that year. Defaults to 65% "
        "(matching the baseline above) for every year; adjust freely, "
        "e.g. ramping up as you add capacity. Indexation below is one "
        "flat rate per segment (not per-year) — each segment's day-rate "
        "compounds at its own rate from Year 2 onward, same escalation "
        "pattern used everywhere else in this model."
    )

    if "spot_utilization_by_year" not in st.session_state:
        st.session_state.spot_utilization_by_year = [65.0] * 11

    st.markdown("Utilization (%), Year 2–12")
    _util_year_cols = st.columns(11)
    for _yi in range(11):
        with _util_year_cols[_yi]:
            st.session_state.spot_utilization_by_year[_yi] = st.number_input(
                f"Year {_yi + 2}", min_value=0.0, max_value=100.0,
                value=st.session_state.spot_utilization_by_year[_yi], step=1.0,
                key=f"spot_util_year_{_yi}", disabled=locked
            )
    spot_utilization_by_year = st.session_state.spot_utilization_by_year

    st.markdown("**Fixed Voyage opex — today's value, Year 2–12**")
    st.caption(
        "Each year's own real (today's money) Fixed Voyage opex — default "
        "matches Year 1's baseline above. Change a later year's value to "
        "reflect a real cost change (e.g. hiring a second person): typing "
        "2,000,000 for Year 3 means 2,000,000 in today's money, which the "
        "Financial Statements then show as 2,000,000 x (1 + Fixed Voyage "
        "opex escalator)² in Year 3's nominal terms — the same single "
        "escalator set above, just applied to whatever real value is "
        "typed for that specific year, not a new escalation clock."
    )
    if "spot_fixed_opex_real_by_year" not in st.session_state:
        st.session_state.spot_fixed_opex_real_by_year = [spot_opex_annual_nok] * 11

    def _on_fixed_opex_year_change(index):
        raw = st.session_state[f"spot_fixed_opex_year_{index}"]
        value = parse_nok(raw)
        st.session_state.spot_fixed_opex_real_by_year[index] = value
        st.session_state[f"spot_fixed_opex_year_{index}"] = format_nok(value)

    _fixed_opex_year_cols = st.columns(11)
    for _yi in range(11):
        with _fixed_opex_year_cols[_yi]:
            _fixed_opex_display_key = f"spot_fixed_opex_year_{_yi}"
            if _fixed_opex_display_key not in st.session_state:
                st.session_state[_fixed_opex_display_key] = format_nok(st.session_state.spot_fixed_opex_real_by_year[_yi])
            st.text_input(
                f"Year {_yi + 2}", key=_fixed_opex_display_key,
                on_change=_on_fixed_opex_year_change, args=(_yi,), disabled=locked
            )
    spot_fixed_opex_real_by_year = st.session_state.spot_fixed_opex_real_by_year

    st.markdown("**Additional spot capex — Year 2–12** (on top of the NOK 4.3m TC-equivalent maintenance capex)")
    st.caption(
        "Spot trading takes slightly more wear on the vessel than a "
        "steady TC charter — this is the extra capex on top of what the "
        "TC-operation would incur (Tab 1's maintenance capex, applied "
        "unconditionally either way). Punch in a real (today's money) "
        "figure for whichever year it's needed. Added to the vessel's "
        "asset value on the balance sheet and depreciated on its own "
        "schedule (set below), separate from the vessel/maintenance "
        "capex rate — see the Financial Statements tab's Asset register "
        "for the resulting P&L/cash flow/balance sheet lines."
    )
    spot_additional_capex_depreciation_pct = stateful_number_input(
        "Additional spot capex depreciation rate (%/yr)", min_value=0.1, max_value=100.0, value=5.0, step=0.5,
        key="spot_additional_capex_depreciation", disabled=locked,
        help="Default 5%/yr = 20-year useful life. Separate from the "
             "vessel's own rate (Tab 1), since spot-specific capex "
             "additions may have a genuinely different useful life."
    )
    if spot_additional_capex_depreciation_pct > 0:
        st.caption(f"= {100/spot_additional_capex_depreciation_pct:.0f}-year implied useful life.")

    if "spot_additional_capex_by_year" not in st.session_state:
        st.session_state.spot_additional_capex_by_year = [1_000_000.0] * 11

    def _on_additional_capex_year_change(index):
        raw = st.session_state[f"spot_additional_capex_year_{index}"]
        value = parse_nok(raw)
        st.session_state.spot_additional_capex_by_year[index] = value
        st.session_state[f"spot_additional_capex_year_{index}"] = format_nok(value)

    _additional_capex_year_cols = st.columns(11)
    for _yi in range(11):
        with _additional_capex_year_cols[_yi]:
            _additional_capex_display_key = f"spot_additional_capex_year_{_yi}"
            if _additional_capex_display_key not in st.session_state:
                st.session_state[_additional_capex_display_key] = format_nok(st.session_state.spot_additional_capex_by_year[_yi])
            st.text_input(
                f"Year {_yi + 2}", key=_additional_capex_display_key,
                on_change=_on_additional_capex_year_change, args=(_yi,), disabled=locked
            )
    spot_additional_capex_by_year = st.session_state.spot_additional_capex_by_year

    st.markdown("**Revenue indexation by segment — Year 2–12** (each year's own %, compounding)")
    st.caption(
        "Each cell is that specific year's escalator versus the year "
        "before — not a single flat rate — so Year 5's nominal rate "
        "depends on every year's own % from Year 2 through Year 5, "
        "compounding. Defaults to 2% everywhere; change any individual "
        "year freely."
    )

    def _init_segment_escalator_years(state_key):
        if state_key not in st.session_state:
            st.session_state[state_key] = [2.0] * 11

    _init_segment_escalator_years("spot_smolt_escalator_by_year")
    _init_segment_escalator_years("spot_harvest_escalator_by_year")
    _init_segment_escalator_years("spot_treatment_escalator_by_year")

    st.markdown("Smolt indexation (%/yr)")
    _smolt_esc_cols = st.columns(11)
    for _yi in range(11):
        with _smolt_esc_cols[_yi]:
            st.session_state.spot_smolt_escalator_by_year[_yi] = st.number_input(
                f"Year {_yi + 2}", min_value=-100.0,
                value=st.session_state.spot_smolt_escalator_by_year[_yi], step=0.5,
                key=f"spot_smolt_esc_year_{_yi}", label_visibility="collapsed", disabled=locked
            )
    spot_smolt_escalator_by_year = st.session_state.spot_smolt_escalator_by_year

    st.markdown("Harvest indexation (%/yr)")
    _harvest_esc_cols = st.columns(11)
    for _yi in range(11):
        with _harvest_esc_cols[_yi]:
            st.session_state.spot_harvest_escalator_by_year[_yi] = st.number_input(
                f"Year {_yi + 2}", min_value=-100.0,
                value=st.session_state.spot_harvest_escalator_by_year[_yi], step=0.5,
                key=f"spot_harvest_esc_year_{_yi}", label_visibility="collapsed", disabled=locked
            )
    spot_harvest_escalator_by_year = st.session_state.spot_harvest_escalator_by_year

    st.markdown("Treatment indexation (%/yr)")
    _treatment_esc_cols = st.columns(11)
    for _yi in range(11):
        with _treatment_esc_cols[_yi]:
            st.session_state.spot_treatment_escalator_by_year[_yi] = st.number_input(
                f"Year {_yi + 2}", min_value=-100.0,
                value=st.session_state.spot_treatment_escalator_by_year[_yi], step=0.5,
                key=f"spot_treatment_esc_year_{_yi}", label_visibility="collapsed", disabled=locked
            )
    spot_treatment_escalator_by_year = st.session_state.spot_treatment_escalator_by_year

    # --- baseline reference: the COMBINED TC-rate (vessel + leased
    # equipment, e.g. the FLS equipment lease) — not vessel-only. Tab 3
    # (Combined TC-rate) computes this but runs AFTER this tab in script
    # order, so it's read one pass behind via session state (same
    # convention used elsewhere in this app, e.g. Tab 1's Sources & Uses
    # guideline). Falls back to vessel-only on the very first load, before
    # Tab 3 has run even once. ---
    spot_baseline_tc_daily = st.session_state.get("_combined_tc_daily", vessel_tc_daily)

    # This is the required NET income per working day — i.e. after voyage
    # opex, matching the TC-equivalent annual return. Gross price (what's
    # actually billed) = this net target + voyage opex. Utilization is now
    # a direct input above, not derived from a table that renders later —
    # so this is computed once, straightforwardly, with no provisional/
    # stale-versus-final distinction needed anymore.
    required_net_rate_at_utilization = (
        spot_baseline_tc_daily / (spot_utilization_pct / 100) if spot_utilization_pct > 0 else 0.0
    )
    required_gross_rate_at_utilization = required_net_rate_at_utilization + spot_opex_rate_nok_day

    st.markdown("**Baseline reference** (imported live from the Combined TC-rate, Tab 3 — vessel + leased equipment)")
    bl1, bl2, bl3, bl4 = st.columns(4)
    bl1.metric("Baseline TC-rate, 100% utilization (vessel + equipment)", fmt(spot_baseline_tc_daily) + "/day")
    bl2.metric("Utilization (input)", f"{spot_utilization_pct:.1f}%")
    bl3.metric("Required NET rate on working days", fmt(required_net_rate_at_utilization) + "/day")
    bl4.metric("Required GROSS price (net + voyage opex)", fmt(required_gross_rate_at_utilization) + "/day")
    st.caption(
        f"= {fmt(vessel_tc_daily)}/day vessel (Tab 1) + "
        f"{fmt(spot_baseline_tc_daily - vessel_tc_daily)}/day leased equipment "
        f"(Tab 2/3, e.g. FLS) — this is a **100%-utilization** rate (spread "
        f"across every operating day, not just working days), matching how "
        f"a TC charter is priced. Required NET rate = baseline ÷ "
        f"utilization — the net income a job type needs to earn, on the "
        f"days it's actually working, to match the same TC-equivalent "
        f"annual revenue at the utilization set above. Required GROSS "
        f"price = that net target + voyage opex "
        f"({fmt(spot_opex_rate_nok_day)}/day) — this is the day-rate "
        f"actually billed. Services flagged 'priced at baseline' below are "
        f"simply assumed to bill at this gross price exactly (no "
        f"price-list build-up on top) — a simplifying assumption for "
        f"segments that aren't the focus of the pricing work. Baseline "
        f"TC-rate above is one script pass behind Tab 3 — switch tabs once "
        f"after editing lease inputs for it to catch up."
    )

    def _add_service_item():
        st.session_state.spot_service_items.append(
            {"name": "New service", "share_pct": 0.0, "rate_nok_day": 0.0, "escalator_pct": 0.0, "priced_at_baseline": False}
        )

    def _remove_service_item(index):
        st.session_state.spot_service_items.pop(index)

    def _on_service_rate_change(index):
        raw = st.session_state[f"service_rate_{index}"]
        value = parse_nok(raw)
        st.session_state.spot_service_items[index]["rate_nok_day"] = value
        st.session_state[f"service_rate_{index}"] = format_nok(value)

    shdr1, shdr2, shdr3, shdr4, shdr5, shdr6, shdr7, shdr8 = st.columns([1.4, 1.2, 0.9, 0.8, 1.1, 1.1, 1.3, 0.4])
    shdr1.markdown("**Service**")
    shdr2.markdown("**Share of working days (%)**")
    shdr3.markdown("**Days/year**")
    shdr4.markdown("**% of year**")
    shdr5.markdown("**Priced at baseline?**")
    shdr6.markdown("**Rate (NOK/day)**")
    shdr7.markdown("**Annual revenue (NOK)**")

    _sum_share = 0.0
    _sum_days = 0.0
    _sum_annual_revenue = 0.0

    for i, item in enumerate(st.session_state.spot_service_items):
        item.setdefault("priced_at_baseline", False)
        item.setdefault("share_pct", 0.0)
        item.setdefault("escalator_pct", 0.0)
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.4, 1.2, 0.9, 0.8, 1.1, 1.1, 1.3, 0.4])
        with c1:
            item["name"] = st.text_input(
                "Service", value=item["name"], key=f"service_name_{i}", label_visibility="collapsed",
                disabled=locked
            )
        with c2:
            item["share_pct"] = st.number_input(
                "Share of working days (%)", min_value=0.0, max_value=100.0, value=item["share_pct"],
                step=1.0, key=f"service_share_{i}", label_visibility="collapsed", disabled=locked
            )
        with c3:
            _days_this = _working_days_annual_target * (item["share_pct"] / 100)
            item["days_per_year"] = _days_this  # cached/computed — everything downstream still just reads this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_days_this)}</div>", unsafe_allow_html=True)
        with c4:
            _pct_of_year = (_days_this / operating_days * 100) if operating_days else 0.0
            st.markdown(f"<div style='padding-top:8px'>{_pct_of_year:.1f}%</div>", unsafe_allow_html=True)
        with c5:
            item["priced_at_baseline"] = st.checkbox(
                "Priced at baseline?", value=item["priced_at_baseline"],
                key=f"service_baseline_{i}", label_visibility="collapsed", disabled=locked
            )
        with c6:
            if item["priced_at_baseline"]:
                _row_rate = required_gross_rate_at_utilization
                st.text_input(
                    "Rate (NOK/day)", value=format_nok(_row_rate),
                    key=f"service_rate_display_{i}", label_visibility="collapsed", disabled=True
                )
            else:
                _row_rate = item["rate_nok_day"]
                if f"service_rate_{i}" not in st.session_state:
                    st.session_state[f"service_rate_{i}"] = format_nok(item["rate_nok_day"])
                st.text_input(
                    "Rate (NOK/day)", key=f"service_rate_{i}", label_visibility="collapsed",
                    on_change=_on_service_rate_change, args=(i,), disabled=locked
                )
        with c7:
            _row_annual_revenue = _row_rate * _days_this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_row_annual_revenue)}</div>", unsafe_allow_html=True)
        with c8:
            st.button("✕", key=f"service_remove_{i}", on_click=_remove_service_item, args=(i,), disabled=locked)

        _sum_share += item["share_pct"]
        _sum_days += _days_this
        _sum_annual_revenue += _row_annual_revenue

    st.button("+ Add service", on_click=_add_service_item, disabled=locked)

    if abs(_sum_share - 100.0) > 0.5:
        st.warning(
            f"⚠️ Shares sum to {_sum_share:.1f}%, not 100%. Days/year above "
            f"are still computed as entered, but check the shares reflect "
            f"the intended mix."
        )

    _sum_pct_of_year = (_sum_days / operating_days * 100) if operating_days else 0.0
    tcol1, tcol2, tcol3, tcol4, tcol5 = st.columns([1.4, 1.2, 0.9, 0.8, 2.7])
    tcol1.markdown("**Total**")
    tcol2.markdown(f"**{_sum_share:.1f}%**")
    tcol3.markdown(f"**{fmt(_sum_days)}**")
    tcol4.markdown(f"**{_sum_pct_of_year:.1f}%**")
    tcol5.markdown(f"**{fmt(_sum_annual_revenue)}** (revenue only, excl. opex and price-list build-up)")

    _target_net_annual = spot_baseline_tc_daily * operating_days
    _target_gross_annual = _target_net_annual + spot_opex_annual_nok
    _target_delta = _sum_annual_revenue - _target_gross_annual
    st.caption(
        f"Target: {fmt(_target_net_annual)} net (baseline TC-rate x operating days) + "
        f"{fmt(spot_opex_annual_nok)} opex = **{fmt(_target_gross_annual)}** gross required. "
        f"Current total above: {fmt(_sum_annual_revenue)} "
        f"({'+' if _target_delta >= 0 else ''}{fmt(_target_delta)} vs. target)."
    )

    spot_service_items_current = [
        {
            "name": item["name"],
            "days_per_year": item["days_per_year"],
            "share_pct": item.get("share_pct", 0.0),
            "rate_nok_day": item["rate_nok_day"],
            "escalator_pct": item.get("escalator_pct", 0.0),
            "priced_at_baseline": item.get("priced_at_baseline", False),
        }
        for item in st.session_state.spot_service_items
    ]

    # Should equal _working_days_annual_target by construction, barring the
    # shares-not-summing-to-100% edge case flagged above.
    _working_days_annual = sum(item["days_per_year"] for item in spot_service_items_current)

    st.divider()
    st.markdown("**Smolt voyage cost build-up** (per round trip)")
    st.caption(
        "Bottom-up, phase-by-phase cost for one smolt round trip — build "
        "this properly first, then copy the same structure for Harvest. "
        "Steaming phases derive fuel from speed (fuel burn scales roughly "
        "with speed cubed — hull resistance physics, hence 'almost double' "
        "going from 9 to 11 knots); Stationary phases (loading/offloading) "
        "use a directly-entered fuel rate instead, since propulsion "
        "physics don't apply while alongside. An additional flat cost/hour "
        "(crew overtime, wear, consumables, etc.) applies across every "
        "phase regardless of type. **Every number below — speed per "
        "Steaming phase, fuel rates, the exponent, fuel price — is a "
        "starting default, not fixed**: try raising the speed on 'Steam "
        "to client' or 'Steam to pens' to see the cost of running faster "
        "flow straight through, live."
    )

    smolt_gcol1, smolt_gcol2, smolt_gcol3, smolt_gcol4 = st.columns(4)
    with smolt_gcol1:
        spot_smolt_ref_speed_kn = stateful_number_input(
            "Reference speed (knots)", min_value=0.1, value=9.0, step=0.5,
            key="spot_smolt_ref_speed", disabled=locked
        )
    with smolt_gcol2:
        spot_smolt_ref_fuel_lhr = stateful_number_input(
            "Fuel rate @ reference speed (L/hr)", min_value=0.0, value=350.0, step=10.0,
            key="spot_smolt_ref_fuel", disabled=locked
        )
    with smolt_gcol3:
        spot_smolt_speed_exponent = stateful_number_input(
            "Speed → fuel exponent", min_value=1.0, max_value=5.0, value=1.8, step=0.1,
            key="spot_smolt_speed_exp", disabled=locked,
            help="Fuel rate at any speed = reference rate x (speed / reference speed) ^ this exponent. "
                 "3.0 is the standard hull-resistance approximation (fuel roughly triples if speed doubles)."
        )
    with smolt_gcol4:
        spot_smolt_fuel_price = stateful_number_input(
            "Fuel price (NOK/liter)", min_value=0.0, value=12.5, step=0.5,
            key="spot_smolt_fuel_price", disabled=locked
        )
    spot_smolt_additional_opex_hr = nok_input(
        "Additional cost per hour in operation (NOK/hr) — all phases",
        "spot_smolt_additional_opex_hr", 2_000.0,
        key="spot_smolt_additional_opex_input", disabled=locked
    )

    if "spot_smolt_segments" not in st.session_state:
        st.session_state.spot_smolt_segments = [
            {"name": "Steam to client", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0},
            {"name": "Load smolt", "type": "Stationary", "duration_hr": 8.0, "speed_kn": 0.0, "fuel_rate_lhr": 50.0},
            {"name": "Steam to pens", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0},
            {"name": "Offload smolt", "type": "Stationary", "duration_hr": 4.0, "speed_kn": 0.0, "fuel_rate_lhr": 50.0},
            {"name": "Others/waiting time", "type": "Stationary", "duration_hr": 4.5, "speed_kn": 0.0, "fuel_rate_lhr": 20.0},
        ]

    def _add_smolt_segment():
        st.session_state.spot_smolt_segments.append(
            {"name": "New phase", "type": "Stationary", "duration_hr": 0.0, "speed_kn": 0.0, "fuel_rate_lhr": 0.0}
        )

    def _remove_smolt_segment(index):
        st.session_state.spot_smolt_segments.pop(index)

    smhdr = st.columns([1.6, 1.1, 0.9, 0.9, 1.1, 0.9, 1.1, 1.1, 1.2, 0.4])
    smhdr[0].markdown("**Phase**")
    smhdr[1].markdown("**Type**")
    smhdr[2].markdown("**Duration (hr)**")
    smhdr[3].markdown("**Speed (kn)**")
    smhdr[4].markdown("**Fuel rate (L/hr)**")
    smhdr[5].markdown("**Fuel (L)**")
    smhdr[6].markdown("**Fuel cost (NOK)**")
    smhdr[7].markdown("**Add'l opex (NOK)**")
    smhdr[8].markdown("**Total cost (NOK)**")

    _smolt_total_hours = 0.0
    _smolt_total_fuel_l = 0.0
    _smolt_total_fuel_cost = 0.0
    _smolt_total_additional_opex = 0.0
    _smolt_total_cost = 0.0

    for si, seg in enumerate(st.session_state.spot_smolt_segments):
        cols = st.columns([1.6, 1.1, 0.9, 0.9, 1.1, 0.9, 1.1, 1.1, 1.2, 0.4])
        with cols[0]:
            seg["name"] = st.text_input(
                "Phase", value=seg["name"], key=f"smolt_seg_name_{si}", label_visibility="collapsed", disabled=locked
            )
        with cols[1]:
            seg["type"] = st.selectbox(
                "Type", ["Steaming", "Stationary"],
                index=0 if seg["type"] == "Steaming" else 1,
                key=f"smolt_seg_type_{si}", label_visibility="collapsed", disabled=locked
            )
        with cols[2]:
            seg["duration_hr"] = st.number_input(
                "Duration (hr)", min_value=0.0, value=seg["duration_hr"], step=0.5,
                key=f"smolt_seg_duration_{si}", label_visibility="collapsed", disabled=locked
            )
        with cols[3]:
            if seg["type"] == "Steaming":
                seg["speed_kn"] = st.number_input(
                    "Speed (kn)", min_value=0.0, value=seg["speed_kn"], step=0.5,
                    key=f"smolt_seg_speed_{si}", label_visibility="collapsed", disabled=locked
                )
            else:
                st.markdown("<div style='padding-top:8px'>—</div>", unsafe_allow_html=True)
        with cols[4]:
            if seg["type"] == "Steaming":
                _fuel_rate_this = spot_smolt_ref_fuel_lhr * (
                    (seg["speed_kn"] / spot_smolt_ref_speed_kn) ** spot_smolt_speed_exponent
                    if spot_smolt_ref_speed_kn else 0.0
                )
                st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_rate_this)}</div>", unsafe_allow_html=True)
            else:
                seg["fuel_rate_lhr"] = st.number_input(
                    "Fuel rate (L/hr)", min_value=0.0, value=seg["fuel_rate_lhr"], step=5.0,
                    key=f"smolt_seg_fuelrate_{si}", label_visibility="collapsed", disabled=locked
                )
                _fuel_rate_this = seg["fuel_rate_lhr"]
        with cols[5]:
            _fuel_this = _fuel_rate_this * seg["duration_hr"]
            st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_this)}</div>", unsafe_allow_html=True)
        with cols[6]:
            _fuel_cost_this = _fuel_this * spot_smolt_fuel_price
            st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_cost_this)}</div>", unsafe_allow_html=True)
        with cols[7]:
            _additional_opex_this = spot_smolt_additional_opex_hr * seg["duration_hr"]
            st.markdown(f"<div style='padding-top:8px'>{fmt(_additional_opex_this)}</div>", unsafe_allow_html=True)
        with cols[8]:
            _total_cost_this = _fuel_cost_this + _additional_opex_this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_total_cost_this)}</div>", unsafe_allow_html=True)
        with cols[9]:
            st.button("✕", key=f"smolt_seg_remove_{si}", on_click=_remove_smolt_segment, args=(si,), disabled=locked)

        _smolt_total_hours += seg["duration_hr"]
        _smolt_total_fuel_l += _fuel_this
        _smolt_total_fuel_cost += _fuel_cost_this
        _smolt_total_additional_opex += _additional_opex_this
        _smolt_total_cost += _total_cost_this

    st.button("+ Add phase", key="smolt_add_phase", on_click=_add_smolt_segment, disabled=locked)

    tcols = st.columns([1.6, 1.1, 0.9, 0.9, 1.1, 0.9, 1.1, 1.1, 1.2, 0.4])
    tcols[0].markdown("**Round trip total**")
    tcols[2].markdown(f"**{fmt(_smolt_total_hours)}**")
    tcols[5].markdown(f"**{fmt(_smolt_total_fuel_l)}**")
    tcols[6].markdown(f"**{fmt(_smolt_total_fuel_cost)}**")
    tcols[7].markdown(f"**{fmt(_smolt_total_additional_opex)}**")
    tcols[8].markdown(f"**{fmt(_smolt_total_cost)}**")

    _smolt_days_available = next(
        (item["days_per_year"] for item in spot_service_items_current if item["name"] == "Smolt transport"),
        0.0
    )
    _smolt_hours_available = _smolt_days_available * 24
    _smolt_trips_exact = (_smolt_hours_available / _smolt_total_hours) if _smolt_total_hours else 0.0
    _smolt_trips_whole = int(_smolt_trips_exact)
    _smolt_annual_voyage_cost = _smolt_total_cost * _smolt_trips_exact
    _smolt_implied_day_rate = (_smolt_annual_voyage_cost / _smolt_days_available) if _smolt_days_available else 0.0

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Hours per round trip", fmt(_smolt_total_hours))
    sm2.metric("Trips available (47-day-style window)", f"{_smolt_trips_exact:.1f}", help=f"{_smolt_trips_whole} whole trips + a partial trip, over {fmt(_smolt_days_available)} days available (from the Service mix table).")
    sm3.metric("Implied annual voyage cost (round trips only)", fmt(_smolt_annual_voyage_cost))
    sm4.metric("Implied day-rate (round trips only)", fmt(_smolt_implied_day_rate) + "/day")
    st.caption(
        f"Days available for Smolt: {fmt(_smolt_days_available)} (from the Service mix table above) "
        f"x 24 hr = {fmt(_smolt_hours_available)} hours ÷ {fmt(_smolt_total_hours)} hours/round trip "
        f"= {_smolt_trips_exact:.2f} trips/year."
    )

    st.divider()
    st.markdown("**Customer changeover costs** (per year)")
    st.caption(
        "Separate from the round-trip cost above — these happen per "
        "customer relationship, not per round trip. Defaults below assume "
        "your restated total (8 deep cleans, 8 intermediate cleans); "
        "'Intermediate cleans per customer' defaults to 1 so 8 customers "
        "x 1 = 8 — bump it to 2 directly if you actually meant twice per "
        "customer (16/year)."
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        spot_smolt_customers_per_year = stateful_number_input(
            "Customers/year", min_value=0.0, value=8.0, step=1.0,
            key="spot_smolt_customers_per_year", disabled=locked
        )
    with cc2:
        _rounds_per_customer = (_smolt_trips_exact / spot_smolt_customers_per_year) if spot_smolt_customers_per_year else 0.0
        st.metric("Rounds per customer (check)", f"{_rounds_per_customer:.1f}", help="Trips available ÷ customers/year — should land near your expected 4-5 rounds per customer.")

    cc3, cc4 = st.columns(2)
    with cc3:
        st.markdown("**Deep disinfection**")
        spot_smolt_deep_clean_days = stateful_number_input(
            "Days at yard", min_value=0.0, value=1.0, step=0.5,
            key="spot_smolt_deep_clean_days", disabled=locked
        )
        spot_smolt_yard_cost_per_day = nok_input(
            "Disinfection opex (NOK/day)", "spot_smolt_yard_cost_per_day", 25_000.0,
            key="spot_smolt_yard_cost_input", disabled=locked
        )
        spot_smolt_drydock_cost_per_day = nok_input(
            "Dry-docking cost (NOK/day)", "spot_smolt_drydock_cost_per_day", 75_000.0,
            key="spot_smolt_drydock_cost_input", disabled=locked
        )
        st.caption(
            "Cost/event = days at yard x (disinfection opex/day + dry-docking "
            "cost/day). Once per customer change — frequency = customers/year."
        )
    with cc4:
        st.markdown("**Intermediate clean**")
        spot_smolt_intermediate_clean_hr = stateful_number_input(
            "Duration (hr)", min_value=0.0, value=3.0, step=0.5,
            key="spot_smolt_intermediate_clean_hr", disabled=locked
        )
        spot_smolt_intermediate_cost_per_hr = nok_input(
            "Cost per hour (NOK/hr)", "spot_smolt_intermediate_cost_per_hr", 2_500.0,
            key="spot_smolt_intermediate_cost_input", disabled=locked
        )
        spot_smolt_intermediate_cleans_per_customer = stateful_number_input(
            "Intermediate cleans per customer (0 to skip)", min_value=0.0, value=1.0, step=1.0,
            key="spot_smolt_intermediate_cleans_per_customer", disabled=locked
        )
        st.caption(
            "Cost/event = duration x cost/hour — no dry-dock, no fuel "
            "physics, just a blended operational rate."
        )

    spot_smolt_deep_clean_cost = (
        spot_smolt_deep_clean_days * (spot_smolt_yard_cost_per_day + spot_smolt_drydock_cost_per_day)
    )
    spot_smolt_intermediate_clean_cost = (
        spot_smolt_intermediate_clean_hr * spot_smolt_intermediate_cost_per_hr
    )
    st.caption(
        f"Computed cost per event — Deep disinfection: {fmt(spot_smolt_deep_clean_cost)}, "
        f"Intermediate clean: {fmt(spot_smolt_intermediate_clean_cost)}."
    )

    cc5, cc6 = st.columns(2)
    with cc5:
        spot_smolt_transport_base_hr = stateful_number_input(
            "Transport back to base — duration (hr)", min_value=0.0, value=8.0, step=0.5,
            key="spot_smolt_transport_base_hr", disabled=locked
        )
    with cc6:
        spot_smolt_transport_base_speed = stateful_number_input(
            "Transport back to base — speed (kn)", min_value=0.0, value=spot_smolt_ref_speed_kn, step=0.5,
            key="spot_smolt_transport_base_speed", disabled=locked
        )
    st.caption(
        "Once per customer change — frequency = customers/year. Fuel cost "
        "uses the same speed formula and additional cost/hour as the "
        "round-trip phases above."
    )

    _transport_base_fuel_rate = spot_smolt_ref_fuel_lhr * (
        (spot_smolt_transport_base_speed / spot_smolt_ref_speed_kn) ** spot_smolt_speed_exponent
        if spot_smolt_ref_speed_kn else 0.0
    )
    _transport_base_cost_per_event = (
        (_transport_base_fuel_rate * spot_smolt_transport_base_hr * spot_smolt_fuel_price)
        + (spot_smolt_additional_opex_hr * spot_smolt_transport_base_hr)
    )

    _annual_deep_clean_cost = spot_smolt_customers_per_year * spot_smolt_deep_clean_cost
    _annual_intermediate_clean_cost = (
        spot_smolt_customers_per_year * spot_smolt_intermediate_cleans_per_customer * spot_smolt_intermediate_clean_cost
    )
    _annual_transport_base_cost = spot_smolt_customers_per_year * _transport_base_cost_per_event
    _annual_changeover_cost = _annual_deep_clean_cost + _annual_intermediate_clean_cost + _annual_transport_base_cost

    changeover_df = pd.DataFrame([
        {"Item": "Deep disinfection", "Events/year": spot_smolt_customers_per_year, "Cost/event (NOK)": spot_smolt_deep_clean_cost, "Annual cost (NOK)": _annual_deep_clean_cost},
        {"Item": "Intermediate clean", "Events/year": spot_smolt_customers_per_year * spot_smolt_intermediate_cleans_per_customer, "Cost/event (NOK)": spot_smolt_intermediate_clean_cost, "Annual cost (NOK)": _annual_intermediate_clean_cost},
        {"Item": "Transport back to base", "Events/year": spot_smolt_customers_per_year, "Cost/event (NOK)": _transport_base_cost_per_event, "Annual cost (NOK)": _annual_transport_base_cost},
        {"Item": "Total", "Events/year": None, "Cost/event (NOK)": None, "Annual cost (NOK)": _annual_changeover_cost},
    ])
    show_table(changeover_df, "Item", width="stretch")

    _smolt_total_annual_voyage_cost = _smolt_annual_voyage_cost + _annual_changeover_cost
    _smolt_total_implied_day_rate = (
        _smolt_total_annual_voyage_cost / _smolt_days_available if _smolt_days_available else 0.0
    )

    st.markdown("**Combined total (round trips + customer changeover)**")
    ct1, ct2 = st.columns(2)
    ct1.metric("Total implied annual voyage cost", fmt(_smolt_total_annual_voyage_cost))
    ct2.metric("Total implied day-rate", fmt(_smolt_total_implied_day_rate) + "/day")
    st.caption(
        "This is a build-up tool — the resulting day-rate isn't wired into "
        "the Voyage costs table below yet; once you're happy with this and "
        "the Harvest build-up further down, say so and I'll connect both "
        "into the actual Voyage costs table."
    )

    st.markdown("**Net income check — Smolt transport**")
    st.caption(
        "Links the customer rate set on the Service mix table above "
        "against this build-up's voyage cost, so you can see the "
        "contribution margin move live as you test different rates in "
        "discussion."
    )
    _smolt_charged_rate = next(
        (item["rate_nok_day"] for item in spot_service_items_current if item["name"] == "Smolt transport"),
        0.0
    )
    _smolt_charged_annual_revenue = _smolt_charged_rate * _smolt_days_available
    _smolt_net_income_day = _smolt_charged_rate - _smolt_total_implied_day_rate
    _smolt_net_income_annual = _smolt_charged_annual_revenue - _smolt_total_annual_voyage_cost

    ni1, ni2, ni3, ni4 = st.columns(4)
    ni1.metric("Charged rate (NOK/day)", fmt(_smolt_charged_rate) + "/day")
    ni2.metric("Charged annual revenue (NOK)", fmt(_smolt_charged_annual_revenue))
    ni3.metric("Net income (NOK/day)", fmt(_smolt_net_income_day) + "/day")
    ni4.metric("Net income (NOK/year)", fmt(_smolt_net_income_annual))

    st.divider()
    st.markdown("**Harvest voyage cost build-up** (per round trip)")
    st.caption(
        "Bottom-up, phase-by-phase cost for one harvest round trip — same "
        "structure as the Smolt build-up above, adapted for harvest-size "
        "(~5kg) fish and reversed logistics (picking fish up from the "
        "pens, delivering to the processing plant, rather than delivering "
        "smolt to the pens). Steaming phases derive fuel from speed (fuel "
        "burn scales roughly with speed cubed — hull resistance physics, "
        "hence 'almost double' going from 9 to 11 knots); Stationary "
        "phases (loading/offloading) use a directly-entered fuel rate "
        "instead, since propulsion physics don't apply while alongside. "
        "An additional flat cost/hour (crew overtime, wear, consumables, "
        "etc.) applies across every phase regardless of type. **Every "
        "number below — speed per Steaming phase, fuel rates, the "
        "exponent, fuel price — is a starting default, not fixed**: try "
        "raising the speed on 'Steam to pens' or 'Steam to processing "
        "plant' to see the cost of running faster flow straight through, "
        "live."
    )

    harvest_gcol1, harvest_gcol2, harvest_gcol3, harvest_gcol4 = st.columns(4)
    with harvest_gcol1:
        spot_harvest_ref_speed_kn = stateful_number_input(
            "Reference speed (knots)", min_value=0.1, value=9.0, step=0.5,
            key="spot_harvest_ref_speed", disabled=locked
        )
    with harvest_gcol2:
        spot_harvest_ref_fuel_lhr = stateful_number_input(
            "Fuel rate @ reference speed (L/hr)", min_value=0.0, value=350.0, step=10.0,
            key="spot_harvest_ref_fuel", disabled=locked
        )
    with harvest_gcol3:
        spot_harvest_speed_exponent = stateful_number_input(
            "Speed → fuel exponent", min_value=1.0, max_value=5.0, value=1.8, step=0.1,
            key="spot_harvest_speed_exp", disabled=locked,
            help="Fuel rate at any speed = reference rate x (speed / reference speed) ^ this exponent. "
                 "3.0 is the standard hull-resistance approximation (fuel roughly triples if speed doubles)."
        )
    with harvest_gcol4:
        spot_harvest_fuel_price = stateful_number_input(
            "Fuel price (NOK/liter)", min_value=0.0, value=12.5, step=0.5,
            key="spot_harvest_fuel_price", disabled=locked
        )
    spot_harvest_additional_opex_hr = nok_input(
        "Additional cost per hour in operation (NOK/hr) — all phases",
        "spot_harvest_additional_opex_hr", 2_000.0,
        key="spot_harvest_additional_opex_input", disabled=locked
    )

    if "spot_harvest_segments" not in st.session_state:
        st.session_state.spot_harvest_segments = [
            {"name": "Steam to pens", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0},
            {"name": "Load fish (5kg)", "type": "Stationary", "duration_hr": 8.0, "speed_kn": 0.0, "fuel_rate_lhr": 50.0},
            {"name": "Steam to processing plant", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0},
            {"name": "Offload fish (5kg)", "type": "Stationary", "duration_hr": 4.0, "speed_kn": 0.0, "fuel_rate_lhr": 50.0},
            {"name": "Others/waiting time", "type": "Stationary", "duration_hr": 4.5, "speed_kn": 0.0, "fuel_rate_lhr": 20.0},
        ]

    def _add_harvest_segment():
        st.session_state.spot_harvest_segments.append(
            {"name": "New phase", "type": "Stationary", "duration_hr": 0.0, "speed_kn": 0.0, "fuel_rate_lhr": 0.0}
        )

    def _remove_harvest_segment(index):
        st.session_state.spot_harvest_segments.pop(index)

    smhdr = st.columns([1.6, 1.1, 0.9, 0.9, 1.1, 0.9, 1.1, 1.1, 1.2, 0.4])
    smhdr[0].markdown("**Phase**")
    smhdr[1].markdown("**Type**")
    smhdr[2].markdown("**Duration (hr)**")
    smhdr[3].markdown("**Speed (kn)**")
    smhdr[4].markdown("**Fuel rate (L/hr)**")
    smhdr[5].markdown("**Fuel (L)**")
    smhdr[6].markdown("**Fuel cost (NOK)**")
    smhdr[7].markdown("**Add'l opex (NOK)**")
    smhdr[8].markdown("**Total cost (NOK)**")

    _harvest_total_hours = 0.0
    _harvest_total_fuel_l = 0.0
    _harvest_total_fuel_cost = 0.0
    _harvest_total_additional_opex = 0.0
    _harvest_total_cost = 0.0

    for si, seg in enumerate(st.session_state.spot_harvest_segments):
        cols = st.columns([1.6, 1.1, 0.9, 0.9, 1.1, 0.9, 1.1, 1.1, 1.2, 0.4])
        with cols[0]:
            seg["name"] = st.text_input(
                "Phase", value=seg["name"], key=f"harvest_seg_name_{si}", label_visibility="collapsed", disabled=locked
            )
        with cols[1]:
            seg["type"] = st.selectbox(
                "Type", ["Steaming", "Stationary"],
                index=0 if seg["type"] == "Steaming" else 1,
                key=f"harvest_seg_type_{si}", label_visibility="collapsed", disabled=locked
            )
        with cols[2]:
            seg["duration_hr"] = st.number_input(
                "Duration (hr)", min_value=0.0, value=seg["duration_hr"], step=0.5,
                key=f"harvest_seg_duration_{si}", label_visibility="collapsed", disabled=locked
            )
        with cols[3]:
            if seg["type"] == "Steaming":
                seg["speed_kn"] = st.number_input(
                    "Speed (kn)", min_value=0.0, value=seg["speed_kn"], step=0.5,
                    key=f"harvest_seg_speed_{si}", label_visibility="collapsed", disabled=locked
                )
            else:
                st.markdown("<div style='padding-top:8px'>—</div>", unsafe_allow_html=True)
        with cols[4]:
            if seg["type"] == "Steaming":
                _fuel_rate_this = spot_harvest_ref_fuel_lhr * (
                    (seg["speed_kn"] / spot_harvest_ref_speed_kn) ** spot_harvest_speed_exponent
                    if spot_harvest_ref_speed_kn else 0.0
                )
                st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_rate_this)}</div>", unsafe_allow_html=True)
            else:
                seg["fuel_rate_lhr"] = st.number_input(
                    "Fuel rate (L/hr)", min_value=0.0, value=seg["fuel_rate_lhr"], step=5.0,
                    key=f"harvest_seg_fuelrate_{si}", label_visibility="collapsed", disabled=locked
                )
                _fuel_rate_this = seg["fuel_rate_lhr"]
        with cols[5]:
            _fuel_this = _fuel_rate_this * seg["duration_hr"]
            st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_this)}</div>", unsafe_allow_html=True)
        with cols[6]:
            _fuel_cost_this = _fuel_this * spot_harvest_fuel_price
            st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_cost_this)}</div>", unsafe_allow_html=True)
        with cols[7]:
            _additional_opex_this = spot_harvest_additional_opex_hr * seg["duration_hr"]
            st.markdown(f"<div style='padding-top:8px'>{fmt(_additional_opex_this)}</div>", unsafe_allow_html=True)
        with cols[8]:
            _total_cost_this = _fuel_cost_this + _additional_opex_this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_total_cost_this)}</div>", unsafe_allow_html=True)
        with cols[9]:
            st.button("✕", key=f"harvest_seg_remove_{si}", on_click=_remove_harvest_segment, args=(si,), disabled=locked)

        _harvest_total_hours += seg["duration_hr"]
        _harvest_total_fuel_l += _fuel_this
        _harvest_total_fuel_cost += _fuel_cost_this
        _harvest_total_additional_opex += _additional_opex_this
        _harvest_total_cost += _total_cost_this

    st.button("+ Add phase", key="harvest_add_phase", on_click=_add_harvest_segment, disabled=locked)

    tcols = st.columns([1.6, 1.1, 0.9, 0.9, 1.1, 0.9, 1.1, 1.1, 1.2, 0.4])
    tcols[0].markdown("**Round trip total**")
    tcols[2].markdown(f"**{fmt(_harvest_total_hours)}**")
    tcols[5].markdown(f"**{fmt(_harvest_total_fuel_l)}**")
    tcols[6].markdown(f"**{fmt(_harvest_total_fuel_cost)}**")
    tcols[7].markdown(f"**{fmt(_harvest_total_additional_opex)}**")
    tcols[8].markdown(f"**{fmt(_harvest_total_cost)}**")

    _harvest_days_available = next(
        (item["days_per_year"] for item in spot_service_items_current if item["name"] == "Harvest transport"),
        0.0
    )
    _harvest_hours_available = _harvest_days_available * 24
    _harvest_trips_exact = (_harvest_hours_available / _harvest_total_hours) if _harvest_total_hours else 0.0
    _harvest_trips_whole = int(_harvest_trips_exact)
    _harvest_annual_voyage_cost = _harvest_total_cost * _harvest_trips_exact
    _harvest_implied_day_rate = (_harvest_annual_voyage_cost / _harvest_days_available) if _harvest_days_available else 0.0

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Hours per round trip", fmt(_harvest_total_hours))
    sm2.metric("Trips available (47-day-style window)", f"{_harvest_trips_exact:.1f}", help=f"{_harvest_trips_whole} whole trips + a partial trip, over {fmt(_harvest_days_available)} days available (from the Service mix table).")
    sm3.metric("Implied annual voyage cost (round trips only)", fmt(_harvest_annual_voyage_cost))
    sm4.metric("Implied day-rate (round trips only)", fmt(_harvest_implied_day_rate) + "/day")
    st.caption(
        f"Days available for Harvest: {fmt(_harvest_days_available)} (from the Service mix table above) "
        f"x 24 hr = {fmt(_harvest_hours_available)} hours ÷ {fmt(_harvest_total_hours)} hours/round trip "
        f"= {_harvest_trips_exact:.2f} trips/year."
    )

    st.divider()
    st.markdown("**Customer changeover costs** (per year)")
    st.caption(
        "Separate from the round-trip cost above — these happen per "
        "customer relationship, not per round trip. Customers/year "
        "defaults to 4 here (vs. 8 for Smolt), since harvest activity "
        "takes roughly half the time. 'Intermediate cleans per customer' "
        "defaults to 1 so 4 customers x 1 = 4/year — adjust directly if "
        "needed."
    )

    cc1, cc2 = st.columns(2)
    with cc1:
        spot_harvest_customers_per_year = stateful_number_input(
            "Customers/year", min_value=0.0, value=4.0, step=1.0,
            key="spot_harvest_customers_per_year", disabled=locked
        )
    with cc2:
        _rounds_per_customer = (_harvest_trips_exact / spot_harvest_customers_per_year) if spot_harvest_customers_per_year else 0.0
        st.metric("Rounds per customer (check)", f"{_rounds_per_customer:.1f}", help="Trips available ÷ customers/year — a sanity check on the mix, not a fixed target.")

    cc3, cc4 = st.columns(2)
    with cc3:
        st.markdown("**Deep disinfection**")
        spot_harvest_deep_clean_days = stateful_number_input(
            "Days at yard", min_value=0.0, value=1.0, step=0.5,
            key="spot_harvest_deep_clean_days", disabled=locked
        )
        spot_harvest_yard_cost_per_day = nok_input(
            "Disinfection opex (NOK/day)", "spot_harvest_yard_cost_per_day", 25_000.0,
            key="spot_harvest_yard_cost_input", disabled=locked
        )
        spot_harvest_drydock_cost_per_day = nok_input(
            "Dry-docking cost (NOK/day)", "spot_harvest_drydock_cost_per_day", 75_000.0,
            key="spot_harvest_drydock_cost_input", disabled=locked
        )
        st.caption(
            "Cost/event = days at yard x (disinfection opex/day + dry-docking "
            "cost/day). Once per customer change — frequency = customers/year."
        )
    with cc4:
        st.markdown("**Intermediate clean**")
        spot_harvest_intermediate_clean_hr = stateful_number_input(
            "Duration (hr)", min_value=0.0, value=3.0, step=0.5,
            key="spot_harvest_intermediate_clean_hr", disabled=locked
        )
        spot_harvest_intermediate_cost_per_hr = nok_input(
            "Cost per hour (NOK/hr)", "spot_harvest_intermediate_cost_per_hr", 2_500.0,
            key="spot_harvest_intermediate_cost_input", disabled=locked
        )
        spot_harvest_intermediate_cleans_per_customer = stateful_number_input(
            "Intermediate cleans per customer (0 to skip)", min_value=0.0, value=1.0, step=1.0,
            key="spot_harvest_intermediate_cleans_per_customer", disabled=locked
        )
        st.caption(
            "Cost/event = duration x cost/hour — no dry-dock, no fuel "
            "physics, just a blended operational rate."
        )

    spot_harvest_deep_clean_cost = (
        spot_harvest_deep_clean_days * (spot_harvest_yard_cost_per_day + spot_harvest_drydock_cost_per_day)
    )
    spot_harvest_intermediate_clean_cost = (
        spot_harvest_intermediate_clean_hr * spot_harvest_intermediate_cost_per_hr
    )
    st.caption(
        f"Computed cost per event — Deep disinfection: {fmt(spot_harvest_deep_clean_cost)}, "
        f"Intermediate clean: {fmt(spot_harvest_intermediate_clean_cost)}."
    )

    cc5, cc6 = st.columns(2)
    with cc5:
        spot_harvest_transport_base_hr = stateful_number_input(
            "Transport back to base — duration (hr)", min_value=0.0, value=8.0, step=0.5,
            key="spot_harvest_transport_base_hr", disabled=locked
        )
    with cc6:
        spot_harvest_transport_base_speed = stateful_number_input(
            "Transport back to base — speed (kn)", min_value=0.0, value=spot_harvest_ref_speed_kn, step=0.5,
            key="spot_harvest_transport_base_speed", disabled=locked
        )
    st.caption(
        "Once per customer change — frequency = customers/year. Fuel cost "
        "uses the same speed formula and additional cost/hour as the "
        "round-trip phases above."
    )

    _transport_base_fuel_rate = spot_harvest_ref_fuel_lhr * (
        (spot_harvest_transport_base_speed / spot_harvest_ref_speed_kn) ** spot_harvest_speed_exponent
        if spot_harvest_ref_speed_kn else 0.0
    )
    _transport_base_cost_per_event = (
        (_transport_base_fuel_rate * spot_harvest_transport_base_hr * spot_harvest_fuel_price)
        + (spot_harvest_additional_opex_hr * spot_harvest_transport_base_hr)
    )

    _annual_deep_clean_cost = spot_harvest_customers_per_year * spot_harvest_deep_clean_cost
    _annual_intermediate_clean_cost = (
        spot_harvest_customers_per_year * spot_harvest_intermediate_cleans_per_customer * spot_harvest_intermediate_clean_cost
    )
    _annual_transport_base_cost = spot_harvest_customers_per_year * _transport_base_cost_per_event
    _annual_changeover_cost = _annual_deep_clean_cost + _annual_intermediate_clean_cost + _annual_transport_base_cost

    changeover_df = pd.DataFrame([
        {"Item": "Deep disinfection", "Events/year": spot_harvest_customers_per_year, "Cost/event (NOK)": spot_harvest_deep_clean_cost, "Annual cost (NOK)": _annual_deep_clean_cost},
        {"Item": "Intermediate clean", "Events/year": spot_harvest_customers_per_year * spot_harvest_intermediate_cleans_per_customer, "Cost/event (NOK)": spot_harvest_intermediate_clean_cost, "Annual cost (NOK)": _annual_intermediate_clean_cost},
        {"Item": "Transport back to base", "Events/year": spot_harvest_customers_per_year, "Cost/event (NOK)": _transport_base_cost_per_event, "Annual cost (NOK)": _annual_transport_base_cost},
        {"Item": "Total", "Events/year": None, "Cost/event (NOK)": None, "Annual cost (NOK)": _annual_changeover_cost},
    ])
    show_table(changeover_df, "Item", width="stretch")

    _harvest_total_annual_voyage_cost = _harvest_annual_voyage_cost + _annual_changeover_cost
    _harvest_total_implied_day_rate = (
        _harvest_total_annual_voyage_cost / _harvest_days_available if _harvest_days_available else 0.0
    )

    st.markdown("**Combined total (round trips + customer changeover)**")
    ct1, ct2 = st.columns(2)
    ct1.metric("Total implied annual voyage cost", fmt(_harvest_total_annual_voyage_cost))
    ct2.metric("Total implied day-rate", fmt(_harvest_total_implied_day_rate) + "/day")
    st.caption(
        "This is a build-up tool — the resulting day-rate isn't wired into "
        "the Voyage costs table below yet; once you're happy with both "
        "this and the Smolt build-up above, say so and I'll connect both "
        "into the actual Voyage costs table."
    )

    st.markdown("**Net income check — Harvest transport**")
    st.caption(
        "Links the customer rate set on the Service mix table above "
        "against this build-up's voyage cost, so you can see the "
        "contribution margin move live as you test different rates in "
        "discussion."
    )
    _harvest_charged_rate = next(
        (item["rate_nok_day"] for item in spot_service_items_current if item["name"] == "Harvest transport"),
        0.0
    )
    _harvest_charged_annual_revenue = _harvest_charged_rate * _harvest_days_available
    _harvest_net_income_day = _harvest_charged_rate - _harvest_total_implied_day_rate
    _harvest_net_income_annual = _harvest_charged_annual_revenue - _harvest_total_annual_voyage_cost

    ni1, ni2, ni3, ni4 = st.columns(4)
    ni1.metric("Charged rate (NOK/day)", fmt(_harvest_charged_rate) + "/day")
    ni2.metric("Charged annual revenue (NOK)", fmt(_harvest_charged_annual_revenue))
    ni3.metric("Net income (NOK/day)", fmt(_harvest_net_income_day) + "/day")
    ni4.metric("Net income (NOK/year)", fmt(_harvest_net_income_annual))

    st.divider()
    st.markdown("**Treatment voyage cost build-up** (per round trip)")
    st.caption(
        "Same fuel-speed physics as Smolt/Harvest above. Structure: steam "
        "out to a site (8hr), treat (8hr x however many treatments happen "
        "at that visit — 'typical 1-5', via the Repeats column), steam "
        "home (8hr, disinfection happens during this leg at no extra time "
        "or cost), steam out to a second site (8hr), treat again, steam "
        "home again. Unlike Smolt/Harvest, there's no separate "
        "customer-changeover section here — disinfection is already "
        "embedded in every return-to-base leg, not a discrete event "
        "between customers."
    )

    treatment_gcol1, treatment_gcol2, treatment_gcol3, treatment_gcol4 = st.columns(4)
    with treatment_gcol1:
        spot_treatment_ref_speed_kn = stateful_number_input(
            "Reference speed (knots)", min_value=0.1, value=9.0, step=0.5,
            key="spot_treatment_ref_speed", disabled=locked
        )
    with treatment_gcol2:
        spot_treatment_ref_fuel_lhr = stateful_number_input(
            "Fuel rate @ reference speed (L/hr)", min_value=0.0, value=350.0, step=10.0,
            key="spot_treatment_ref_fuel", disabled=locked
        )
    with treatment_gcol3:
        spot_treatment_speed_exponent = stateful_number_input(
            "Speed → fuel exponent", min_value=1.0, max_value=5.0, value=1.8, step=0.1,
            key="spot_treatment_speed_exp", disabled=locked,
            help="Fuel rate at any speed = reference rate x (speed / reference speed) ^ this exponent."
        )
    with treatment_gcol4:
        spot_treatment_fuel_price = stateful_number_input(
            "Fuel price (NOK/liter)", min_value=0.0, value=12.5, step=0.5,
            key="spot_treatment_fuel_price", disabled=locked
        )
    spot_treatment_additional_opex_hr = nok_input(
        "Additional cost per hour in operation (NOK/hr) — all phases",
        "spot_treatment_additional_opex_hr", 2_000.0,
        key="spot_treatment_additional_opex_input", disabled=locked
    )

    if "spot_treatment_segments" not in st.session_state:
        st.session_state.spot_treatment_segments = [
            {"name": "Steam to site 1", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0, "repeats": 1.0},
            {"name": "Treatment at site 1", "type": "Stationary", "duration_hr": 8.0, "speed_kn": 0.0, "fuel_rate_lhr": 50.0, "repeats": 3.0},
            {"name": "Steam home (incl. disinfection)", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0, "repeats": 1.0},
            {"name": "Steam to site 2", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0, "repeats": 1.0},
            {"name": "Treatment at site 2", "type": "Stationary", "duration_hr": 8.0, "speed_kn": 0.0, "fuel_rate_lhr": 50.0, "repeats": 3.0},
            {"name": "Steam home (incl. disinfection)", "type": "Steaming", "duration_hr": 8.0, "speed_kn": 9.0, "fuel_rate_lhr": 0.0, "repeats": 1.0},
        ]

    def _add_treatment_segment():
        st.session_state.spot_treatment_segments.append(
            {"name": "New phase", "type": "Stationary", "duration_hr": 0.0, "speed_kn": 0.0, "fuel_rate_lhr": 0.0, "repeats": 1.0}
        )

    def _remove_treatment_segment(index):
        st.session_state.spot_treatment_segments.pop(index)

    thdr = st.columns([1.3, 0.9, 0.7, 0.6, 0.7, 0.9, 0.7, 0.8, 0.9, 0.9, 0.9, 0.4])
    thdr[0].markdown("**Phase**")
    thdr[1].markdown("**Type**")
    thdr[2].markdown("**Duration (hr)**")
    thdr[3].markdown("**Repeats**")
    thdr[4].markdown("**Speed (kn)**")
    thdr[5].markdown("**Fuel rate (L/hr)**")
    thdr[6].markdown("**Total hrs**")
    thdr[7].markdown("**Fuel (L)**")
    thdr[8].markdown("**Fuel cost**")
    thdr[9].markdown("**Add'l opex**")
    thdr[10].markdown("**Total cost**")

    _treatment_total_hours = 0.0
    _treatment_total_fuel_l = 0.0
    _treatment_total_fuel_cost = 0.0
    _treatment_total_additional_opex = 0.0
    _treatment_total_cost = 0.0

    for ti, seg in enumerate(st.session_state.spot_treatment_segments):
        cols = st.columns([1.3, 0.9, 0.7, 0.6, 0.7, 0.9, 0.7, 0.8, 0.9, 0.9, 0.9, 0.4])
        with cols[0]:
            seg["name"] = st.text_input(
                "Phase", value=seg["name"], key=f"treatment_seg_name_{ti}", label_visibility="collapsed", disabled=locked
            )
        with cols[1]:
            seg["type"] = st.selectbox(
                "Type", ["Steaming", "Stationary"],
                index=0 if seg["type"] == "Steaming" else 1,
                key=f"treatment_seg_type_{ti}", label_visibility="collapsed", disabled=locked
            )
        with cols[2]:
            seg["duration_hr"] = st.number_input(
                "Duration (hr)", min_value=0.0, value=seg["duration_hr"], step=0.5,
                key=f"treatment_seg_duration_{ti}", label_visibility="collapsed", disabled=locked
            )
        with cols[3]:
            seg["repeats"] = st.number_input(
                "Repeats", min_value=0.0, value=seg.get("repeats", 1.0), step=1.0,
                key=f"treatment_seg_repeats_{ti}", label_visibility="collapsed", disabled=locked
            )
        with cols[4]:
            if seg["type"] == "Steaming":
                seg["speed_kn"] = st.number_input(
                    "Speed (kn)", min_value=0.0, value=seg["speed_kn"], step=0.5,
                    key=f"treatment_seg_speed_{ti}", label_visibility="collapsed", disabled=locked
                )
            else:
                st.markdown("<div style='padding-top:8px'>—</div>", unsafe_allow_html=True)
        with cols[5]:
            if seg["type"] == "Steaming":
                _fuel_rate_this = spot_treatment_ref_fuel_lhr * (
                    (seg["speed_kn"] / spot_treatment_ref_speed_kn) ** spot_treatment_speed_exponent
                    if spot_treatment_ref_speed_kn else 0.0
                )
                st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_rate_this)}</div>", unsafe_allow_html=True)
            else:
                seg["fuel_rate_lhr"] = st.number_input(
                    "Fuel rate (L/hr)", min_value=0.0, value=seg["fuel_rate_lhr"], step=5.0,
                    key=f"treatment_seg_fuelrate_{ti}", label_visibility="collapsed", disabled=locked
                )
                _fuel_rate_this = seg["fuel_rate_lhr"]
        with cols[6]:
            _effective_hours_this = seg["duration_hr"] * seg["repeats"]
            st.markdown(f"<div style='padding-top:8px'>{fmt(_effective_hours_this)}</div>", unsafe_allow_html=True)
        with cols[7]:
            _fuel_this = _fuel_rate_this * _effective_hours_this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_this)}</div>", unsafe_allow_html=True)
        with cols[8]:
            _fuel_cost_this = _fuel_this * spot_treatment_fuel_price
            st.markdown(f"<div style='padding-top:8px'>{fmt(_fuel_cost_this)}</div>", unsafe_allow_html=True)
        with cols[9]:
            _additional_opex_this = spot_treatment_additional_opex_hr * _effective_hours_this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_additional_opex_this)}</div>", unsafe_allow_html=True)
        with cols[10]:
            _total_cost_this = _fuel_cost_this + _additional_opex_this
            st.markdown(f"<div style='padding-top:8px'>{fmt(_total_cost_this)}</div>", unsafe_allow_html=True)
        with cols[11]:
            st.button("✕", key=f"treatment_seg_remove_{ti}", on_click=_remove_treatment_segment, args=(ti,), disabled=locked)

        _treatment_total_hours += _effective_hours_this
        _treatment_total_fuel_l += _fuel_this
        _treatment_total_fuel_cost += _fuel_cost_this
        _treatment_total_additional_opex += _additional_opex_this
        _treatment_total_cost += _total_cost_this

    st.button("+ Add phase", key="treatment_add_phase", on_click=_add_treatment_segment, disabled=locked)

    tcols = st.columns([1.3, 0.9, 0.7, 0.6, 0.7, 0.9, 0.7, 0.8, 0.9, 0.9, 0.9, 0.4])
    tcols[0].markdown("**Round trip total**")
    tcols[6].markdown(f"**{fmt(_treatment_total_hours)}**")
    tcols[7].markdown(f"**{fmt(_treatment_total_fuel_l)}**")
    tcols[8].markdown(f"**{fmt(_treatment_total_fuel_cost)}**")
    tcols[9].markdown(f"**{fmt(_treatment_total_additional_opex)}**")
    tcols[10].markdown(f"**{fmt(_treatment_total_cost)}**")

    _treatment_days_available = next(
        (item["days_per_year"] for item in spot_service_items_current if item["name"] == "Treatment of fish"),
        0.0
    )
    _treatment_hours_available = _treatment_days_available * 24
    _treatment_trips_exact = (_treatment_hours_available / _treatment_total_hours) if _treatment_total_hours else 0.0
    _treatment_annual_voyage_cost = _treatment_total_cost * _treatment_trips_exact
    _treatment_implied_day_rate = (_treatment_annual_voyage_cost / _treatment_days_available) if _treatment_days_available else 0.0

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Hours per round trip", fmt(_treatment_total_hours))
    sm2.metric("Rounds available (166-day-style window)", f"{_treatment_trips_exact:.1f}", help=f"Over {fmt(_treatment_days_available)} days available (from the Service mix table).")
    sm3.metric("Implied annual voyage cost", fmt(_treatment_annual_voyage_cost))
    sm4.metric("Implied day-rate", fmt(_treatment_implied_day_rate) + "/day")
    st.caption(
        f"Days available for Treatment: {fmt(_treatment_days_available)} (from the Service mix table above) "
        f"x 24 hr = {fmt(_treatment_hours_available)} hours ÷ {fmt(_treatment_total_hours)} hours/round trip "
        f"= {_treatment_trips_exact:.2f} rounds/year. This is a build-up tool — the resulting day-rate "
        f"isn't wired into the Voyage costs table below yet; once you're happy with this and the "
        f"Smolt/Harvest build-ups above, say so and I'll connect all three into the actual model."
    )

    st.markdown("**Net income check — Treatment of fish**")
    st.caption(
        "Links the customer rate set on the Service mix table above "
        "against this build-up's voyage cost, so you can see the "
        "contribution margin move live as you test different rates in "
        "discussion."
    )
    _treatment_charged_rate = next(
        (item["rate_nok_day"] for item in spot_service_items_current if item["name"] == "Treatment of fish"),
        0.0
    )
    _treatment_charged_annual_revenue = _treatment_charged_rate * _treatment_days_available
    _treatment_net_income_day = _treatment_charged_rate - _treatment_implied_day_rate
    _treatment_net_income_annual = _treatment_charged_annual_revenue - _treatment_annual_voyage_cost

    ni1, ni2, ni3, ni4 = st.columns(4)
    ni1.metric("Charged rate (NOK/day)", fmt(_treatment_charged_rate) + "/day")
    ni2.metric("Charged annual revenue (NOK)", fmt(_treatment_charged_annual_revenue))
    ni3.metric("Net income (NOK/day)", fmt(_treatment_net_income_day) + "/day")
    ni4.metric("Net income (NOK/year)", fmt(_treatment_net_income_annual))


# ===========================================================================
# TAB 2 — Lease spread (customer lease, with optional bank financing leg)
# ===========================================================================
with tab_lease:
    st.subheader("Leased equipment")
    st.caption(
        "Lease equipment out to the customer alongside the vessel. Optionally "
        "model bank financing for the equipment as well, to see your funding "
        "margin — but the customer lease works independently, whether or not "
        "the equipment is bank-financed."
    )

    toggle_col1, toggle_col2 = st.columns(2)
    with toggle_col1:
        lease_enabled = stateful_toggle(
            "Include customer lease", value=True, key="lease_enabled", disabled=locked
        )
    with toggle_col2:
        bank_financing_enabled = stateful_toggle(
            "Include bank financing", value=True, key="bank_financing_enabled", disabled=locked
        )

    if not lease_enabled:
        st.info(
            "Customer lease is currently **off**. Turn it on to add the "
            "equipment's lease payment to the Combined TC-rate. Inputs below "
            "are still editable so it's ready whenever you switch it on."
        )

    left, right = st.columns([1, 1.4], gap="large")

    with left:
        st.markdown("**Equipment**")
        st.caption(
            "Defaults mirror the vessel's own financing as a starting "
            "point: 65,000,000 capex, 6.7% bank rate, 84-month term/payback "
            "— all independently editable below. In TC mode, the customer "
            "lease payment below applies as configured, underpinned by the "
            "TC-rate. **In spot mode** (see the Spot market tab), there's "
            "no secured lease contract — the customer lease payment is "
            "cancelled entirely (set to zero), while the equipment still "
            "gets bought and bank-financed exactly as configured below; "
            "spot revenue has to cover that bank payment like any other "
            "cost, with no dedicated lease income offsetting it."
        )
        lease_capex_nok = nok_input(
            "Capex (NOK)", "lease_capex_nok", 65_000_000.0, key="lease_capex_input", disabled=locked
        )

        st.markdown("**Customer lease (income)**")
        lease_yield_pct = stateful_number_input(
            "Lease-out rate, annual (%)", min_value=0.0, value=12.0, step=0.1, key="lease_yield", disabled=locked
        )
        customer_term_months = stateful_number_input(
            "Customer lease term (months)", min_value=1, max_value=120, value=60, step=1,
            key="customer_term", disabled=locked
        )
        lease_payback_months = stateful_number_input(
            "Lease payback structure (months)", min_value=1, max_value=180, value=84, step=1,
            key="lease_payback_months", disabled=locked
        )
        st.caption(
            "The monthly rental rate is calculated as if amortizing the full "
            "capex over this payback period — which can be longer than the "
            "customer contract above (e.g. price on a 7-year/84-month "
            "payback even though the contract is only 5 years/60 months). "
            "This produces a lower monthly rate than a 5-year-only "
            "amortization would, but leaves a residual, unrecovered lease "
            "value at the end of the customer term — shown below — which is "
            "the residual-value risk being taken on."
        )
        lease_opex_monthly_nok = nok_input(
            "Additional opex billed to customer (NOK/month)", "lease_opex_monthly_nok",
            50_000.0, key="lease_opex_input", disabled=locked
        )
        st.caption(
            "This opex is billed to the customer on top of the lease payment, "
            "and passes straight through: it adds to revenue (the TC) and to "
            "vessel opex by the same amount, with no net EBITDA impact. The "
            "lease payment itself (above) has no offsetting cost — it flows "
            "100% to EBITDA."
        )

        if bank_financing_enabled:
            st.markdown("**Bank financing (cost)**")
            bank_rate_pct = stateful_number_input(
                "Bank interest rate, annual (%)", min_value=0.0, value=6.7, step=0.1, key="bank_rate", disabled=locked
            )
            bank_term_months = stateful_number_input(
                "Bank loan term (months)", min_value=1, max_value=120, value=84, step=1,
                key="bank_term", disabled=locked
            )
            lease_equity_instalment_nok = nok_input(
                "Equity instalment (NOK)", "lease_equity_instalment_nok", 0.0,
                key="lease_equity_instalment_input", disabled=locked
            )
            st.caption(
                "Portion of the equipment capex funded by equity rather than "
                "the bank. Default 0 = 100% debt-financed. Bank loan principal "
                "= equipment capex − equity instalment."
            )
        else:
            bank_rate_pct = 0.0
            bank_term_months = int(lease_payback_months)  # depreciation basis matches the payback structure, not the shorter customer contract
            lease_equity_instalment_nok = 0.0

    bank_loan_principal = max(0.0, lease_capex_nok - lease_equity_instalment_nok)

    # --- calculations ---
    # Monthly rental rate is priced on the (potentially longer) payback
    # structure, not the customer contract length — see the caption above.
    lease_monthly_payment = annuity_monthly_payment(
        lease_capex_nok, lease_yield_pct, int(lease_payback_months)
    )

    if bank_financing_enabled:
        bank_monthly_payment = annuity_monthly_payment(
            bank_loan_principal, bank_rate_pct, int(bank_term_months)
        )
        monthly_surplus = lease_monthly_payment - bank_monthly_payment
        tail_months = max(0, int(bank_term_months) - int(customer_term_months))
        total_term_months = max(int(customer_term_months), int(bank_term_months))
        total_surplus_active = monthly_surplus * customer_term_months
        total_shortfall_tail = bank_monthly_payment * tail_months
        net_result = total_surplus_active - total_shortfall_tail
    else:
        bank_monthly_payment = 0.0
        monthly_surplus = 0.0
        tail_months = 0
        total_term_months = int(customer_term_months)
        total_surplus_active = 0.0
        total_shortfall_tail = 0.0
        net_result = 0.0

    # --- full monthly schedules, always computed so later tabs can use them.
    # The customer-side schedule runs only for customer_term_months, but the
    # payment itself was priced on the longer lease_payback_months — leaving
    # a genuine residual (unrecovered) balance at the end; see
    # residual_lease_value below. ---
    lease_schedule_full = amortization_schedule_full(
        lease_capex_nok, lease_yield_pct, int(customer_term_months),
        payment_basis_months=int(lease_payback_months)
    )
    residual_lease_value = lease_schedule_full[-1]["Closing balance"] if lease_schedule_full else 0.0
    bank_schedule_full = amortization_schedule_full(
        bank_loan_principal, bank_rate_pct, int(bank_term_months)
    )

    with right:
        if lease_enabled:
            st.subheader("Cash flow — customer lease")
            lease_annual_amt = lease_monthly_payment * 12
            lease_daily_amt = lease_annual_amt / 365
            m1, m2, m3 = st.columns(3)
            m1.metric("Daily", fmt(lease_daily_amt))
            m2.metric("Monthly", fmt(lease_monthly_payment))
            m3.metric("Annual", fmt(lease_annual_amt))

            if int(lease_payback_months) > int(customer_term_months):
                st.warning(
                    f"**Residual value risk: {fmt(residual_lease_value)}.** The "
                    f"rental rate above is priced on a {int(lease_payback_months)}-month "
                    f"payback, but the customer only pays for "
                    f"{int(customer_term_months)} months — leaving this much "
                    f"unrecovered equipment value at the end of the contract, "
                    f"with no further lease income committed against it "
                    f"(unless renewed, re-leased, or sold)."
                )

            st.subheader("Additional opex (pass-through, billed to customer)")
            lease_opex_annual_amt = lease_opex_monthly_nok * 12
            lease_opex_daily_amt = lease_opex_annual_amt / 365
            m1b, m2b, m3b = st.columns(3)
            m1b.metric("Daily", fmt(lease_opex_daily_amt))
            m2b.metric("Monthly", fmt(lease_opex_monthly_nok))
            m3b.metric("Annual", fmt(lease_opex_annual_amt))

            if bank_financing_enabled:
                st.subheader("Cash flow — bank financing")
                bank_annual_amt = bank_monthly_payment * 12
                bank_daily_amt = bank_annual_amt / 365
                m4, m5, m6 = st.columns(3)
                m4.metric("Daily", fmt(bank_daily_amt))
                m5.metric("Monthly", fmt(bank_monthly_payment))
                m6.metric("Annual", fmt(bank_annual_amt))

                st.subheader("Monthly surplus (lease − bank)")
                surplus_annual_amt = monthly_surplus * 12
                surplus_daily_amt = surplus_annual_amt / 365
                m7, m8, m9 = st.columns(3)
                m7.metric("Daily", fmt(surplus_daily_amt))
                m8.metric("Monthly", fmt(monthly_surplus))
                m9.metric("Annual", fmt(surplus_annual_amt))
            else:
                st.caption(
                    "Bank financing is off — the figures above are the lease payment "
                    "received from the customer, with no offsetting financing cost. "
                    "Turn on 'Include bank financing' to see your funding margin."
                )

            # --- schedule chart ---
            lease_balances = amortization_balances(
                lease_capex_nok, lease_yield_pct, int(customer_term_months),
                payment_basis_months=int(lease_payback_months)
            )

            if bank_financing_enabled:
                bank_balances = amortization_balances(
                    bank_loan_principal, bank_rate_pct, int(bank_term_months)
                )
                # Pad with the residual value (not zero) — the unrecovered
                # lease balance doesn't vanish at the end of the customer
                # term, it simply stops being paid down (see the residual
                # value metric above).
                lease_balances_padded = lease_balances + [residual_lease_value] * (total_term_months - len(lease_balances))
                bank_balances_padded = bank_balances + [0.0] * (total_term_months - len(bank_balances))
                schedule_df = pd.DataFrame(
                    {
                        "Month": list(range(1, total_term_months + 1)),
                        "Lease balance (customer)": lease_balances_padded,
                        "Bank balance (loan)": bank_balances_padded,
                    }
                )
                formatted_line_chart(schedule_df, "Month", ["Lease balance (customer)", "Bank balance (loan)"])
            else:
                schedule_df = pd.DataFrame(
                    {
                        "Month": list(range(1, total_term_months + 1)),
                        "Lease balance (customer)": lease_balances,
                    }
                )
                formatted_line_chart(schedule_df, "Month", ["Lease balance (customer)"])

            if bank_financing_enabled and tail_months > 0:
                st.warning(
                    f"**Tail period:** the bank loan continues for **{tail_months} months** "
                    f"after the customer lease ends, with a monthly shortfall of "
                    f"**{fmt(bank_monthly_payment)}** and no offsetting lease income "
                    f"(unless the equipment is re-leased)."
                )

            if bank_financing_enabled:
                st.subheader("Summary over the full term")
                summary_df = pd.DataFrame(
                    [
                        {
                            "Period": f"Months 1–{int(customer_term_months)} (both active)",
                            "Monthly": monthly_surplus,
                            "Total": total_surplus_active,
                        },
                        {
                            "Period": f"Months {int(customer_term_months)+1}–{total_term_months} (tail)"
                                      if tail_months > 0 else "—",
                            "Monthly": -bank_monthly_payment if tail_months > 0 else None,
                            "Total": -total_shortfall_tail if tail_months > 0 else None,
                        },
                        {
                            "Period": f"Net result, full {total_term_months} months",
                            "Monthly": None,
                            "Total": net_result,
                        },
                    ]
                )
                show_table(summary_df, "Period", width="stretch")

            # --- full monthly amortization tables ---
            st.subheader("Amortization schedule — customer lease")
            lease_schedule_df = pd.DataFrame(lease_schedule_full)
            show_table(lease_schedule_df, "Month", width="stretch", height=300)

            if bank_financing_enabled:
                st.subheader("Amortization schedule — bank financing")
                bank_schedule_df = pd.DataFrame(bank_schedule_full)
                show_table(bank_schedule_df, "Month", width="stretch", height=300)

                st.subheader("Spread payment schedule")
                st.caption(
                    "Lease payment received from the customer, less bank payment "
                    "paid, month by month — including any tail period after the "
                    "customer lease ends but the bank loan continues."
                )
                spread_rows = []
                for month in range(1, total_term_months + 1):
                    lease_payment = (
                        lease_schedule_full[month - 1]["Payment"]
                        if month <= int(customer_term_months) else 0.0
                    )
                    bank_payment = (
                        bank_schedule_full[month - 1]["Payment"]
                        if month <= int(bank_term_months) else 0.0
                    )
                    spread_rows.append({
                        "Month": month,
                        "Lease payment (in)": lease_payment,
                        "Bank payment (out)": bank_payment,
                        "Spread": lease_payment - bank_payment,
                    })
                spread_df = pd.DataFrame(spread_rows)
                show_table(spread_df, "Month", width="stretch", height=300)
        else:
            st.markdown("&nbsp;")
            st.markdown(
                "*Results will appear here once leased equipment is switched on.*"
            )

# ===========================================================================
# TAB 3 — Combined TC-rate (vessel + customer lease payment)
# ===========================================================================
with tab_combined:
    st.subheader("Combined TC-rate — vessel + leased equipment")
    st.caption(
        "Every revenue stream, always shown together — TC and lease income "
        "(TC mode), plus Smolt/Harvest/Treatment spot income (spot mode), "
        "each on its own line. Whichever aren't relevant to the current "
        "mode simply show 0, matching exactly what the Financial "
        "Statements P&L does for these same lines. For the detailed "
        "per-service breakdown behind the spot lines, see the Spot market "
        "tab directly."
    )

    if not lease_enabled:
        st.info(
            "Leased equipment is currently **off** (see the Lease spread tab). "
            "The Lease income and Lease opex lines below will show 0."
        )

    active_lease_monthly = lease_monthly_payment if lease_enabled else 0.0
    lease_annual = active_lease_monthly * 12
    lease_daily = lease_annual / operating_days if operating_days else 0

    active_lease_opex_monthly = lease_opex_monthly_nok if lease_enabled else 0.0
    lease_opex_annual = active_lease_opex_monthly * 12
    lease_opex_daily = lease_opex_annual / operating_days if operating_days else 0

    # --- TC-equivalent baseline, kept ALWAYS on TC-mode figures regardless
    # of the spot toggle — this feeds the Spot market tab's own "required
    # rate" benchmark, so it must never reflect spot economics itself
    # (that would make the benchmark circular, measuring spot against
    # spot). This is intentionally separate from the DISPLAY figures below. ---
    total_tc_annual = vessel_tc_annual + lease_annual + lease_opex_annual
    total_tc_daily = vessel_tc_daily + lease_daily + lease_opex_daily
    total_tc_monthly = vessel_tc_monthly + active_lease_monthly + active_lease_opex_monthly

    # --- stored for the Spot market tab's baseline reference, which runs
    # BEFORE this tab in script order (same one-pass-behind convention used
    # elsewhere in the app, e.g. Tab 1's Sources & Uses guideline) ---
    st.session_state["_combined_tc_daily"] = total_tc_daily

    # --- the six lines: TC/Lease/Lease-opex only nonzero in TC mode
    # (matching the P&L's TC-revenue/Lease-revenue/Pass-through costs
    # lines, all of which are cancelled under spot mode); Smolt/Harvest/
    # Treatment only nonzero in spot mode. Each segment's revenue uses the
    # same pure manual/baseline-gross rate as the corrected P&L calc — no
    # price-list addition. ---
    def _segment_annual(service_name):
        item = next((it for it in spot_service_items_current if it["name"] == service_name), None)
        if item is None:
            return 0.0
        rate = required_gross_rate_at_utilization if item["priced_at_baseline"] else item["rate_nok_day"]
        return rate * item["days_per_year"]

    _tc_income_annual = vessel_tc_annual if not spot_market_enabled else 0.0
    _lease_income_annual = lease_annual if (lease_enabled and not spot_market_enabled) else 0.0
    _lease_opex_annual_line = lease_opex_annual if (lease_enabled and not spot_market_enabled) else 0.0
    _smolt_spot_annual = _segment_annual("Smolt transport") if spot_market_enabled else 0.0
    _harvest_spot_annual = _segment_annual("Harvest transport") if spot_market_enabled else 0.0
    _treatment_spot_annual = _segment_annual("Treatment of fish") if spot_market_enabled else 0.0

    _line_items = [
        ("TC income", _tc_income_annual),
        ("Lease income", _lease_income_annual),
        ("Lease-opex pass-through", _lease_opex_annual_line),
        ("Smolt spot", _smolt_spot_annual),
        ("Harvest spot", _harvest_spot_annual),
        ("Treatment spot", _treatment_spot_annual),
    ]

    _display_total_annual = sum(v for _, v in _line_items)
    _display_total_daily = _display_total_annual / operating_days if operating_days else 0
    _display_total_monthly = _display_total_annual / 12

    combined_df = pd.DataFrame(
        [
            {
                "Component": name,
                "Daily": annual / operating_days if operating_days else 0,
                "Monthly": annual / 12,
                "Annual": annual,
            }
            for name, annual in _line_items
        ] + [
            {
                "Component": "TOTAL",
                "Daily": _display_total_daily,
                "Monthly": _display_total_monthly,
                "Annual": _display_total_annual,
            },
        ]
    )
    show_table(combined_df, "Component", width="stretch")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total, daily", fmt(_display_total_daily))
    m2.metric("Total, monthly", fmt(_display_total_monthly))
    m3.metric("Total, annual", fmt(_display_total_annual))

    if not spot_market_enabled:
        st.caption(
            "**Note:** if the customer lease term is shorter than the bank loan term "
            "(see the Lease spread tab), this combined figure reflects the period "
            "while the lease is active. During any tail period, the vessel's TC-rate "
            "no longer includes the equipment lease payment, but the bank loan "
            "obligation continues separately."
        )
    else:
        st.caption(
            "**Note:** in spot mode, the customer lease payment is cancelled "
            "entirely (see the Lease spread tab) — the equipment is still "
            "bank-financed as configured, but spot revenue has to cover "
            "that cost with no dedicated lease income offsetting it."
        )

# ===========================================================================
# TAB 4 — Financial Statements (monthly & annual, horizontal layout)
# ===========================================================================
with tab_financials:
    def _escalation_factor(rate_pct, month):
        """Pure function, no dependencies on anything else in this tab —
        defined first, before anything else, since _get_vessel_revenue
        (defined further down) calls this internally, and gets called
        itself from the Contract summary block before the rest of this
        tab's variables exist. A previous version of this bug (the same
        ordering issue, for spot_segment_revenue_monthly_base) was already
        fixed once; this is the same class of issue for this function."""
        year_number = (month - 1) // 12 + 1  # Year 1 = months 1-12
        escalation_periods = year_number - 1  # 0 in Year 1, 1 in Year 2 (month 13+), ...
        return (1 + rate_pct / 100) ** escalation_periods

    def _utilization_ratio_for_month(month):
        """Utilization for this month's year, relative to Year 1's
        baseline (the top-level Utilization input — Year 1 has no
        separate entry here, avoiding two editable copies of the same
        number). Year 2-12 come from the Year 2-12 planning row (no
        smooth escalation, no staging — each year just holds whatever
        value was typed for it). Years beyond 12 hold at Year 12's value."""
        year = (month - 1) // 12 + 1
        if year <= 1:
            return 1.0
        year_idx = min(year, 12) - 2  # year 2 -> index 0
        active_util = spot_utilization_by_year[year_idx]
        return (active_util / spot_utilization_pct) if spot_utilization_pct else 1.0

    def _fixed_opex_nominal_monthly(month):
        """Fixed Voyage opex, nominal, for this month. Year 1 uses the
        top-level Fixed Voyage opex input directly (no escalation). Years
        2-12 use that specific year's own real (today's money) value from
        the Year 1-12 planning table, run through the SAME single Fixed
        Voyage opex escalator using the standard Year-1-based factor (not
        a new clock starting from when that year's value was set) — e.g.
        a real value typed for Year 3 is multiplied by (1+esc)^2, exactly
        as if it had been the real figure since Year 1. Years beyond 12
        hold at Year 12's real value, still escalating each year."""
        year = (month - 1) // 12 + 1
        if year <= 1:
            real_value = spot_opex_annual_nok
        else:
            year_idx = min(year, 12) - 2  # year 2 -> index 0, clamp beyond 12 at year 12's value
            real_value = spot_fixed_opex_real_by_year[year_idx]
        return real_value * _escalation_factor(spot_opex_escalator_pct, month) / 12

    _segment_escalator_by_year_lookup = {
        "Smolt transport": spot_smolt_escalator_by_year,
        "Harvest transport": spot_harvest_escalator_by_year,
        "Treatment of fish": spot_treatment_escalator_by_year,
    }

    def _maintenance_capex_depreciation_for_month(month):
        """Straight-line depreciation on every maintenance capex vintage
        incurred so far — one vintage per year (Tab 1's annual maintenance
        capex, escalated), each depreciating at the VESSEL's own
        depreciation rate (Tab 1) starting from its own year — same
        'each addition gets its own clock' principle used for TC
        contract renewals elsewhere in this model. Applies unconditionally
        in both TC and spot mode, since the vessel needs maintenance
        either way. This is what's missing from simply capitalizing
        maintenance capex into vessel NBV without ever depreciating it
        back down."""
        year = (month - 1) // 12 + 1
        total_dep = 0.0
        for vintage_year in range(1, min(year, 12) + 1):
            vintage_start_month = (vintage_year - 1) * 12 + 1
            if month < vintage_start_month:
                continue
            _maint_this_vintage = annual_maintenance_capex_nok * _escalation_factor(maintenance_escalator_pct, vintage_start_month)
            total_dep += _maint_this_vintage * (depreciation_rate_pct / 100) / 12
        return total_dep

    def _additional_spot_capex_nominal_for_vintage(vintage_year):
        """Additional spot capex's NOMINAL value for a given vintage year
        — the real (today's money) figure typed on the Spot market tab,
        run through the maintenance capex escalator (Tab 1) using the
        standard Year-1-based factor, same treatment as Fixed Voyage
        opex's real-to-nominal conversion. Uses the maintenance escalator
        specifically since Additional spot capex sits 'on top of'
        maintenance capex in the asset register — both are capex
        additions to the same vessel, so both index the same way."""
        if vintage_year < 2:
            return 0.0
        _real_value = spot_additional_capex_by_year[vintage_year - 2]
        _vintage_start_month = (vintage_year - 1) * 12 + 1
        return _real_value * _escalation_factor(maintenance_escalator_pct, _vintage_start_month)

    def _additional_spot_capex_depreciation_for_month(month):
        """Straight-line depreciation on every Additional spot capex
        vintage incurred so far (Spot market tab's Year 2-12 planning
        table, spot mode only) — each vintage's NOMINAL value (real value
        escalated from its own start year) depreciates at its OWN rate
        (Additional spot capex depreciation rate, default 5%/yr =
        20-year life), separate from the vessel/maintenance capex rate,
        since spot-specific capex may genuinely have a different useful
        life."""
        if not spot_market_enabled:
            return 0.0
        year = (month - 1) // 12 + 1
        total_dep = 0.0
        for vintage_year in range(2, min(year, 12) + 1):
            vintage_start_month = (vintage_year - 1) * 12 + 1
            if month < vintage_start_month:
                continue
            _add_capex_this_vintage = _additional_spot_capex_nominal_for_vintage(vintage_year)
            total_dep += _add_capex_this_vintage * (spot_additional_capex_depreciation_pct / 100) / 12
        return total_dep

    def _segment_revenue_multiplier(segment_name, month):
        """Cumulative compounding multiplier for a segment's revenue,
        relative to its Year 1 rate — each year has its OWN escalator %
        (from the Year 1-12 planning table), not one flat rate, so this
        multiplies together every year's own factor from Year 2 through
        the target year. Years beyond 12 stop compounding further (hold
        at Year 12's cumulative multiplier)."""
        year = (month - 1) // 12 + 1
        year_capped = min(year, 12)
        if year_capped <= 1:
            return 1.0
        escalator_list = _segment_escalator_by_year_lookup.get(segment_name)
        if escalator_list is None:
            return 1.0
        multiplier = 1.0
        for y in range(2, year_capped + 1):
            multiplier *= (1 + escalator_list[y - 2] / 100)
        return multiplier


    st.subheader("Financial statements — vessel + leased equipment")
    st.caption(
        "P&L, cash flow, and balance sheet, laid out horizontally (line items "
        "down the rows, periods across the columns) — toggle Monthly / Annual "
        "within each statement below. Combines the vessel (Tab 1) with the "
        "leased equipment (Tab 2), when switched on. The lease payment "
        "received from the customer flows 100% to EBITDA (no offsetting "
        "cost); the additional opex billed to the customer is a pass-through "
        "(net-zero EBITDA impact); equipment financing (leasing company) is "
        "treated the same way as the vessel's own bank debt, shown as a "
        "separate line throughout. Depreciation is split into two lines: "
        "the vessel depreciates straight-line at the rate set on Tab 1 (% "
        "of original capex per year); leased equipment depreciates "
        "straight-line over the same number of months as its own financing "
        "term (Tab 2), reaching zero NBV once that term ends. Maintenance "
        "capex is capitalized (investing outflow, added to the vessel's "
        "balance sheet value) rather than expensed. The cash flow statement "
        "is an EBITDA-down bridge: EBITDA, less working capital build (from "
        "DSO/DPO), less finance cost, less tax, less amortization and "
        "maintenance capex, leaves cash flow for the period."
    )

    st.subheader("Working capital & tax assumptions")
    wc_col1, wc_col2, wc_col3 = st.columns(3)
    with wc_col1:
        dso_days = stateful_number_input(
            "Days sales outstanding (DSO)", min_value=0, value=30, step=1, key="dso_days", disabled=locked
        )
    with wc_col2:
        dpo_days = stateful_number_input(
            "Days payable outstanding (DPO)", min_value=0, value=20, step=1, key="dpo_days", disabled=locked
        )
    with wc_col3:
        tax_rate_pct = stateful_number_input(
            "Corporate tax rate (%)", min_value=0.0, value=0.0, step=0.5, key="tax_rate", disabled=locked
        )
        st.caption("Default 0% — Norwegian Tonnage Tax regime.")

    st.subheader("Escalators (annual, first adjustment in month 13)")
    st.caption(
        "Each rate compounds once per year starting in month 13 (i.e. Year 2 "
        "onward) — months 1–12 stay at the base level."
    )
    esc_col1, esc_col2, esc_col3 = st.columns(3)
    with esc_col1:
        tc_escalator_pct = stateful_number_input(
            "TC revenue escalator (%/yr)", min_value=-100.0, value=2.0, step=0.5, key="tc_escalator", disabled=locked
        )
        lease_escalator_pct = stateful_number_input(
            "Lease payment escalator (%/yr)", min_value=-100.0, value=0.0, step=0.5, key="lease_escalator", disabled=locked
        )
    with esc_col2:
        maintenance_escalator_pct = stateful_number_input(
            "Maintenance capex escalator (%/yr)", min_value=-100.0, value=2.0, step=0.5,
            key="maintenance_escalator", disabled=locked
        )

    st.markdown("**Vessel opex escalators**")
    opex_escalator_pcts = []
    esc_cols = st.columns(min(len(st.session_state.opex_items), 4) or 1)
    for i, item in enumerate(st.session_state.opex_items):
        default_esc = 3.0 if item["name"].strip().lower() == "crewing" else 2.0
        col = esc_cols[i % len(esc_cols)]
        with col:
            esc_pct = stateful_number_input(
                f"{item['name']} (%/yr)", min_value=-100.0, value=default_esc, step=0.5,
                key=f"opex_escalator_{i}", disabled=locked
            )
        opex_escalator_pcts.append(esc_pct)

    st.subheader("Debt refinancing (vessel)")
    st.caption(
        "Refinance the vessel debt at two points, releveraging to a multiple "
        "of the coming year's projected EBITDA — same interest rate (swap + "
        "spread) and amortization profile as the initial debt. Any excess "
        "over the outstanding balance at that point is released as cash."
    )
    refinancing_enabled = stateful_toggle(
        "Enable debt refinancing", value=True, key="refinancing_enabled", disabled=locked
    )
    if refinancing_enabled:
        refi_col1, refi_col2, refi_col3 = st.columns(3)
        with refi_col1:
            refi_year1 = stateful_number_input(
                "First refinancing (year)", min_value=1, value=4, step=1, key="refi_year1", disabled=locked
            )
        with refi_col2:
            refi_year2 = stateful_number_input(
                "Second refinancing (year)", min_value=1, value=8, step=1, key="refi_year2", disabled=locked
            )
        with refi_col3:
            releverage_multiple = stateful_number_input(
                "Releverage multiple (x next year's EBITDA)", min_value=0.0,
                value=float(debt_multiple), step=0.5, key="releverage_multiple", disabled=locked
            )
        st.caption(
            f"E.g. with defaults: refinance in year {int(refi_year1)}, releveraging to "
            f"{releverage_multiple:.1f}x Year {int(refi_year1)+1}'s projected vessel EBITDA; "
            f"same again in year {int(refi_year2)}, releveraging to Year {int(refi_year2)+1}'s."
        )
        refi_trigger_months = {int(refi_year1) * 12 + 1, int(refi_year2) * 12 + 1}
    else:
        refi_trigger_months = set()
        releverage_multiple = debt_multiple

    # --- horizon: covers vessel debt, and if the lease is on, its customer
    #     and bank terms too, so nothing gets truncated ---
    horizon_months = amortization_months
    if lease_enabled:
        horizon_months = max(horizon_months, int(customer_term_months))
        if bank_financing_enabled:
            horizon_months = max(horizon_months, int(bank_term_months))

    monthly_revenue_vessel_base = vessel_tc_monthly  # only meaningful in TC mode — see the info box below

    st.subheader("TC contract schedule")
    if spot_market_enabled:
        st.info(
            "Spot market is active — this contract schedule is now fully "
            "inactive. Treatment, Smolt, and Harvest revenue are each "
            "tracked directly (Service mix table + their own build-up "
            "tools where available), escalating at their own flat rate "
            "indefinitely — see the Spot market tab. This section (and "
            "the TC revenue escalator/renewals below) only drives the "
            "'TC-revenue' line, which applies in TC mode."
        )
    st.caption(
        "Define the initial contract length and up to 3 renewals over the "
        "horizon. Each new contract starts its own escalation clock — first "
        "adjustment 12 months after that contract begins — using the TC "
        "revenue escalator above. Leave a renewal's length at 0 to skip it; "
        "the final segment automatically runs to the end of the horizon. "
        "Optionally, a capex upgrade or downgrade can be applied at the same "
        "month as each renewal (e.g. equipment added or removed alongside a "
        "new charter) — positive adds to the vessel's book value and is an "
        "investing cash outflow; negative reduces book value and returns cash."
    )

    c1a, c1b = st.columns(2)
    with c1a:
        contract1_length = stateful_number_input(
            "Contract 1 length (months)", min_value=1, value=60,
            step=1, key="contract1_length", disabled=locked
        )
    with c1b:
        st.markdown(f"Rate: vessel TC-rate from Tab 1 ({fmt(monthly_revenue_vessel_base)}/month)")

    def _revenue_for_contracts(contracts_so_far, month):
        """Same lookup as _get_vessel_revenue below, but against a partial
        contracts list — used to compute the LTM yardstick using only
        contracts already known at that point in the form."""
        contract = contracts_so_far[-1]
        for c in contracts_so_far:
            if c["start"] <= month < c["start"] + c["length"]:
                contract = c
                break
        months_into = month - contract["start"] + 1
        periods = (months_into - 1) // 12
        factor = (1 + tc_escalator_pct / 100) ** periods
        return contract["base_monthly"] * factor

    tc_contracts = [{
        "start": 1, "length": int(contract1_length),
        "base_monthly": monthly_revenue_vessel_base, "capex_delta": 0.0,
    }]
    next_start = int(contract1_length) + 1

    # Default renewal schedule: Contract 2 after 36 months at 140m/yr (+10m
    # capex), Contract 3 after a further 24 months at 149m/yr (no capex
    # change), Contract 4 at 155m/yr (+5m capex) running to the horizon.
    _contract_defaults = {
        2: {"length": 36, "rate": 140_000_000.0, "capex": 10_000_000.0},
        3: {"length": 24, "rate": 149_000_000.0, "capex": 0.0},
        4: {"length": None, "rate": 155_000_000.0, "capex": 5_000_000.0},
    }

    contract_renewals = []
    for i in (2, 3, 4):
        upcoming_start = next_start

        # --- LTM yardstick: last 12 months' vessel TC-revenue, using only
        #     the contracts already defined up to this renewal ---
        if upcoming_start > 12:
            ltm_start_month = upcoming_start - 12
            ltm_end_month = upcoming_start - 1
            ltm_total = sum(
                _revenue_for_contracts(tc_contracts, m)
                for m in range(ltm_start_month, ltm_end_month + 1)
            )
            st.caption(
                f"📊 **LTM TC-revenue before Contract {i}** (months {ltm_start_month}–{ltm_end_month}): "
                f"{fmt(ltm_total)} — use this as a yardstick for the new rate."
            )
        else:
            st.caption(
                f"Not enough history yet for a full LTM figure before Contract {i} "
                f"(it would start month {upcoming_start})."
            )

        rcol1, rcol2, rcol3 = st.columns(3)
        with rcol1:
            if i < 4:
                length = stateful_number_input(
                    f"Contract {i} length (months) — 0 to skip", min_value=0,
                    value=_contract_defaults[i]["length"],
                    step=1, key=f"contract{i}_length", disabled=locked
                )
            else:
                length = None  # contract 4 always runs to the end of the horizon
                st.markdown("Contract 4 runs to the end of the horizon (if reached)")
        with rcol2:
            new_annual_rate = nok_input(
                f"Contract {i} new TC-rate (NOK/year)", f"contract{i}_rate_nok",
                _contract_defaults[i]["rate"], key=f"contract{i}_rate_input", disabled=locked
            )
        with rcol3:
            capex_delta = nok_input(
                f"Contract {i} capex adjustment (NOK)", f"contract{i}_capex_delta_nok",
                _contract_defaults[i]["capex"], key=f"contract{i}_capex_delta_input", disabled=locked
            )
        contract_renewals.append({"length": length, "new_annual_rate": new_annual_rate, "capex_delta": capex_delta})

        # extend the known contracts list so the NEXT renewal's LTM sees this one
        if i < 4:
            length_int = int(length)
            if length_int > 0 and upcoming_start <= horizon_months:
                new_monthly = new_annual_rate / 12
                tc_contracts.append({
                    "start": upcoming_start, "length": length_int,
                    "base_monthly": new_monthly, "capex_delta": capex_delta,
                })
                next_start = upcoming_start + length_int
        else:
            remaining = horizon_months - (upcoming_start - 1)
            if remaining > 0:
                new_monthly = new_annual_rate / 12
                tc_contracts.append({
                    "start": upcoming_start, "length": remaining,
                    "base_monthly": new_monthly, "capex_delta": capex_delta,
                })

    # Capex adjustment applied exactly once, at each renewal's start month
    # (contract 1 never has one — it's the vessel's original capex).
    capex_delta_by_month = {
        c["start"]: c["capex_delta"] for c in tc_contracts[1:] if c["capex_delta"] != 0.0
    }

    # --- per-segment revenue basis (Treatment/Smolt/Harvest), kept
    # explicit per segment so the P&L can show each segment's revenue on
    # its own line. Each segment escalates at its own flat rate
    # indefinitely (the escalator_pct already sitting on that service
    # row), independent of the TC contract-renewal mechanism, which now
    # only drives the TC-mode 'TC-revenue' line. Uses the pure manual (or
    # baseline-gross) rate only — no price-list addition — matching each
    # segment's own build-up tool and Net income check on the Spot tab.
    # Defined here (early) because _get_vessel_revenue below needs it, and
    # that function gets called from the Contract summary block further
    # down — before the main monthly loop even runs. ---
    spot_segment_revenue_monthly_base = []
    for s_idx, item in enumerate(spot_service_items_current):
        _seg_rate = required_gross_rate_at_utilization if item["priced_at_baseline"] else item["rate_nok_day"]
        spot_segment_revenue_monthly_base.append({
            "name": item["name"],
            "monthly_base": _seg_rate * item["days_per_year"] / 12,
            "escalator_pct": item["escalator_pct"],
        })

    def _get_vessel_revenue(month):
        """Base monthly revenue for this month. TC mode: from the active
        contract (escalated from that contract's own start — first
        adjustment 12 months in). Spot mode: sum of Treatment/Smolt/
        Harvest revenue, each escalating according to its own per-year
        escalator schedule (Year 1-12 planning table — each year has its
        own %, compounding), scaled by that year's utilization relative
        to Year 1's baseline — used here as a convenient 'total vessel
        revenue' figure for refinancing and terminal-value projections;
        the main monthly loop tracks each segment individually and
        explicitly for the P&L."""
        if spot_market_enabled:
            _util_factor = _utilization_ratio_for_month(month)
            return sum(
                item["monthly_base"] * _segment_revenue_multiplier(item["name"], month) * _util_factor
                for item in spot_segment_revenue_monthly_base
            )
        return _revenue_for_contracts(tc_contracts, month)

    def _get_vessel_opex(month):
        """Vessel opex for this month: Tab 1's fixed crewing/opex items
        (applies every calendar day, unconditional on utilization — crew
        salaries don't stop when idle, and the vessel needs a crew
        whether trading TC or spot), plus, in spot mode, Fixed Voyage
        opex on top (that year's own real value, escalated the standard
        way) — Fixed Voyage opex is additional overhead specific to
        running the spot-trade business, not a replacement for crewing."""
        _crew_and_other_opex = sum(
            item["monthly"] * _escalation_factor(item["escalator_pct"], month)
            for item in opex_line_items_base
        )
        if spot_market_enabled:
            return _crew_and_other_opex + _fixed_opex_nominal_monthly(month)
        return _crew_and_other_opex

    if len(tc_contracts) > 1:
        st.markdown("**Contract summary** (annualized rate, and uplift vs. the TC-rate just before renewal)")
        for i, c in enumerate(tc_contracts):
            annual_rate = c["base_monthly"] * 12
            if i == 0:
                st.markdown(
                    f"- Contract 1 (months {c['start']}–{c['start']+c['length']-1}): "
                    f"{fmt(c['base_monthly'])}/month · {fmt(annual_rate)}/year"
                )
            else:
                prev_rate_monthly = _get_vessel_revenue(c["start"] - 1)
                uplift_pct = (c["base_monthly"] / prev_rate_monthly - 1) * 100 if prev_rate_monthly else 0.0
                end_label = c["start"] + c["length"] - 1
                st.markdown(
                    f"- Contract {i+1} (months {c['start']}–{end_label}): "
                    f"{fmt(c['base_monthly'])}/month · {fmt(annual_rate)}/year "
                    f"— uplift vs. prior rate: **{uplift_pct:+.1f}%**"
                )

    monthly_opex_vessel_base = opex_total / 12
    monthly_vessel_depreciation = (capex_nok * (depreciation_rate_pct / 100)) / 12
    monthly_maintenance_base = annual_maintenance_capex_nok / 12

    opex_line_items_base = [
        {"name": item["name"], "monthly": item["value_nok"] / 12, "escalator_pct": esc}
        for item, esc in zip(st.session_state.opex_items, opex_escalator_pcts)
    ]

    # --- spot market basis: voyage costs/recovery scale with working days
    # (idle days don't incur fuel/port fees), unchanged regardless of the
    # revenue-side simplification above. Vessel opex (crewing — Tab 1)
    # stays fixed on the full operating_days basis in TC mode; in spot
    # mode it's a fixed ANNUAL budget (spot_opex_annual_nok) spread evenly
    # across months — NOT tied to working days here, since the annual
    # figure is the true fixed input; only its day-rate equivalent (shown
    # on the Spot tab) derives from working days. ---
    spot_working_days_annual = sum(item["days_per_year"] for item in spot_service_items_current)
    spot_opex_monthly_base = spot_opex_annual_nok / 12

    # --- per-segment voyage cost basis. Treatment, Smolt, and Harvest all
    # now source their direct voyage cost from their own phase-by-phase
    # build-up tools above (fuel physics, cleaning, customer changeover) —
    # all three now fully self-contained, no generic fallback table needed
    # anymore. ---
    _treatment_idx = next(
        (i for i, it in enumerate(spot_service_items_current) if it["name"] == "Treatment of fish"), None
    )
    _smolt_idx_lookup = next(
        (i for i, it in enumerate(spot_service_items_current) if it["name"] == "Smolt transport"), None
    )
    _harvest_idx_lookup = next(
        (i for i, it in enumerate(spot_service_items_current) if it["name"] == "Harvest transport"), None
    )

    spot_treatment_cost_monthly_base = _treatment_annual_voyage_cost / 12
    spot_treatment_cost_escalator_pct = spot_variable_opex_escalator_pct
    spot_smolt_cost_monthly_base = _smolt_total_annual_voyage_cost / 12
    spot_smolt_cost_escalator_pct = spot_variable_opex_escalator_pct
    spot_harvest_cost_monthly_base = _harvest_total_annual_voyage_cost / 12
    spot_harvest_cost_escalator_pct = spot_variable_opex_escalator_pct

    equipment_capex = lease_capex_nok if lease_enabled else 0.0
    equipment_debt_initial = bank_loan_principal if (lease_enabled and bank_financing_enabled) else 0.0
    equipment_equity_initial = equipment_capex - equipment_debt_initial

    # Equipment is depreciated straight-line over the same number of months
    # as its financing term (bank_term_months) — whether or not bank
    # financing is actually switched on, since bank_term_months already
    # falls back to the customer lease term in that case (see Tab 2).
    equipment_depreciation_months = int(bank_term_months) if (lease_enabled and equipment_capex > 0) else 0
    monthly_equipment_depreciation = (
        equipment_capex / equipment_depreciation_months if equipment_depreciation_months else 0.0
    )

    if not spot_market_enabled and monthly_revenue_vessel_base < (monthly_opex_vessel_base + debt_schedule[0]["Monthly finance cost"]):
        st.warning(
            "**Note:** the vessel TC-rate (Tab 1) is built from required EBITDA + "
            "vessel opex only — it does not include debt finance cost or tax. "
            "Depending on your inputs, monthly revenue may not fully cover opex + "
            "finance cost + tax; check the P&L for negative net income if that "
            "matters for your analysis."
        )
    elif spot_market_enabled:
        st.caption(
            "ℹ️ Spot market is active — vessel revenue and voyage costs below "
            "come from the Spot market tab, not the TC-rate on Tab 1 (Tab 1's "
            "capex/debt sizing still applies)."
        )

    def _row_or_zero(schedule, month, term_months):
        if month <= term_months and month <= len(schedule):
            return schedule[month - 1]
        return {"Finance cost": 0.0, "Amortization": 0.0, "Closing balance": 0.0}

    # --- operational funding, decided on Tab 1's Sources & Uses (runs earlier
    #     in the script, so this is already set for the current pass) ---
    _op_funding = st.session_state.get("_operational_funding", {"equity": 0.0, "debt": 0.0})
    operational_equity_nok = _op_funding["equity"]
    operational_debt_nok = _op_funding["debt"]

    vessel_equity_initial = capex_nok - debt_nok

    def _run_monthly_model(op_equity_nok, op_debt_nok):
        """Runs the full monthly P&L / cash flow / balance sheet model for a
        given operational-funding split. Pulled into a function so it can be
        run twice: once with whatever funding the user actually chose (for
        the real statements and IRR), and once forced to zero funding, purely
        to read off a stable, funding-independent guideline — see the call
        site below for why that removes the circularity entirely rather than
        iterating toward it."""
        pnl_rows_ = []
        cf_rows_ = []
        bs_rows_ = []

        cumulative_cash = op_equity_nok + op_debt_nok  # injected upfront, month 0
        cumulative_vessel_depreciation = 0.0
        cumulative_equipment_depreciation = 0.0
        cumulative_maintenance_capex = 0.0
        cumulative_additional_spot_capex = 0.0
        cumulative_maintenance_capex_depreciation = 0.0
        cumulative_additional_capex_depreciation = 0.0
        cumulative_capex_adjustment = 0.0
        equity = vessel_equity_initial + equipment_equity_initial + op_equity_nok

        bs_rows_.append({
            "Month": 0,
            "Vessel (NBV)": capex_nok,
            "Leased equipment (NBV)": equipment_capex,
            "Accounts receivable": 0.0,
            "Cash": cumulative_cash,
            "Total assets": capex_nok + equipment_capex + cumulative_cash,
            "Debt — vessel (bank)": debt_nok,
            "Debt — equipment (leasing company)": equipment_debt_initial,
            "Debt — operational funding": op_debt_nok,
            "Accounts payable": 0.0,
            "Equity": equity,
            "Total liabilities + equity": debt_nok + equipment_debt_initial + op_debt_nok + equity,
        })

        # --- month 0 on the cash flow statement: the operational funding
        # injected upfront (equity + debt), before month 1's operations begin.
        # Shown here so it's possible to see, side by side, the opening cash
        # available going into month 1 — and to compare "Cash flow for the
        # period" month-by-month with and without covering the liquidity gap,
        # since none of the other flow lines depend on this injection (see
        # "Cash flow for the period" below, month 1 onward, which is
        # independent of operational funding whenever it's debt-free).
        cf_rows_.append({
            "Month": 0,
            "EBITDA": 0.0,
            "Working capital change": 0.0,
            "Finance cost — vessel (bank)": 0.0,
            "Finance cost — equipment (leasing company)": 0.0,
            "Finance cost — operational funding": 0.0,
            "Tax": 0.0,
            "Amortization — vessel (bank)": 0.0,
            "Amortization — equipment (leasing company)": 0.0,
            "Amortization — operational funding": 0.0,
            "Maintenance capex": 0.0,
            "Additional spot capex": 0.0,
            "Capex adjustment (vessel upgrade/downgrade)": 0.0,
            "Refinancing proceeds (vessel)": 0.0,
            "Operational funding injected (equity + debt)": op_equity_nok + op_debt_nok,
            "Cash flow for the period": op_equity_nok + op_debt_nok,
            "Cash balance": cumulative_cash,
        })

        prev_nwc = 0.0
        vessel_debt_balance = debt_nok
        vessel_quarterly_amort = quarterly_amortization_nok
        vessel_cycle_month = 0
        vessel_monthly_rate = (finance_cost_rate_pct / 100) / 12

        operational_debt_balance = op_debt_nok
        operational_quarterly_amort = op_debt_nok / (amortization_years * 4) if amortization_years else 0.0
        operational_cycle_month = 0

        for month in range(1, horizon_months + 1):
            vessel_cycle_month += 1
            operational_cycle_month += 1
            refinancing_proceeds_this_month = 0.0

            if month in refi_trigger_months:
                # trigger month is the first month of the "coming year" itself
                # (e.g. refi_year=4 -> trigger month 49 -> that's the first month
                # of Year 5), so no extra +1 is needed here.
                target_month_for_projection = month
                projected_monthly_revenue = _get_vessel_revenue(target_month_for_projection)
                projected_monthly_opex = _get_vessel_opex(target_month_for_projection)
                if spot_market_enabled:
                    # _get_vessel_revenue already sums Treatment/Smolt/Harvest
                    # revenue (incl. the per-year utilization factor); add
                    # all three segments' own build-up-tool voyage costs
                    # here, with the same factor applied (crew/vessel opex
                    # above is the shared line only, unaffected).
                    _util_factor_proj = _utilization_ratio_for_month(target_month_for_projection)
                    projected_monthly_opex += (
                        spot_treatment_cost_monthly_base * _escalation_factor(spot_treatment_cost_escalator_pct, target_month_for_projection) * _util_factor_proj
                        + spot_smolt_cost_monthly_base * _escalation_factor(spot_smolt_cost_escalator_pct, target_month_for_projection) * _util_factor_proj
                        + spot_harvest_cost_monthly_base * _escalation_factor(spot_harvest_cost_escalator_pct, target_month_for_projection) * _util_factor_proj
                    )
                projected_annual_ebitda_vessel = (projected_monthly_revenue - projected_monthly_opex) * 12
                new_principal = releverage_multiple * projected_annual_ebitda_vessel
                refinancing_proceeds_this_month = new_principal - vessel_debt_balance
                vessel_debt_balance = new_principal
                vessel_quarterly_amort = new_principal / (amortization_years * 4)
                vessel_cycle_month = 1  # this month is month 1 of the new amortization cycle

            vessel_opening_balance = vessel_debt_balance
            vessel_finance_cost = vessel_opening_balance * vessel_monthly_rate
            vessel_is_quarter_end = (vessel_cycle_month % 3 == 0)
            vessel_amortization = vessel_quarterly_amort if vessel_is_quarter_end else 0.0
            vessel_debt_balance = vessel_opening_balance - vessel_amortization
            vessel_debt_closing = vessel_debt_balance

            # --- operational funding debt tranche (same rate/terms as vessel debt) ---
            operational_opening_balance = operational_debt_balance
            operational_finance_cost = operational_opening_balance * vessel_monthly_rate
            operational_is_quarter_end = (operational_cycle_month % 3 == 0)
            operational_amortization = operational_quarterly_amort if operational_is_quarter_end else 0.0
            operational_debt_balance = operational_opening_balance - operational_amortization
            operational_debt_closing = operational_debt_balance

            # --- escalated revenue & opex for this month ---
            # TC-mode revenue uses the existing contract mechanism; in spot
            # mode, this line goes to zero and Treatment/Smolt/Harvest
            # revenue are tracked explicitly below instead (each escalating
            # at its own flat rate, independent of the TC contract engine).
            if spot_market_enabled:
                _util_factor_this_month = _utilization_ratio_for_month(month)
                monthly_revenue_vessel = 0.0
                monthly_treatment_revenue = (
                    spot_segment_revenue_monthly_base[_treatment_idx]["monthly_base"]
                    * _segment_revenue_multiplier("Treatment of fish", month)
                    * _util_factor_this_month
                    if _treatment_idx is not None else 0.0
                )
                monthly_smolt_revenue = (
                    spot_segment_revenue_monthly_base[_smolt_idx_lookup]["monthly_base"]
                    * _segment_revenue_multiplier("Smolt transport", month)
                    * _util_factor_this_month
                    if _smolt_idx_lookup is not None else 0.0
                )
                monthly_harvest_revenue = (
                    spot_segment_revenue_monthly_base[_harvest_idx_lookup]["monthly_base"]
                    * _segment_revenue_multiplier("Harvest transport", month)
                    * _util_factor_this_month
                    if _harvest_idx_lookup is not None else 0.0
                )
                monthly_treatment_voyage_cost = (
                    spot_treatment_cost_monthly_base * _escalation_factor(spot_treatment_cost_escalator_pct, month) * _util_factor_this_month
                )
                monthly_smolt_voyage_cost = (
                    spot_smolt_cost_monthly_base * _escalation_factor(spot_smolt_cost_escalator_pct, month) * _util_factor_this_month
                )
                monthly_harvest_voyage_cost = (
                    spot_harvest_cost_monthly_base * _escalation_factor(spot_harvest_cost_escalator_pct, month) * _util_factor_this_month
                )
            else:
                monthly_revenue_vessel = _get_vessel_revenue(month)
                monthly_treatment_revenue = 0.0
                monthly_smolt_revenue = 0.0
                monthly_harvest_revenue = 0.0
                monthly_treatment_voyage_cost = 0.0
                monthly_smolt_voyage_cost = 0.0
                monthly_harvest_voyage_cost = 0.0

            # In spot mode, the equipment's customer lease payment (the
            # fixed, contracted 12%-yield revenue) is cancelled — there's
            # no secured lease contract underpinning it under spot trading.
            # The equipment still gets bought and bank-financed exactly as
            # configured (finance cost/amortization below are computed
            # separately, from bank_schedule_full, and are unaffected by
            # this); only the lease REVENUE side goes to zero, so spot
            # revenue has to cover that cost like everything else.
            if lease_enabled and month <= int(customer_term_months) and not spot_market_enabled:
                lease_factor = _escalation_factor(lease_escalator_pct, month)
                lease_revenue_this_month = lease_monthly_payment * lease_factor
                lease_opex_this_month = lease_opex_monthly_nok  # pass-through, not escalated
            else:
                lease_revenue_this_month = 0.0
                lease_opex_this_month = 0.0

            # --- equipment depreciation: straight-line, stops once the
            # equipment financing term (equipment_depreciation_months) has
            # elapsed, leaving NBV at exactly 0 rather than going negative ---
            if equipment_depreciation_months and month <= equipment_depreciation_months:
                equipment_depreciation_this_month = monthly_equipment_depreciation
            else:
                equipment_depreciation_this_month = 0.0

            escalated_opex_items = []
            for item in opex_line_items_base:
                factor = _escalation_factor(item["escalator_pct"], month)
                escalated_value = item["monthly"] * factor
                escalated_opex_items.append({"name": item["name"], "value": escalated_value})

            if spot_market_enabled:
                _fixed_voyage_opex_this_month = _fixed_opex_nominal_monthly(month)
                spot_vessel_opex_this_month = _fixed_voyage_opex_this_month  # Fixed Voyage opex specifically, for its own P&L line
                monthly_opex_vessel = _fixed_voyage_opex_this_month + sum(x["value"] for x in escalated_opex_items)
            else:
                monthly_opex_vessel = sum(x["value"] for x in escalated_opex_items)
                spot_vessel_opex_this_month = 0.0

            # --- spot market: Treatment/Smolt/Harvest voyage costs, each
            # from their own build-up tool — all three now fully
            # self-contained, no generic recovery mechanic needed anymore. ---
            if spot_market_enabled:
                monthly_opex_vessel += monthly_treatment_voyage_cost + monthly_smolt_voyage_cost + monthly_harvest_voyage_cost

            maintenance_factor = _escalation_factor(maintenance_escalator_pct, month)
            monthly_maintenance = monthly_maintenance_base * maintenance_factor

            # --- additional spot capex: spread evenly across the year it's
            # incurred, same convention as maintenance capex above. Uses
            # the NOMINAL value (real value escalated from its own start
            # year via the maintenance escalator) — the real figure typed
            # on the Spot market tab isn't what actually hits cash/the
            # balance sheet, its escalated nominal equivalent is. Spot
            # mode only — this represents the extra wear spot trading
            # puts on the vessel beyond what a steady TC charter would. ---
            if spot_market_enabled:
                _year_now = (month - 1) // 12 + 1
                if _year_now >= 2:
                    monthly_additional_spot_capex = _additional_spot_capex_nominal_for_vintage(min(_year_now, 12)) / 12
                else:
                    monthly_additional_spot_capex = 0.0
            else:
                monthly_additional_spot_capex = 0.0

            # --- asset register depreciation: maintenance capex and
            # Additional spot capex each depreciate on their OWN schedule
            # (different rates/useful lives), starting from their own
            # vintage year — see each function's docstring. This is IN
            # ADDITION to the vessel's own depreciation on original capex
            # (monthly_vessel_depreciation, computed once above). ---
            monthly_maintenance_capex_depreciation = _maintenance_capex_depreciation_for_month(month)
            monthly_additional_capex_depreciation = _additional_spot_capex_depreciation_for_month(month)

            if lease_enabled and bank_financing_enabled:
                eq_debt_row = _row_or_zero(bank_schedule_full, month, int(bank_term_months))
                equipment_finance_cost = eq_debt_row["Finance cost"]
                equipment_amortization = eq_debt_row["Amortization"]
                equipment_debt_closing = eq_debt_row["Closing balance"]
            else:
                equipment_finance_cost = 0.0
                equipment_amortization = 0.0
                equipment_debt_closing = 0.0

            # --- combined P&L ---
            # monthly_revenue_vessel is 0 in spot mode (Treatment/Smolt/
            # Harvest carry the actual revenue instead); EBITDA stays a
            # single combined figure (no per-segment EBITDA split — direct
            # voyage costs are netted per segment on the Spot market tab's
            # own 'Net income check' sections instead, since crew opex
            # stays shared/unallocated here).
            revenue = (
                monthly_revenue_vessel + monthly_treatment_revenue + monthly_smolt_revenue + monthly_harvest_revenue
                + lease_revenue_this_month + lease_opex_this_month
            )
            ebitda_vessel = (
                monthly_revenue_vessel + monthly_treatment_revenue + monthly_smolt_revenue + monthly_harvest_revenue
                - monthly_opex_vessel
            )
            ebitda_equipment = lease_revenue_this_month  # pass-through opex nets to zero
            ebitda = ebitda_vessel + ebitda_equipment
            ebit = (
                ebitda - monthly_vessel_depreciation - monthly_maintenance_capex_depreciation
                - monthly_additional_capex_depreciation - equipment_depreciation_this_month
            )
            finance_cost_total = vessel_finance_cost + equipment_finance_cost + operational_finance_cost
            ebt = ebit - finance_cost_total
            tax = ebt * (tax_rate_pct / 100)
            net_income = ebt - tax

            pnl_row = {"Month": month}
            pnl_row["TC-revenue"] = monthly_revenue_vessel
            pnl_row["Lease-revenue"] = lease_revenue_this_month
            if spot_market_enabled:
                pnl_row["Smolt transport revenue"] = monthly_smolt_revenue
                pnl_row["Harvest transport revenue"] = monthly_harvest_revenue
                pnl_row["Treatment revenue (spot-income)"] = monthly_treatment_revenue
            pnl_row["Pass-through costs"] = lease_opex_this_month
            pnl_row["Total revenue"] = revenue
            for item in escalated_opex_items:
                pnl_row[item["name"]] = -item["value"]
            if spot_market_enabled:
                pnl_row["Fixed voyage opex (spot — shared, unallocated)"] = -spot_vessel_opex_this_month
                pnl_row["Smolt voyage costs"] = -monthly_smolt_voyage_cost
                pnl_row["Harvest voyage costs"] = -monthly_harvest_voyage_cost
                pnl_row["Treatment voyage costs"] = -monthly_treatment_voyage_cost
            pnl_row["Equipment opex (pass-through)"] = -lease_opex_this_month
            pnl_row["EBITDA — vessel"] = ebitda_vessel
            pnl_row["EBITDA — equipment"] = ebitda_equipment
            pnl_row["EBITDA"] = ebitda
            pnl_row["Depreciation — vessel"] = -monthly_vessel_depreciation
            pnl_row["Depreciation — maintenance capex (asset register)"] = -monthly_maintenance_capex_depreciation
            pnl_row["Depreciation — additional spot capex (asset register)"] = -monthly_additional_capex_depreciation
            pnl_row["Depreciation — equipment"] = -equipment_depreciation_this_month
            pnl_row["EBIT"] = ebit
            pnl_row["Finance cost — vessel (bank)"] = -vessel_finance_cost
            pnl_row["Finance cost — equipment (leasing company)"] = -equipment_finance_cost
            pnl_row["Finance cost — operational funding"] = -operational_finance_cost
            pnl_row["EBT"] = ebt
            pnl_row["Tax"] = -tax
            pnl_row["Net income"] = net_income
            pnl_rows_.append(pnl_row)

            # --- working capital: tracks the current (escalated) TOTAL
            # billed revenue run-rate — vessel/spot revenue, voyage cost
            # recovery, and lease revenue (incl. its pass-through opex) all
            # get the same DSO treatment, since they're all genuinely
            # invoiced to the customer the same way. ---
            daily_revenue_now = revenue * 12 / 365
            daily_opex_now = monthly_opex_vessel * 12 / 365
            ar_balance = daily_revenue_now * dso_days
            ap_balance = daily_opex_now * dpo_days
            this_nwc = ar_balance - ap_balance
            wc_change = this_nwc - prev_nwc
            prev_nwc = this_nwc

            cf_after_wc = ebitda - wc_change
            cf_after_finance = cf_after_wc - finance_cost_total
            cf_after_tax = cf_after_finance - tax
            capex_adjustment_this_month = capex_delta_by_month.get(month, 0.0)
            cash_flow_for_period = (
                cf_after_tax - vessel_amortization - equipment_amortization - operational_amortization
                - monthly_maintenance - monthly_additional_spot_capex
                + refinancing_proceeds_this_month - capex_adjustment_this_month
            )
            cumulative_cash += cash_flow_for_period

            cf_rows_.append({
                "Month": month,
                "EBITDA": ebitda,
                "Working capital change": -wc_change,
                "Finance cost — vessel (bank)": -vessel_finance_cost,
                "Finance cost — equipment (leasing company)": -equipment_finance_cost,
                "Finance cost — operational funding": -operational_finance_cost,
                "Tax": -tax,
                "Amortization — vessel (bank)": -vessel_amortization,
                "Amortization — equipment (leasing company)": -equipment_amortization,
                "Amortization — operational funding": -operational_amortization,
                "Maintenance capex": -monthly_maintenance,
                "Additional spot capex": -monthly_additional_spot_capex,
                "Capex adjustment (vessel upgrade/downgrade)": -capex_adjustment_this_month,
                "Refinancing proceeds (vessel)": refinancing_proceeds_this_month,
                "Operational funding injected (equity + debt)": 0.0,
                "Cash flow for the period": cash_flow_for_period,
                "Cash balance": cumulative_cash,
            })

            cumulative_vessel_depreciation += monthly_vessel_depreciation
            cumulative_equipment_depreciation += equipment_depreciation_this_month
            cumulative_maintenance_capex += monthly_maintenance
            cumulative_additional_spot_capex += monthly_additional_spot_capex
            cumulative_maintenance_capex_depreciation += monthly_maintenance_capex_depreciation
            cumulative_additional_capex_depreciation += monthly_additional_capex_depreciation
            cumulative_capex_adjustment += capex_adjustment_this_month
            vessel_nbv = (
                capex_nok - cumulative_vessel_depreciation
                + cumulative_maintenance_capex + cumulative_additional_spot_capex
                - cumulative_maintenance_capex_depreciation - cumulative_additional_capex_depreciation
                + cumulative_capex_adjustment
            )
            equipment_nbv = max(0.0, equipment_capex - cumulative_equipment_depreciation)
            equity += net_income
            total_assets = vessel_nbv + equipment_nbv + ar_balance + cumulative_cash
            total_liab_equity = vessel_debt_closing + equipment_debt_closing + operational_debt_closing + ap_balance + equity

            bs_rows_.append({
                "Month": month,
                "Vessel (NBV)": vessel_nbv,
                "Leased equipment (NBV)": equipment_nbv,
                "Accounts receivable": ar_balance,
                "Cash": cumulative_cash,
                "Total assets": total_assets,
                "Debt — vessel (bank)": vessel_debt_closing,
                "Debt — equipment (leasing company)": equipment_debt_closing,
                "Debt — operational funding": operational_debt_closing,
                "Accounts payable": ap_balance,
                "Equity": equity,
                "Total liabilities + equity": total_liab_equity,
            })

        return pnl_rows_, cf_rows_, bs_rows_

    # --- run twice: the REAL statements use whatever funding the user chose
    # on Tab 1 (possibly a mix of equity and debt); a separate, throwaway
    # BASELINE run forced to zero funding gives a stable guideline that
    # never moves depending on how much was funded — see the caption on
    # Tab 1's Sources & Uses for why this replaces the old iterative
    # approach entirely. ---
    pnl_rows, cf_rows, bs_rows = _run_monthly_model(operational_equity_nok, operational_debt_nok)
    _baseline_pnl_rows, _baseline_cf_rows, _baseline_bs_rows = _run_monthly_model(0.0, 0.0)
    _baseline_cash_series = [row["Cash balance"] for row in _baseline_cf_rows]
    _baseline_month_series = [row["Month"] for row in _baseline_cf_rows]
    _baseline_min_idx = _baseline_cash_series.index(min(_baseline_cash_series))
    baseline_min_cash_balance = _baseline_cash_series[_baseline_min_idx]
    baseline_min_cash_month = _baseline_month_series[_baseline_min_idx]

    pnl_df = pd.DataFrame(pnl_rows)
    cf_df = pd.DataFrame(cf_rows)
    bs_df = pd.DataFrame(bs_rows)

    # --- annual roll-ups ---
    pnl_df_yr = pnl_df.copy()
    pnl_df_yr["Year"] = ((pnl_df_yr["Month"] - 1) // 12 + 1)
    pnl_annual = pnl_df_yr.drop(columns=["Month"]).groupby("Year").sum()

    cf_df_yr = cf_df.copy()
    cf_df_yr["Year"] = ((cf_df_yr["Month"] - 1) // 12 + 1)
    flow_cols = [c for c in cf_df_yr.columns if c not in ("Month", "Year", "Cash balance")]
    cf_annual = cf_df_yr.groupby("Year")[flow_cols].sum()
    cf_annual["Cash balance"] = cf_df_yr.groupby("Year")["Cash balance"].last()  # year-end stock, not summed

    bs_year_end = bs_df[bs_df["Month"] % 12 == 0].copy()
    bs_year_end["Year"] = bs_year_end["Month"] // 12
    bs_opening = bs_df[bs_df["Month"] == 0].copy()
    bs_opening["Year"] = 0
    bs_annual = pd.concat([bs_opening, bs_year_end]).drop(columns=["Month"]).set_index("Year")

    def to_horizontal(df: pd.DataFrame, index_col: str = "Month", prefix: str = "Month") -> pd.DataFrame:
        t = df.set_index(index_col).T if index_col in df.columns else df.T
        t.columns = [f"{prefix} {c}" for c in t.columns]
        t.index.name = "Line item"
        return t

    def to_horizontal_indexed(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        t = df.T
        t.columns = [f"{prefix} {c}" for c in t.columns]
        t.index.name = "Line item"
        return t

    st.caption(f"All figures in {currency}.")

    if not lease_enabled:
        st.info(
            "Leased equipment is currently **off** (see the Lease spread tab). "
            "The statements below reflect the vessel only."
        )

    pnl_tab, cf_tab, bs_tab = st.tabs(["P&L", "Cash flow", "Balance sheet"])

    with pnl_tab:
        view = st.radio("View", ["Monthly", "Annual"], horizontal=True, key="pnl_view")
        if view == "Monthly":
            st.markdown(f"**Monthly P&L** — months 1 to {horizon_months}")
            show_table(to_horizontal(pnl_df, "Month", "Month"), width="stretch", height=460)
        else:
            st.markdown(f"**Annual P&L** — Year 1 to Year {pnl_annual.index.max()}")
            show_table(to_horizontal_indexed(pnl_annual, "Year"), width="stretch", height=460)

        chart_df = pnl_df[["Month", "EBITDA", "EBIT", "Net income"]]
        formatted_line_chart(chart_df, "Month", ["EBITDA", "EBIT", "Net income"])

    with cf_tab:
        view = st.radio("View", ["Monthly", "Annual"], horizontal=True, key="cf_view")
        if view == "Monthly":
            st.markdown(f"**Cash flow (EBITDA bridge)** — month 0 (opening) to month {horizon_months}")
            show_table(to_horizontal(cf_df, "Month", "Month"), width="stretch", height=380)
        else:
            st.markdown(f"**Annual cash flow (EBITDA bridge)** — Year 0 (opening) to Year {cf_annual.index.max()}")
            show_table(to_horizontal_indexed(cf_annual, "Year"), width="stretch", height=380)

        chart_df = pd.DataFrame({
            "Month": cf_df["Month"],
            "Cash balance": cf_df["Cash flow for the period"].cumsum(),
        })
        formatted_line_chart(chart_df, "Month", ["Cash balance"])

    with bs_tab:
        view = st.radio("View", ["Monthly", "Annual"], horizontal=True, key="bs_view")
        if view == "Monthly":
            st.markdown(f"**Balance sheet** — month 0 (opening) to month {horizon_months}")
            show_table(to_horizontal(bs_df, "Month", "Month"), width="stretch", height=420)
        else:
            st.markdown(f"**Balance sheet, year-end** — Year 0 (opening) to Year {bs_annual.index.max()}")
            show_table(to_horizontal_indexed(bs_annual, "Year"), width="stretch", height=420)

        chart_df = bs_df[["Month", "Vessel (NBV)", "Cash", "Equity"]]
        formatted_line_chart(chart_df, "Month", ["Vessel (NBV)", "Cash", "Equity"])

        max_imbalance = (bs_df["Total assets"] - bs_df["Total liabilities + equity"]).abs().max()
        if max_imbalance < 1.0:
            st.success("Balance sheet ties out: Total assets = Total liabilities + equity, every month.")
        else:
            st.error(
                f"Balance sheet does not tie out — largest imbalance is "
                f"{format_nok(max_imbalance)} NOK. This shouldn't happen; flag it if you see it."
            )

    # =======================================================================
    # Asset register — full depreciation build-up across all four streams:
    # vessel (original capex), equipment (lease), maintenance capex
    # vintages, and additional spot capex vintages — each on its own
    # schedule, shown explicitly so every P&L depreciation line can be
    # traced back to its source rather than trusted blind.
    # =======================================================================
    st.divider()
    st.subheader("Asset register — depreciation build-up")
    st.caption(
        "Every depreciation line in the P&L above, traced back to its "
        "own schedule — four separate streams, each with its own rate "
        "and useful life."
    )

    st.markdown("**1) Vessel** (original capex — Tab 1)")
    _vessel_useful_life = (100 / depreciation_rate_pct) if depreciation_rate_pct else 0.0
    vc1, vc2, vc3, vc4 = st.columns(4)
    vc1.metric("Capex", fmt(capex_nok))
    vc2.metric("Depreciation rate", f"{depreciation_rate_pct:.1f}%/yr")
    vc3.metric("Implied useful life", f"{_vessel_useful_life:.0f} years")
    vc4.metric("Annual depreciation", fmt(monthly_vessel_depreciation * 12))

    st.markdown("**2) Leased equipment** (Tab 2 — depreciated over the bank financing term)")
    if lease_enabled and equipment_capex > 0:
        ec1, ec2, ec3, ec4 = st.columns(4)
        ec1.metric("Capex", fmt(equipment_capex))
        ec2.metric("Financing term", f"{equipment_depreciation_months} months ({equipment_depreciation_months/12:.0f} years)")
        ec3.metric("Monthly depreciation", fmt(monthly_equipment_depreciation))
        ec4.metric("Annual depreciation", fmt(monthly_equipment_depreciation * 12))
        st.caption(
            "Straight-line over the bank financing term (currently "
            f"{int(bank_term_months)} months) — reaches zero NBV exactly "
            "when that term ends, unlike the vessel/maintenance/"
            "additional-capex streams, which keep depreciating at a flat "
            "rate indefinitely rather than fully writing off within the "
            "model horizon."
        )
    else:
        st.caption("Leased equipment is currently off (see the Lease spread tab) — no equipment depreciation.")

    st.markdown(f"**3) Maintenance capex** (Tab 1, {fmt(annual_maintenance_capex_nok)}/yr baseline — same rate/life as the vessel)")
    st.caption(
        f"Each year's maintenance capex becomes its own vintage, "
        f"depreciating at the vessel's own rate ({depreciation_rate_pct:.1f}%/yr, "
        f"{_vessel_useful_life:.0f}-year implied life) from its own start year — "
        f"applies unconditionally in both TC and spot mode."
    )
    _maint_vintage_rows = []
    for _vintage_year in range(1, 13):
        _vintage_start_month = (_vintage_year - 1) * 12 + 1
        _maint_this_vintage = annual_maintenance_capex_nok * _escalation_factor(maintenance_escalator_pct, _vintage_start_month)
        _annual_dep_this_vintage = _maint_this_vintage * (depreciation_rate_pct / 100)
        _maint_vintage_rows.append({
            "Vintage year": f"Year {_vintage_year}",
            "Maintenance capex added (nominal)": _maint_this_vintage,
            "Annual depreciation (this vintage, ongoing every year from here)": _annual_dep_this_vintage,
        })
    maint_vintage_df = pd.DataFrame(_maint_vintage_rows)
    show_table(maint_vintage_df, "Vintage year", width="stretch")

    st.markdown("Total maintenance capex depreciation, by reporting year")
    _maint_total_by_year_rows = []
    for _reporting_year in range(1, 13):
        _total_this_year = sum(
            _maint_vintage_rows[_vy - 1]["Annual depreciation (this vintage, ongoing every year from here)"]
            for _vy in range(1, _reporting_year + 1)
        )
        _maint_total_by_year_rows.append({"Year": f"Year {_reporting_year}", "Total maintenance capex depreciation": _total_this_year})
    maint_total_by_year_df = pd.DataFrame(_maint_total_by_year_rows)
    show_table(maint_total_by_year_df, "Year", width="stretch")

    if spot_market_enabled:
        _additional_useful_life = (100 / spot_additional_capex_depreciation_pct) if spot_additional_capex_depreciation_pct else 0.0
        st.markdown(
            f"**4) Additional spot capex** (Spot market tab, Year 2-12 — "
            f"own rate: {spot_additional_capex_depreciation_pct:.1f}%/yr, "
            f"{_additional_useful_life:.0f}-year implied life)"
        )
        st.caption(
            "Each year's Additional spot capex is entered in today's "
            "money and escalated to nominal terms via the maintenance "
            "capex escalator (same 'real value → nominal' treatment as "
            "Fixed Voyage opex) before becoming its own vintage, "
            "depreciating at its own separately-defined rate (set on the "
            "Spot market tab) — genuinely decoupled from the vessel/"
            "maintenance capex rate, since spot-specific capex may have "
            "a different useful life. Spot mode only."
        )
        _additional_vintage_rows = []
        for _vintage_year in range(1, 13):
            _add_capex_this_vintage = _additional_spot_capex_nominal_for_vintage(_vintage_year)
            _annual_dep_this_vintage = _add_capex_this_vintage * (spot_additional_capex_depreciation_pct / 100)
            _additional_vintage_rows.append({
                "Vintage year": f"Year {_vintage_year}",
                "Additional spot capex added (nominal)": _add_capex_this_vintage,
                "Annual depreciation (this vintage, ongoing every year from here)": _annual_dep_this_vintage,
            })
        additional_vintage_df = pd.DataFrame(_additional_vintage_rows)
        show_table(additional_vintage_df, "Vintage year", width="stretch")

        st.markdown("Total additional spot capex depreciation, by reporting year")
        _additional_total_by_year_rows = []
        for _reporting_year in range(1, 13):
            _total_this_year = sum(
                _additional_vintage_rows[_vy - 1]["Annual depreciation (this vintage, ongoing every year from here)"]
                for _vy in range(1, _reporting_year + 1)
            )
            _additional_total_by_year_rows.append({"Year": f"Year {_reporting_year}", "Total additional spot capex depreciation": _total_this_year})
        additional_total_by_year_df = pd.DataFrame(_additional_total_by_year_rows)
        show_table(additional_total_by_year_df, "Year", width="stretch")
    else:
        st.markdown("**4) Additional spot capex**")
        st.caption("Spot market is off — no additional spot capex depreciation applies.")

    # =======================================================================
    # Net revenue by segment — deliberately separate from the P&L's EBITDA
    # waterfall above (crew/vessel opex stays shared and unallocated there,
    # by design), showing each segment's own direct contribution instead.
    # =======================================================================
    if spot_market_enabled:
        st.divider()
        st.subheader("Net revenue by segment")
        st.caption(
            "Revenue less each segment's own direct voyage cost — kept "
            "separate from the EBITDA waterfall above, since crew/vessel "
            "opex there stays one shared, unallocated line rather than "
            "being split across segments (allocating a shared fixed cost "
            "is inherently arbitrary; this net revenue view is a cleaner "
            "'contribution' read instead). TC and Lease revenue have no "
            "directly-tracked offsetting cost in this model, so they're "
            "shown as-is."
        )
        _net_rev_rows = []
        for _yr in pnl_annual.index:
            _row = {"Year": f"Year {int(_yr)}"}
            _row["TC-revenue"] = pnl_annual.loc[_yr, "TC-revenue"]
            _row["Lease-revenue"] = pnl_annual.loc[_yr, "Lease-revenue"]
            if "Treatment revenue (spot-income)" in pnl_annual.columns:
                _row["Treatment net revenue"] = (
                    pnl_annual.loc[_yr, "Treatment revenue (spot-income)"]
                    + pnl_annual.loc[_yr, "Treatment voyage costs"]
                )
            if "Smolt transport revenue" in pnl_annual.columns:
                _row["Smolt net revenue"] = (
                    pnl_annual.loc[_yr, "Smolt transport revenue"] + pnl_annual.loc[_yr, "Smolt voyage costs"]
                )
            if "Harvest transport revenue" in pnl_annual.columns:
                _row["Harvest net revenue"] = (
                    pnl_annual.loc[_yr, "Harvest transport revenue"] + pnl_annual.loc[_yr, "Harvest voyage costs"]
                )
            _row["Total net revenue"] = sum(v for k, v in _row.items() if k != "Year")
            _net_rev_rows.append(_row)
        net_rev_by_segment_df = pd.DataFrame(_net_rev_rows).set_index("Year").T
        net_rev_by_segment_df.index.name = "Segment"
        show_table(net_rev_by_segment_df, width="stretch")

    # =======================================================================
    # Operational funding summary
    # =======================================================================
    st.divider()
    st.subheader("Operational funding")
    st.caption(
        "The vessel's implied equity (Tab 1) covers the purchase price only — "
        "it assumes the cash balance starts at zero and simply accumulates "
        "from there. If the monthly cash flow ever dips negative before it "
        "recovers, that's a real shortfall that needs covering so the vessel "
        "never actually runs out of cash. **Decide how to cover it on Tab 1's "
        "Sources & Uses section** — this is just a summary of what's "
        "currently applied there. The guideline below is always the deficit "
        "that would exist with **zero** operational funding — a fixed target "
        "that doesn't move depending on how much you choose to fund, so "
        "there's nothing to iterate towards."
    )

    # Actual, as-funded minimum (reflects whatever funding is currently applied)
    min_cash_balance = cf_df["Cash balance"].min()
    min_cash_month = int(cf_df.loc[cf_df["Cash balance"].idxmin(), "Month"])

    # The guideline: computed above from a SEPARATE run forced to zero
    # funding, so it's a fixed number that never depends on the funding
    # decision itself — no circularity, no staleness, no iteration needed.
    deficit_guideline_fixed = abs(baseline_min_cash_balance) if baseline_min_cash_balance < 0 else 0.0

    st.metric(
        "Maximum cash deficit (guideline, zero funding)",
        fmt(deficit_guideline_fixed),
        help=(
            f"With no operational funding at all, cumulative cash balance "
            f"bottoms out at {fmt(baseline_min_cash_balance)} in month "
            f"{baseline_min_cash_month}. This is the fixed target used to "
            f"size the equity/debt split on Tab 1 — it does not change "
            f"based on how much of it you actually fund."
        ) if deficit_guideline_fixed > 0 else "Cash flow never dips negative even with zero funding."
    )

    if min_cash_balance < 0:
        st.caption(
            f"⚠️ **With the funding currently applied**, cash balance still goes "
            f"as low as {fmt(min_cash_balance)} in month {min_cash_month}."
        )
    else:
        st.caption(
            f"✅ **With the funding currently applied**, cash balance never goes "
            f"negative — lowest point is {fmt(min_cash_balance)} in month {min_cash_month}."
        )

    op_col1, op_col2 = st.columns(2)
    op_col1.metric("Operational funding — equity portion", fmt(operational_equity_nok))
    op_col2.metric("Operational funding — debt portion", fmt(operational_debt_nok))

    total_equity_required = vessel_equity_initial + equipment_equity_initial + operational_equity_nok
    st.markdown(
        f"**Total equity required:** {fmt(vessel_equity_initial)} (vessel) + "
        f"{fmt(equipment_equity_initial)} (equipment) + {fmt(operational_equity_nok)} (operational, equity portion) "
        f"= **{fmt(total_equity_required)}**"
    )

    # --- store for the Sources & Uses summary on Tab 1 (which runs earlier in
    #     the script and can't compute this itself — see the note there).
    #     Crucially, this is the FIXED, zero-funding guideline, not the
    #     as-funded minimum — so it's stable pass to pass regardless of what
    #     funding decision was made, eliminating the old circularity. ---
    _previous_su = st.session_state.get("_sources_uses")
    st.session_state["_sources_uses"] = {
        "vessel_equity": vessel_equity_initial,
        "equipment_equity": equipment_equity_initial,
        "total_equity": total_equity_required,
        "min_cash_balance": baseline_min_cash_balance,
        "min_cash_month": baseline_min_cash_month,
        "vessel_debt": debt_nok,
        "equipment_debt": equipment_debt_initial,
        "lease_enabled": lease_enabled,
    }

    # --- self-healing refresh: Tab 1 is one script pass behind by design
    # (it runs before this tab, so it always shows what was stored on the
    # PREVIOUS pass). If what was just freshly computed here differs
    # meaningfully from what Tab 1 is currently displaying, that number is
    # stale — trigger a deferred rerun so it catches up automatically,
    # without needing a manual Refresh click or a tab switch. Capped at a
    # few retries per interaction as a safety net against any edge case
    # that doesn't settle. ---
    _guideline_changed = (
        _previous_su is None
        or abs(_previous_su.get("min_cash_balance", 0.0) - baseline_min_cash_balance) > 1.0
    )
    _stale_refresh_count = st.session_state.get("_stale_guideline_refresh_count", 0)
    if _guideline_changed and _stale_refresh_count < 4:
        st.session_state["_stale_guideline_refresh_count"] = _stale_refresh_count + 1
        _request_rerun()
    else:
        st.session_state["_stale_guideline_refresh_count"] = 0

# ===========================================================================
# TAB 5 — Investment Analysis (equity IRR, terminal value on forward EBITDA)
# ===========================================================================
with tab_investment:
    st.subheader("Investment analysis — equity IRR")
    st.caption(
        "Equity cash flows from the initial investment (month 0) through "
        "monthly operations, plus a terminal value at exit. Each month's "
        "'Cash flow for the period' (after all debt service, tax, and capex — "
        "see Financial Statements) is treated as available to equity as it's "
        "generated. At exit, enterprise value is set at a multiple of the "
        "**coming year's** projected EBITDA, and outstanding debt (vessel + "
        "equipment) is deducted to arrive at terminal equity value."
    )

    terminal_multiple = stateful_number_input(
        "Terminal EBITDA multiple (x forward EBITDA)", min_value=0.0, value=10.0,
        step=0.5, key="terminal_multiple", disabled=locked
    )

    def _project_ebitda_month(month):
        """EBITDA (vessel + equipment) for any month, including beyond the
        modeled horizon — used to project the exit year's EBITDA."""
        revenue = _get_vessel_revenue(month)
        opex = _get_vessel_opex(month)
        if spot_market_enabled:
            # _get_vessel_revenue already sums Treatment/Smolt/Harvest
            # revenue (incl. the per-year utilization factor); add all
            # three segments' own build-up-tool voyage costs here, with
            # the same factor applied (crew/vessel opex above is the
            # shared line only, unaffected).
            _util_factor_exit = _utilization_ratio_for_month(month)
            opex += (
                spot_treatment_cost_monthly_base * _escalation_factor(spot_treatment_cost_escalator_pct, month) * _util_factor_exit
                + spot_smolt_cost_monthly_base * _escalation_factor(spot_smolt_cost_escalator_pct, month) * _util_factor_exit
                + spot_harvest_cost_monthly_base * _escalation_factor(spot_harvest_cost_escalator_pct, month) * _util_factor_exit
            )
        ebitda_v = revenue - opex
        if lease_enabled and month <= int(customer_term_months) and not spot_market_enabled:
            ebitda_e = lease_monthly_payment * _escalation_factor(lease_escalator_pct, month)
        else:
            ebitda_e = 0.0
        return ebitda_v + ebitda_e

    forward_year_start = horizon_months + 1
    forward_annual_ebitda = sum(
        _project_ebitda_month(m) for m in range(forward_year_start, forward_year_start + 12)
    )

    outstanding_debt_at_exit = (
        bs_df.iloc[-1]["Debt — vessel (bank)"] + bs_df.iloc[-1]["Debt — equipment (leasing company)"]
    )
    enterprise_value_at_exit = terminal_multiple * forward_annual_ebitda
    terminal_equity_value = enterprise_value_at_exit - outstanding_debt_at_exit

    tv_col1, tv_col2, tv_col3 = st.columns(3)
    tv_col1.metric("Forward EBITDA (next 12 months)", fmt(forward_annual_ebitda))
    tv_col2.metric("Enterprise value at exit", fmt(enterprise_value_at_exit))
    tv_col3.metric("Outstanding debt at exit", fmt(outstanding_debt_at_exit))
    st.metric("Terminal equity value", fmt(terminal_equity_value))

    # --- build the monthly equity cash flow stream ---
    st.subheader("Equity invested")
    st.caption(
        "How the vessel, equipment, and any operational funding are financed "
        "is decided on Tab 1's Sources & Uses section — the equity portion "
        "chosen there is included in the month 0 investment below, matching "
        "the cash flow model exactly (any debt portion instead shows up as "
        "ongoing interest and amortization, already reflected in the monthly "
        "cash flow). To raise this IRR, cover less of the operational funding "
        "with equity on Tab 1 and let debt (or group liquidity) absorb more "
        "of it."
    )
    if operational_debt_nok > 0:
        st.caption(
            f"Currently: {fmt(operational_equity_nok)} equity + {fmt(operational_debt_nok)} "
            f"debt covering the operational funding requirement."
        )

    initial_equity_investment = vessel_equity_initial + equipment_equity_initial + operational_equity_nok
    equity_cf_rows = [{"Month": 0, "Equity cash flow": -initial_equity_investment}]
    for _, row in cf_df.iterrows():
        m = int(row["Month"])
        cf = row["Cash flow for the period"]
        if m == horizon_months:
            cf += terminal_equity_value
        equity_cf_rows.append({"Month": m, "Equity cash flow": cf})

    equity_cf_df = pd.DataFrame(equity_cf_rows)

    def _irr_bisection(cashflows, low=-0.5, high=1.0, tol=1e-9, max_iter=200):
        def npv(r):
            return sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
        f_lo, f_hi = npv(low), npv(high)
        if f_lo * f_hi > 0:
            return None
        for _ in range(max_iter):
            mid = (low + high) / 2
            f_mid = npv(mid)
            if abs(f_mid) < tol:
                return mid
            if f_lo * f_mid < 0:
                high, f_hi = mid, f_mid
            else:
                low, f_lo = mid, f_mid
        return (low + high) / 2

    monthly_irr = _irr_bisection(equity_cf_df["Equity cash flow"].tolist())

    st.subheader("Equity IRR")
    if monthly_irr is None:
        st.error(
            "IRR could not be computed — the cash flow pattern doesn't cross "
            "zero NPV within a plausible rate range (e.g. total cash returned "
            "may be less than invested, or the pattern is unusual)."
        )
    else:
        annual_irr = (1 + monthly_irr) ** 12 - 1
        total_distributed = equity_cf_df["Equity cash flow"].iloc[1:].sum()
        moic = total_distributed / initial_equity_investment if initial_equity_investment else 0.0

        irr_col1, irr_col2, irr_col3 = st.columns(3)
        irr_col1.metric("Equity IRR, annual", f"{annual_irr:+.1%}")
        irr_col2.metric("Equity IRR, monthly", f"{monthly_irr:+.2%}")
        irr_col3.metric("MOIC (multiple on invested capital)", f"{moic:.2f}x")

        st.caption(
            f"Initial equity invested: {fmt(initial_equity_investment)} at month 0. "
            f"Total cash returned to equity over the life of the investment "
            f"(including the terminal value): {fmt(total_distributed)}."
        )

    st.divider()
    st.subheader("Instant equity value creation (Day 1 mark-to-market)")
    st.caption(
        "A quick check owners look at: if the vessel could be sold "
        "immediately at a market EBITDA multiple, using Year 1 EBITDA, "
        "what's the resulting equity value versus what's actually been "
        "put in? EV = Year 1 EBITDA x multiple. Instant equity value = EV "
        "less starting debt (vessel + leased equipment only — excludes "
        "any operational funding debt). Shown against equity exposed both "
        "with and without covering the operational funding gap via "
        "equity, to see the immediate value-creation MOIC either way — "
        "distinct from the full-horizon Equity IRR/MOIC above, which "
        "accounts for cash flows over the whole investment life plus the "
        "terminal value at actual exit."
    )

    _year1_ebitda_ia = pnl_annual.loc[1, "EBITDA"] if 1 in pnl_annual.index else 0.0
    _debt_vessel_and_lease_at_close_ia = debt_nok + equipment_debt_initial
    _equity_excl_opfunding_ia = vessel_equity_initial + equipment_equity_initial
    _equity_incl_opfunding_ia = vessel_equity_initial + equipment_equity_initial + operational_equity_nok

    instant_value_rows_ia = []
    for _multiple in (10.0, 11.0, 12.0):
        _ev = _year1_ebitda_ia * _multiple
        _instant_equity_value = _ev - _debt_vessel_and_lease_at_close_ia
        _moic_excl = (_instant_equity_value / _equity_excl_opfunding_ia) if _equity_excl_opfunding_ia else None
        _moic_incl = (_instant_equity_value / _equity_incl_opfunding_ia) if _equity_incl_opfunding_ia else None
        instant_value_rows_ia.append({
            "EBITDA multiple": f"{_multiple:.0f}x",
            "Enterprise value (EV)": fmt(_ev),
            "Less: debt (vessel + lease)": fmt(_debt_vessel_and_lease_at_close_ia),
            "Instant equity value": fmt(_instant_equity_value),
            "Equity exposed, excl. op. funding gap": fmt(_equity_excl_opfunding_ia),
            "Instant MOIC, excl. gap (x)": f"{_moic_excl:.2f}x" if _moic_excl is not None else "—",
            "Equity exposed, incl. op. funding gap": fmt(_equity_incl_opfunding_ia),
            "Instant MOIC, incl. gap (x)": f"{_moic_incl:.2f}x" if _moic_incl is not None else "—",
        })
    instant_value_df_ia = pd.DataFrame(instant_value_rows_ia).set_index("EBITDA multiple")
    st.dataframe(instant_value_df_ia, width="stretch")
    st.caption(
        f"Operational funding gap currently modeled: {fmt(operational_equity_nok)} "
        f"of equity allocated to it (see Tab 1's Sources & Uses to adjust)."
    )

    st.subheader("Equity cash flow schedule")
    chart_df = equity_cf_df.copy()
    chart_df["Cumulative equity cash flow"] = chart_df["Equity cash flow"].cumsum()
    formatted_line_chart(chart_df, "Month", ["Cumulative equity cash flow"])

    show_table(equity_cf_df, "Month", width="stretch", height=320)

# ===========================================================================
# TAB 6 — Summary (key financial ratios & KPIs)
# ===========================================================================
with tab_summary:
    st.subheader("Summary — key financial ratios & KPIs")
    st.caption(
        "First working version — definitions below are a starting point; "
        "flag anything you'd like calculated differently (e.g. NIBD scope, "
        "ICR basis, LTV basis) and we'll refine it."
    )

    total_capex_at_close = capex_nok + equipment_capex
    total_debt_at_close = debt_nok + equipment_debt_initial + operational_debt_nok
    total_equity_at_close = vessel_equity_initial + equipment_equity_initial + operational_equity_nok
    ltv_at_close = (total_debt_at_close / total_capex_at_close) if total_capex_at_close else 0.0
    gearing_at_close = (total_debt_at_close / total_equity_at_close) if total_equity_at_close else 0.0

    st.markdown("**Financial close snapshot (Month 0)**")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total capex", fmt(total_capex_at_close))
    c2.metric("Total debt at close", fmt(total_debt_at_close))
    c3.metric("Total equity at close", fmt(total_equity_at_close))
    c4.metric("LTV at close", f"{ltv_at_close:.1%}")
    c5.metric("Gearing (debt / equity)", f"{gearing_at_close:.2f}x")

    st.divider()
    st.markdown("**Investment return KPIs**")
    i1, i2, i3, i4 = st.columns(4)
    if monthly_irr is None:
        i1.metric("Equity IRR, annual", "n/a")
        i2.metric("MOIC", "n/a")
    else:
        i1.metric("Equity IRR, annual", f"{annual_irr:+.1%}")
        i2.metric("MOIC", f"{moic:.2f}x")

    _year1_ebitda = pnl_annual.loc[1, "EBITDA"] if 1 in pnl_annual.index else 0.0
    _yield_on_capex_yr1 = (_year1_ebitda / total_capex_at_close) if total_capex_at_close else 0.0
    _year1_nbv = (
        (bs_annual.loc[1, "Vessel (NBV)"] + bs_annual.loc[1, "Leased equipment (NBV)"])
        if 1 in bs_annual.index else 0.0
    )
    _yield_on_nbv_yr1 = (_year1_ebitda / _year1_nbv) if _year1_nbv else 0.0
    i3.metric("EBITDA yield on capex (Yr 1)", f"{_yield_on_capex_yr1:.1%}")
    i4.metric("EBITDA yield on NBV (Yr 1)", f"{_yield_on_nbv_yr1:.1%}")

    st.divider()
    st.markdown("**Instant equity value creation** (Day 1 mark-to-market)")
    st.caption(
        "A quick check owners look at: if the vessel could be sold "
        "immediately at a market EBITDA multiple, using Year 1 EBITDA, "
        "what's the resulting equity value versus what's actually been "
        "put in? EV = Year 1 EBITDA x multiple. Instant equity value = EV "
        "less starting debt (vessel + leased equipment only — excludes "
        "any operational funding debt). Shown against equity exposed both "
        "with and without covering the operational funding gap via "
        "equity, to see the immediate value-creation MOIC either way."
    )

    _debt_vessel_and_lease_at_close = debt_nok + equipment_debt_initial
    _equity_excl_opfunding = vessel_equity_initial + equipment_equity_initial
    _equity_incl_opfunding = total_equity_at_close  # already includes operational_equity_nok

    instant_value_rows = []
    for _multiple in (10.0, 11.0, 12.0):
        _ev = _year1_ebitda * _multiple
        _instant_equity_value = _ev - _debt_vessel_and_lease_at_close
        _moic_excl = (_instant_equity_value / _equity_excl_opfunding) if _equity_excl_opfunding else None
        _moic_incl = (_instant_equity_value / _equity_incl_opfunding) if _equity_incl_opfunding else None
        instant_value_rows.append({
            "EBITDA multiple": f"{_multiple:.0f}x",
            "Enterprise value (EV)": fmt(_ev),
            "Less: debt (vessel + lease)": fmt(_debt_vessel_and_lease_at_close),
            "Instant equity value": fmt(_instant_equity_value),
            "Equity exposed, excl. op. funding gap": fmt(_equity_excl_opfunding),
            "Instant MOIC, excl. gap (x)": f"{_moic_excl:.2f}x" if _moic_excl is not None else "—",
            "Equity exposed, incl. op. funding gap": fmt(_equity_incl_opfunding),
            "Instant MOIC, incl. gap (x)": f"{_moic_incl:.2f}x" if _moic_incl is not None else "—",
        })
    instant_value_df = pd.DataFrame(instant_value_rows).set_index("EBITDA multiple")
    st.dataframe(instant_value_df, width="stretch")
    st.caption(
        f"Operational funding gap currently modeled: {fmt(operational_equity_nok)} "
        f"of equity allocated to it (see Tab 1's Sources & Uses to adjust)."
    )

    st.divider()
    st.markdown("**Annual ratios**")
    st.caption(
        "NIBD = total debt (vessel + equipment + operational funding) less "
        "cash, at year-end. ICR = EBITDA / total finance cost. LTV is shown "
        "on both a declining (current NBV) and a fixed (original capex) "
        "basis. ROE = net income (annual) / book equity net of cash — as "
        "if all cash on the balance sheet had been distributed out as a "
        "dividend, so the equity base only reflects capital still tied up "
        "in the vessel, equipment, and working capital."
    )

    ratio_rows = []
    for y in pnl_annual.index:
        if y not in bs_annual.index:
            continue
        ebitda_y = pnl_annual.loc[y, "EBITDA"]
        finance_cost_y = -(
            pnl_annual.loc[y, "Finance cost — vessel (bank)"]
            + pnl_annual.loc[y, "Finance cost — equipment (leasing company)"]
            + pnl_annual.loc[y, "Finance cost — operational funding"]
        )
        debt_total_y = (
            bs_annual.loc[y, "Debt — vessel (bank)"]
            + bs_annual.loc[y, "Debt — equipment (leasing company)"]
            + bs_annual.loc[y, "Debt — operational funding"]
        )
        cash_y = bs_annual.loc[y, "Cash"]
        nibd_y = debt_total_y - cash_y
        vessel_nbv_y = bs_annual.loc[y, "Vessel (NBV)"]
        equipment_nbv_y = bs_annual.loc[y, "Leased equipment (NBV)"]
        nbv_total_y = vessel_nbv_y + equipment_nbv_y
        book_equity_y = bs_annual.loc[y, "Equity"]
        net_income_y = pnl_annual.loc[y, "Net income"]

        nibd_ebitda = (nibd_y / ebitda_y) if ebitda_y else None
        icr = (ebitda_y / finance_cost_y) if finance_cost_y else None
        ltv_nbv_basis = (debt_total_y / nbv_total_y) if nbv_total_y else None
        ltv_capex_basis = (debt_total_y / total_capex_at_close) if total_capex_at_close else None
        yield_nbv = (ebitda_y / nbv_total_y) if nbv_total_y else None
        yield_capex = (ebitda_y / total_capex_at_close) if total_capex_at_close else None
        # As if all cash had been distributed out as a dividend: book equity
        # net of cash, used as the denominator for ROE below.
        book_equity_ex_cash_y = book_equity_y - cash_y
        roe = (net_income_y / book_equity_ex_cash_y) if book_equity_ex_cash_y else None

        ratio_rows.append({
            "Year": f"Year {int(y)}",
            "EBITDA": fmt(ebitda_y),
            "NIBD": fmt(nibd_y),
            "NIBD / EBITDA (x)": f"{nibd_ebitda:.2f}x" if nibd_ebitda is not None else "—",
            "Finance cost, total": fmt(finance_cost_y),
            "ICR — EBITDA / finance cost (x)": f"{icr:.2f}x" if icr is not None else "—",
            "Total debt, period-end": fmt(debt_total_y),
            "Fixed assets NBV, period-end": fmt(nbv_total_y),
            "LTV — debt / NBV (%)": f"{ltv_nbv_basis:.1%}" if ltv_nbv_basis is not None else "—",
            "LTV — debt / original capex (%)": f"{ltv_capex_basis:.1%}" if ltv_capex_basis is not None else "—",
            "EBITDA yield on NBV (%)": f"{yield_nbv:.1%}" if yield_nbv is not None else "—",
            "EBITDA yield on original capex (%)": f"{yield_capex:.1%}" if yield_capex is not None else "—",
            "Vessel book value (NBV), period-end": fmt(vessel_nbv_y),
            "Equipment book value (NBV), period-end": fmt(equipment_nbv_y),
            "Book equity, period-end": fmt(book_equity_y),
            "Book equity excl. cash (as if dividended out)": fmt(book_equity_ex_cash_y),
            "ROE — net income / book equity excl. cash (%)": f"{roe:.1%}" if roe is not None else "—",
        })

    ratio_df = pd.DataFrame(ratio_rows).set_index("Year").T
    ratio_df.index.name = "Metric"
    st.dataframe(ratio_df, width="stretch", height=460)

# ===========================================================================
# Excel export — every table in the app, on one workbook, one click
# ===========================================================================
st.divider()
st.subheader("Export to Excel")
st.caption(
    "Downloads every table in the app as a single .xlsx workbook — one "
    "sheet per table, raw numbers (no text formatting), ready to use "
    "directly in Excel."
)


def _style_workbook(workbook):
    """Bold header row, sensible column widths, frozen header/label column,
    and space-separated number formatting — Excel supports a literal space
    as a thousands separator natively, unlike Streamlit's charts/tables."""
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    label_font = Font(bold=True)

    for ws in workbook.worksheets:
        if ws.max_row < 1 or ws.max_column < 1:
            continue

        is_percent_sheet = ws.title == "Finance cost summary"

        # header row styling
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

        # column widths + number formatting + bold label column
        for col_idx in range(1, ws.max_column + 1):
            col_letter = get_column_letter(col_idx)
            max_len = 8
            for row_idx in range(1, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                value = cell.value
                if value is not None:
                    max_len = max(max_len, len(str(value)))
                if row_idx > 1 and isinstance(value, (int, float)):
                    cell.number_format = "0.00" if is_percent_sheet else "#,##0"
                if row_idx > 1 and col_idx == 1 and not isinstance(value, (int, float)):
                    cell.font = label_font
            ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 45)

        ws.freeze_panes = "B2"
        ws.sheet_view.showGridLines = False


def _build_workbook() -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        results_df.to_excel(writer, sheet_name="Vessel TC-rate")
        finance_cost_summary_df.to_excel(writer, sheet_name="Finance cost summary", index=False)
        debt_schedule_df.to_excel(writer, sheet_name="Vessel debt schedule", index=False)
        if spot_market_enabled:
            pd.DataFrame(spot_service_items_current).to_excel(writer, sheet_name="Spot service mix", index=False)
            pd.DataFrame(st.session_state.spot_smolt_segments).to_excel(writer, sheet_name="Smolt voyage build-up", index=False)
            pd.DataFrame(st.session_state.spot_harvest_segments).to_excel(writer, sheet_name="Harvest voyage build-up", index=False)
            pd.DataFrame(st.session_state.spot_treatment_segments).to_excel(writer, sheet_name="Treatment voyage build-up", index=False)
        if lease_enabled:
            lease_schedule_df.to_excel(writer, sheet_name="Lease schedule", index=False)
            if bank_financing_enabled:
                bank_schedule_df.to_excel(writer, sheet_name="Bank financing schedule", index=False)
                spread_df.to_excel(writer, sheet_name="Spread payment schedule", index=False)
        combined_df.to_excel(writer, sheet_name="Combined TC-rate", index=False)
        pnl_df.to_excel(writer, sheet_name="P&L (monthly)", index=False)
        pnl_annual.to_excel(writer, sheet_name="P&L (annual)")
        cf_df.to_excel(writer, sheet_name="Cash flow (monthly)", index=False)
        cf_annual.to_excel(writer, sheet_name="Cash flow (annual)")
        bs_df.to_excel(writer, sheet_name="Balance sheet (monthly)", index=False)
        bs_annual.to_excel(writer, sheet_name="Balance sheet (annual)")
        equity_cf_df.to_excel(writer, sheet_name="Equity cash flow (IRR)", index=False)
        instant_value_df_ia.to_excel(writer, sheet_name="Instant equity value (IA)")
        ratio_df.to_excel(writer, sheet_name="Summary ratios")
        instant_value_df.to_excel(writer, sheet_name="Instant equity value")
        _style_workbook(writer.book)
    buffer.seek(0)
    return buffer.getvalue()


excel_bytes = _build_workbook()
st.download_button(
    label="Download Excel workbook (.xlsx)",
    data=excel_bytes,
    file_name="tc_rate_model.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ---------------------------------------------------------------------------
# All reruns are triggered here, at the very end of the script, after every
# tab's widgets have fully rendered in this pass — never mid-script. Two
# triggers share this one spot:
#   1. Forced exactly once after the very first execution — Tab 1's
#      "Sources & Uses" reads a value computed on Tab 4 (which runs later
#      in this script), so on a true first load Tab 1 renders before that
#      value exists; this makes sure even a passive viewer sees the
#      correct number immediately, without needing to touch anything.
#   2. Any button elsewhere that called _request_rerun() instead of
#      st.rerun() directly, specifically to avoid cutting a pass short
#      before later tabs' widgets have run (see _request_rerun()'s
#      docstring near the top of the script).
# ---------------------------------------------------------------------------

if not st.session_state.get("_initial_rerun_done"):
    st.session_state["_initial_rerun_done"] = True
    st.rerun()
elif st.session_state.get("_pending_rerun"):
    st.session_state["_pending_rerun"] = False
    st.rerun()
