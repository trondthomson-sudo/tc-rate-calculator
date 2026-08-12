"""
TC-rate calculator for a live fish carrier (brønnbåt) — Streamlit app.

Logic:
    TC-rate (pre fuel, lube oil, port fees, and other spot expenses)
        = Required EBITDA (capex x EBITDA-yield %)
        + Vessel opex (sum of named opex line items)

Run locally with:
    pip install streamlit pandas
    streamlit run tc_rate_app.py
"""

import re

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

st.title("⚓ TC-rate calculator — live fish carrier")
st.caption(
    "Required EBITDA return on capex, plus vessel opex, builds up to the "
    "daily / monthly / annual TC-rate."
)

# ---------------------------------------------------------------------------
# Number formatting helpers (space as thousand separator, Norwegian style)
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


def nok_input(label: str, state_key: str, default: float, key: str) -> float:
    """A text input that displays with thousand separators but stores a raw float."""
    if state_key not in st.session_state:
        st.session_state[state_key] = default
    raw_str = st.text_input(
        label, value=format_nok(st.session_state[state_key]), key=key
    )
    value = parse_nok(raw_str)
    st.session_state[state_key] = value
    return value


# ---------------------------------------------------------------------------
# Session state — opex line items (so add/remove persists across reruns)
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


# ---------------------------------------------------------------------------
# Layout: inputs (left) | results (right)
# ---------------------------------------------------------------------------

left, right = st.columns([1, 1.4], gap="large")

# --- LEFT: inputs ---
with left:
    st.subheader("Capital & return")

    capex_nok = nok_input("Capex (NOK)", "capex_nok", 800_000_000.0, key="capex_input")

    ebitda_yield_pct = st.number_input(
        "EBITDA-yield (%)", min_value=0.0, value=12.0, step=0.1
    )
    operating_days = st.number_input(
        "Operating days / year", min_value=1, value=350, step=1
    )

    st.subheader("Vessel opex (annual, NOK)")

    for i, item in enumerate(st.session_state.opex_items):
        c1, c2, c3 = st.columns([2.2, 1.6, 0.4])
        with c1:
            item["name"] = st.text_input(
                "Name", value=item["name"], key=f"name_{i}", label_visibility="collapsed"
            )
        with c2:
            raw_str = st.text_input(
                "Value (NOK)",
                value=format_nok(item["value_nok"]),
                key=f"value_{i}",
                label_visibility="collapsed",
            )
            item["value_nok"] = parse_nok(raw_str)
        with c3:
            st.button("✕", key=f"remove_{i}", on_click=remove_opex_item, args=(i,))

    st.button("+ Add opex line item", on_click=add_opex_item)

    opex_total = sum(item["value_nok"] for item in st.session_state.opex_items)
    st.markdown(f"**Total vessel opex:** {format_nok(opex_total)} NOK")

# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

required_ebitda_annual = capex_nok * (ebitda_yield_pct / 100)
tc_annual = required_ebitda_annual + opex_total
tc_daily = tc_annual / operating_days if operating_days else 0
tc_monthly = tc_daily * (365 / 12)


def fmt(n):
    return format_nok(n) + " NOK"


# --- RIGHT: results ---
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
                    {fmt(tc_annual)}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    chart_rows = [{"Component": "Required EBITDA", "NOK (annual)": required_ebitda_annual}]
    for item in st.session_state.opex_items:
        if item["value_nok"] > 0:
            chart_rows.append({"Component": item["name"], "NOK (annual)": item["value_nok"]})

    chart_df = pd.DataFrame(chart_rows).set_index("Component")
    st.bar_chart(chart_df, horizontal=True)

    st.subheader("TC-rate")

    results_df = pd.DataFrame(
        [
            {
                "Component": "Required EBITDA",
                "Daily": fmt(required_ebitda_annual / operating_days),
                "Monthly": fmt(required_ebitda_annual / operating_days * (365 / 12)),
                "Annual": fmt(required_ebitda_annual),
            },
            {
                "Component": "Vessel opex",
                "Daily": fmt(opex_total / operating_days),
                "Monthly": fmt(opex_total / operating_days * (365 / 12)),
                "Annual": fmt(opex_total),
            },
            {
                "Component": "TC-rate",
                "Daily": fmt(tc_daily),
                "Monthly": fmt(tc_monthly),
                "Annual": fmt(tc_annual),
            },
        ]
    )
    st.dataframe(results_df, hide_index=True, width="stretch")

    m1, m2, m3 = st.columns(3)
    m1.metric("TC-rate, daily", fmt(tc_daily))
    m2.metric("TC-rate, monthly", fmt(tc_monthly))
    m3.metric("TC-rate, annual", fmt(tc_annual))

    st.caption(
        "**Scope:** this TC-rate covers capital return and vessel opex only. "
        "Fuel, lubrication oil, port fees, and other spot expenses are excluded "
        "and typically sit for charterer's account."
    )
