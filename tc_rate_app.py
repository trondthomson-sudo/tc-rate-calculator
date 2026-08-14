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
    """Buttons (like the opex '✕' remove buttons) can't have their
    session_state pre-set — Streamlit raises an error if you try. File
    uploader keys shouldn't be restored either. Exclude both, everywhere."""
    if key in CONFIG_EXCLUDE_KEYS:
        return True
    if key.startswith("remove_"):
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

with st.sidebar:
    st.subheader("🔒 Edit access")
    if st.session_state.unlocked:
        st.success("Unlocked — inputs are editable.")
        if st.button("Lock again"):
            st.session_state.unlocked = False
            st.rerun()
    else:
        st.caption("All inputs are locked (view-only). Enter the password to edit.")
        pwd = st.text_input("Password", type="password", key="unlock_password_input")
        if st.button("Unlock"):
            if pwd == UNLOCK_PASSWORD:
                st.session_state.unlocked = True
                st.rerun()
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
                st.rerun()
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
    """Horizontal bar chart with comma-separated axis labels and tooltips."""
    chart = (
        alt.Chart(df.reset_index())
        .mark_bar()
        .encode(
            y=alt.Y(f"{category_col}:N", title=None, sort=None),
            x=alt.X(f"{value_col}:Q", title=None, axis=alt.Axis(format=NOK_AXIS_FORMAT)),
            tooltip=[
                alt.Tooltip(f"{category_col}:N", title=category_col),
                alt.Tooltip(f"{value_col}:Q", title=value_col, format=NOK_AXIS_FORMAT),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)


def annuity_monthly_payment(principal_nok: float, annual_rate_pct: float, num_months: int) -> float:
    """Level monthly annuity payment. Nominal monthly rate = annual rate / 12."""
    if num_months <= 0:
        return 0.0
    r = (annual_rate_pct / 100) / 12
    if r == 0:
        return principal_nok / num_months
    return principal_nok * r / (1 - (1 + r) ** -num_months)


def amortization_balances(principal_nok: float, annual_rate_pct: float, num_months: int) -> list:
    """Closing balance for each month (used to chart the paydown)."""
    r = (annual_rate_pct / 100) / 12
    payment = annuity_monthly_payment(principal_nok, annual_rate_pct, num_months)
    balance = principal_nok
    balances = []
    for month in range(1, num_months + 1):
        interest = balance * r
        principal_paid = payment - interest
        balance = balance - principal_paid
        if month == num_months:
            balance = 0.0
        balances.append(balance)
    return balances


def amortization_schedule_full(principal_nok: float, annual_rate_pct: float, num_months: int) -> list:
    """Month-by-month: opening balance, payment, finance cost (interest),
    amortization (principal), closing balance."""
    r = (annual_rate_pct / 100) / 12
    payment = annuity_monthly_payment(principal_nok, annual_rate_pct, num_months)
    balance = principal_nok
    rows = []
    for month in range(1, num_months + 1):
        interest = balance * r
        principal_paid = payment - interest
        closing = balance - principal_paid
        if month == num_months:
            closing = 0.0
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
        {"name": "Crewing", "value_nok": 22_000_000.0},
        {"name": "Other vessel opex", "value_nok": 8_000_000.0},
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

tab_vessel, tab_lease, tab_combined, tab_financials, tab_investment, tab_summary = st.tabs(
    ["Vessel TC-rate", "Lease spread", "Combined TC-rate", "Financial Statements", "Investment Analysis", "Summary"]
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
            "Annual maintenance capex (NOK)", "maintenance_capex_nok", 5_000_000.0,
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
            "Swap rate, annual (%)", min_value=0.0, value=3.0, step=0.1, key="swap_rate", disabled=locked
        )
        credit_spread_pct = stateful_number_input(
            "Credit spread, annual (%)", min_value=0.0, value=2.0, step=0.1, key="credit_spread", disabled=locked
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
            "won't shift as you adjust the equity/debt split — it only lags "
            "by one script pass if you've just changed a different input "
            "(capex, opex, escalators, contracts, refinancing) on another "
            "tab; switch tabs once or wait a moment for it to catch up."
        )

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
            "Include customer lease", value=False, key="lease_enabled", disabled=locked
        )
    with toggle_col2:
        bank_financing_enabled = stateful_toggle(
            "Include bank financing", value=False, key="bank_financing_enabled", disabled=locked
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
        lease_capex_nok = nok_input(
            "Capex (NOK)", "lease_capex_nok", 15_000_000.0, key="lease_capex_input", disabled=locked
        )

        st.markdown("**Customer lease (income)**")
        lease_yield_pct = stateful_number_input(
            "Lease-out rate, annual (%)", min_value=0.0, value=12.0, step=0.1, key="lease_yield", disabled=locked
        )
        customer_term_months = stateful_number_input(
            "Customer lease term (months)", min_value=1, max_value=120, value=60, step=1,
            key="customer_term", disabled=locked
        )
        lease_opex_monthly_nok = nok_input(
            "Additional opex billed to customer (NOK/month)", "lease_opex_monthly_nok",
            100_000.0, key="lease_opex_input", disabled=locked
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
                "Bank interest rate, annual (%)", min_value=0.0, value=6.0, step=0.1, key="bank_rate", disabled=locked
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
            bank_term_months = int(customer_term_months)
            lease_equity_instalment_nok = 0.0

    bank_loan_principal = max(0.0, lease_capex_nok - lease_equity_instalment_nok)

    # --- calculations ---
    lease_monthly_payment = annuity_monthly_payment(
        lease_capex_nok, lease_yield_pct, int(customer_term_months)
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

    # --- full monthly schedules, always computed so later tabs can use them ---
    lease_schedule_full = amortization_schedule_full(
        lease_capex_nok, lease_yield_pct, int(customer_term_months)
    )
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
                lease_capex_nok, lease_yield_pct, int(customer_term_months)
            )

            if bank_financing_enabled:
                bank_balances = amortization_balances(
                    bank_loan_principal, bank_rate_pct, int(bank_term_months)
                )
                lease_balances_padded = lease_balances + [0.0] * (total_term_months - len(lease_balances))
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
        "The vessel TC-rate (Tab 1) plus the customer-facing lease payment "
        "(Tab 2, when switched on), annualized and spread over the vessel's "
        "operating days."
    )

    if not lease_enabled:
        st.info(
            "Leased equipment is currently **off** (see the Lease spread tab). "
            "The figures below show the vessel TC-rate only."
        )

    active_lease_monthly = lease_monthly_payment if lease_enabled else 0.0
    lease_annual = active_lease_monthly * 12
    lease_daily = lease_annual / operating_days if operating_days else 0

    active_lease_opex_monthly = lease_opex_monthly_nok if lease_enabled else 0.0
    lease_opex_annual = active_lease_opex_monthly * 12
    lease_opex_daily = lease_opex_annual / operating_days if operating_days else 0

    total_tc_annual = vessel_tc_annual + lease_annual + lease_opex_annual
    total_tc_daily = vessel_tc_daily + lease_daily + lease_opex_daily
    total_tc_monthly = vessel_tc_monthly + active_lease_monthly + active_lease_opex_monthly

    combined_df = pd.DataFrame(
        [
            {
                "Component": "Vessel TC-rate",
                "Daily": vessel_tc_daily,
                "Monthly": vessel_tc_monthly,
                "Annual": vessel_tc_annual,
            },
            {
                "Component": "Lease payment (customer leg)"
                             + ("" if lease_enabled else " — off"),
                "Daily": lease_daily,
                "Monthly": active_lease_monthly,
                "Annual": lease_annual,
            },
            {
                "Component": "Lease opex (pass-through)"
                             + ("" if lease_enabled else " — off"),
                "Daily": lease_opex_daily,
                "Monthly": active_lease_opex_monthly,
                "Annual": lease_opex_annual,
            },
            {
                "Component": "TOTAL TC-rate",
                "Daily": total_tc_daily,
                "Monthly": total_tc_monthly,
                "Annual": total_tc_annual,
            },
        ]
    )
    show_table(combined_df, "Component", width="stretch")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total TC-rate, daily", fmt(total_tc_daily))
    m2.metric("Total TC-rate, monthly", fmt(total_tc_monthly))
    m3.metric("Total TC-rate, annual", fmt(total_tc_annual))

    st.caption(
        "**Note:** if the customer lease term is shorter than the bank loan term "
        "(see the Lease spread tab), this combined figure reflects the period "
        "while the lease is active. During any tail period, the vessel's TC-rate "
        "no longer includes the equipment lease payment, but the bank loan "
        "obligation continues separately."
    )

# ===========================================================================
# TAB 4 — Financial Statements (monthly & annual, horizontal layout)
# ===========================================================================
with tab_financials:
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
            "Corporate tax rate (%)", min_value=0.0, value=22.0, step=0.5, key="tax_rate", disabled=locked
        )

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

    monthly_revenue_vessel_base = vessel_tc_monthly

    st.subheader("TC contract schedule")
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
            "Contract 1 length (months)", min_value=1, value=int(horizon_months),
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
                    f"Contract {i} length (months) — 0 to skip", min_value=0, value=0,
                    step=1, key=f"contract{i}_length", disabled=locked
                )
            else:
                length = None  # contract 4 always runs to the end of the horizon
                st.markdown("Contract 4 runs to the end of the horizon (if reached)")
        with rcol2:
            new_annual_rate = nok_input(
                f"Contract {i} new TC-rate (NOK/year)", f"contract{i}_rate_nok",
                float(vessel_tc_annual), key=f"contract{i}_rate_input", disabled=locked
            )
        with rcol3:
            capex_delta = nok_input(
                f"Contract {i} capex adjustment (NOK)", f"contract{i}_capex_delta_nok",
                0.0, key=f"contract{i}_capex_delta_input", disabled=locked
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

    def _get_vessel_revenue(month):
        """Base monthly TC-revenue for this month's active contract, escalated
        from that contract's own start (first adjustment 12 months in)."""
        return _revenue_for_contracts(tc_contracts, month)

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

    if monthly_revenue_vessel_base < (monthly_opex_vessel_base + debt_schedule[0]["Monthly finance cost"]):
        st.warning(
            "**Note:** the vessel TC-rate (Tab 1) is built from required EBITDA + "
            "vessel opex only — it does not include debt finance cost or tax. "
            "Depending on your inputs, monthly revenue may not fully cover opex + "
            "finance cost + tax; check the P&L for negative net income if that "
            "matters for your analysis."
        )

    def _row_or_zero(schedule, month, term_months):
        if month <= term_months and month <= len(schedule):
            return schedule[month - 1]
        return {"Finance cost": 0.0, "Amortization": 0.0, "Closing balance": 0.0}

    def _escalation_factor(rate_pct, month):
        year_number = (month - 1) // 12 + 1  # Year 1 = months 1-12
        escalation_periods = year_number - 1  # 0 in Year 1, 1 in Year 2 (month 13+), ...
        return (1 + rate_pct / 100) ** escalation_periods

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
                projected_monthly_opex = sum(
                    item["monthly"] * _escalation_factor(item["escalator_pct"], target_month_for_projection)
                    for item in opex_line_items_base
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
            monthly_revenue_vessel = _get_vessel_revenue(month)

            if lease_enabled and month <= int(customer_term_months):
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
            monthly_opex_vessel = 0.0
            for item in opex_line_items_base:
                factor = _escalation_factor(item["escalator_pct"], month)
                escalated_value = item["monthly"] * factor
                escalated_opex_items.append({"name": item["name"], "value": escalated_value})
                monthly_opex_vessel += escalated_value

            maintenance_factor = _escalation_factor(maintenance_escalator_pct, month)
            monthly_maintenance = monthly_maintenance_base * maintenance_factor

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
            revenue = monthly_revenue_vessel + lease_revenue_this_month + lease_opex_this_month
            ebitda_vessel = monthly_revenue_vessel - monthly_opex_vessel
            ebitda_equipment = lease_revenue_this_month  # pass-through opex nets to zero
            ebitda = ebitda_vessel + ebitda_equipment
            ebit = ebitda - monthly_vessel_depreciation - equipment_depreciation_this_month
            finance_cost_total = vessel_finance_cost + equipment_finance_cost + operational_finance_cost
            ebt = ebit - finance_cost_total
            tax = ebt * (tax_rate_pct / 100)
            net_income = ebt - tax

            pnl_row = {"Month": month}
            pnl_row["TC-revenue"] = monthly_revenue_vessel
            pnl_row["Lease-revenue"] = lease_revenue_this_month
            pnl_row["Pass-through costs"] = lease_opex_this_month
            pnl_row["Total revenue"] = revenue
            for item in escalated_opex_items:
                pnl_row[item["name"]] = -item["value"]
            pnl_row["Equipment opex (pass-through)"] = -lease_opex_this_month
            pnl_row["EBITDA — vessel"] = ebitda_vessel
            pnl_row["EBITDA — equipment"] = ebitda_equipment
            pnl_row["EBITDA"] = ebitda
            pnl_row["Depreciation — vessel"] = -monthly_vessel_depreciation
            pnl_row["Depreciation — equipment"] = -equipment_depreciation_this_month
            pnl_row["EBIT"] = ebit
            pnl_row["Finance cost — vessel (bank)"] = -vessel_finance_cost
            pnl_row["Finance cost — equipment (leasing company)"] = -equipment_finance_cost
            pnl_row["Finance cost — operational funding"] = -operational_finance_cost
            pnl_row["EBT"] = ebt
            pnl_row["Tax"] = -tax
            pnl_row["Net income"] = net_income
            pnl_rows_.append(pnl_row)

            # --- working capital: tracks the current (escalated) vessel run-rate ---
            daily_revenue_now = monthly_revenue_vessel * 12 / 365
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
                - monthly_maintenance + refinancing_proceeds_this_month - capex_adjustment_this_month
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
                "Capex adjustment (vessel upgrade/downgrade)": -capex_adjustment_this_month,
                "Refinancing proceeds (vessel)": refinancing_proceeds_this_month,
                "Operational funding injected (equity + debt)": 0.0,
                "Cash flow for the period": cash_flow_for_period,
                "Cash balance": cumulative_cash,
            })

            cumulative_vessel_depreciation += monthly_vessel_depreciation
            cumulative_equipment_depreciation += equipment_depreciation_this_month
            cumulative_maintenance_capex += monthly_maintenance
            cumulative_capex_adjustment += capex_adjustment_this_month
            vessel_nbv = capex_nok - cumulative_vessel_depreciation + cumulative_maintenance_capex + cumulative_capex_adjustment
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
        opex = sum(
            item["monthly"] * _escalation_factor(item["escalator_pct"], month)
            for item in opex_line_items_base
        )
        ebitda_v = revenue - opex
        if lease_enabled and month <= int(customer_term_months):
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
        ratio_df.to_excel(writer, sheet_name="Summary ratios")
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
# Force exactly one automatic rerun after the very first script execution.
# Tab 1's "Sources & Uses" reads a value computed on Tab 4 (which runs later
# in this script) — on a true first load, Tab 1 renders before that value
# exists. This rerun makes sure even a passive, never-interacts viewer sees
# the correct number immediately, without needing to touch anything.
# ---------------------------------------------------------------------------

if not st.session_state.get("_initial_rerun_done"):
    st.session_state["_initial_rerun_done"] = True
    st.rerun()
