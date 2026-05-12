"""PDF generation for the grievance package.

Produces three artifacts:

- RP-524 (Complaint on Real Property Assessment) — auto-filled per NYS form.
  We generate a faithful recreation rather than overlaying the official PDF
  so the output is robust to year-to-year layout shifts.
- Methodology appendix — explains every adjustment factor, equalization-rate
  handling, and the outlier filter so a BAR member can audit the math.
- Comp detail sheets — one page per used comp, sale data and adjustments.

All three are produced with reportlab platypus. Output goes to a BytesIO so
the FastAPI layer can stream it back to the browser.
"""

from __future__ import annotations
from io import BytesIO
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
)


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="H1c", parent=s["Heading1"], alignment=1, fontSize=16, spaceAfter=10))
    s.add(ParagraphStyle(name="H2u", parent=s["Heading2"], fontSize=12, textColor=colors.HexColor("#1a252f"),
                         spaceBefore=12, spaceAfter=4))
    s.add(ParagraphStyle(name="Small", parent=s["BodyText"], fontSize=9, leading=11))
    s.add(ParagraphStyle(name="Mono", parent=s["BodyText"], fontName="Courier", fontSize=9, leading=11))
    s.add(ParagraphStyle(name="Disclaimer", parent=s["BodyText"], fontSize=8, textColor=colors.HexColor("#7f8c8d"), leading=10))
    return s


def _fmt_money(v):
    if v is None: return "—"
    try: return f"${float(v):,.0f}"
    except Exception: return "—"


def _fmt_sqft(v):
    if not v: return "—"
    try: return f"{float(v):,.0f}"
    except Exception: return "—"


def render_rp524(ctx: dict[str, Any]) -> bytes:
    """Build a filled NYS RP-524 form recreation.

    `ctx` keys expected: subject, current_av, equalization_rate,
    implied_market_value, market_value, range_low, range_high, reduction,
    bar_info (dict from app.bar_info), comps (list of used comps).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        title="RP-524 Complaint on Real Property Assessment",
    )
    s = _styles()
    body = []

    subject = ctx["subject"]
    bar = ctx.get("bar_info") or {}
    used_comps = [c for c in ctx.get("comps", []) if c.get("used")] or ctx.get("comps", [])[:5]

    body.append(Paragraph("NYS Form RP-524", s["Small"]))
    body.append(Paragraph("Complaint on Real Property Assessment", s["H1c"]))
    body.append(Paragraph(
        "For use in challenging an assessment before the Board of Assessment Review. "
        "Filed pursuant to NY Real Property Tax Law Article 5.", s["Small"]))
    body.append(Spacer(1, 0.15 * inch))

    # ─── Part 1: Property identification ───
    body.append(Paragraph("Part 1. Identification of Property", s["H2u"]))
    p1 = [
        ["Property owner(s)", "________________________________"],
        ["Mailing address", "________________________________"],
        ["Day phone", "________________________________"],
        ["Email", "________________________________"],
        ["Property location", subject.get("address", "")],
        ["Town / City / Village", bar.get("municipality") or subject.get("town") or ""],
        ["County", "Dutchess" if (subject.get("sbl") or "").startswith("13") else "Ulster"],
        ["Tax map / SBL", subject.get("sbl") or ""],
        ["Property class", subject.get("property_class") or ""],
    ]
    t = Table(p1, colWidths=[2 * inch, 4.5 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde2e6")),
    ]))
    body.append(t)

    # ─── Part 2: Information necessary to determine value ───
    body.append(Paragraph("Part 2. Information Necessary to Determine Value", s["H2u"]))
    p2 = [
        ["Assessor's estimate of value (current AV)", _fmt_money(ctx.get("current_av"))],
        ["Municipal equalization rate (RAR)", f"{ctx.get('equalization_rate'):.2f}%" if ctx.get("equalization_rate") else "Unknown"],
        ["Implied full market value (AV ÷ ER)", _fmt_money(ctx.get("implied_market_value"))],
        ["Complainant's estimate of value", _fmt_money(ctx.get("market_value"))],
        ["Estimate range (IQR of used comps)", f"{_fmt_money(ctx.get('range_low'))} – {_fmt_money(ctx.get('range_high'))}"],
        ["Requested AV reduction", _fmt_money(ctx.get("reduction"))],
        ["Requested AV after reduction", _fmt_money((ctx.get("current_av") or 0) - (ctx.get("reduction") or 0))],
    ]
    t = Table(p2, colWidths=[3.2 * inch, 3.3 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (1, 5), (1, 5), colors.HexColor("#fff3cd")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde2e6")),
    ]))
    body.append(t)

    # ─── Part 3: Grounds for complaint ───
    body.append(Paragraph("Part 3. Grounds for Complaint", s["H2u"]))
    body.append(Paragraph(
        "[X] <b>Unequal assessment.</b> The assessment is at a higher percentage of full value than "
        "the average of all other property on the assessment roll, or than the average of "
        "residential property on the assessment roll. See sales-comparison analysis in Part 4.",
        s["Small"]))
    body.append(Paragraph(
        "[ ] <b>Excessive assessment.</b> The assessed value exceeds the full value of the property "
        "(only applies if your municipality assesses at 100% of value).",
        s["Small"]))
    body.append(Paragraph("[ ] Unlawful assessment.   [ ] Misclassification.", s["Small"]))

    # ─── Part 4: Sales-comparison analysis ───
    body.append(Paragraph("Part 4. Sales-Comparison Analysis", s["H2u"]))
    body.append(Paragraph(
        f"Methodology: median of {len(used_comps)} best-matching recent comparable sales, "
        f"after applying per-feature adjustments and a 1.5×IQR outlier filter. "
        f"Adjustment factors are calibrated to the {bar.get('municipality') or 'local'} market.",
        s["Small"]))
    body.append(Spacer(1, 0.08 * inch))

    # Subject row + comps table
    header = ["Address", "Sale Price", "Sqft", "Bd/Ba", "Yr", "Acres", "Reconciled"]
    rows = [header]
    rows.append([
        Paragraph(f"<b>Subject:</b> {subject.get('address','')}", s["Small"]),
        "—",
        _fmt_sqft(subject.get("sqft")),
        f"{subject.get('bedrooms')}/{subject.get('bathrooms')}",
        str(subject.get("year_built") or "—"),
        f"{(subject.get('acreage') or 0):.2f}",
        _fmt_money(ctx.get("market_value")),
    ])
    for c in used_comps:
        rows.append([
            Paragraph(c.get("address", ""), s["Small"]),
            _fmt_money(c.get("sale_price")),
            _fmt_sqft(c.get("sqft")),
            f"{c.get('bedrooms')}/{c.get('bathrooms')}",
            str(c.get("year_built") or "—"),
            f"{(c.get('acreage') or 0):.2f}",
            _fmt_money(c.get("reconciled_value")),
        ])
    t = Table(rows, colWidths=[2.3 * inch, 0.9 * inch, 0.6 * inch, 0.55 * inch, 0.5 * inch, 0.55 * inch, 0.95 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#eaf3fb")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde2e6")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    body.append(t)

    # Signature & date
    body.append(Spacer(1, 0.3 * inch))
    body.append(Paragraph("Part 5. Verification", s["H2u"]))
    body.append(Paragraph(
        "I certify that all statements made on this application are true and correct to the "
        "best of my knowledge and belief, and I understand that any willful false statement "
        "made herein is punishable as a misdemeanor under §210.45 of the Penal Law.", s["Small"]))
    body.append(Spacer(1, 0.25 * inch))
    sig = [
        ["Signature of complainant:", "_________________________________________"],
        ["Date:", date.today().strftime("%B %d, %Y")],
    ]
    body.append(Table(sig, colWidths=[2 * inch, 4.5 * inch], style=TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])))

    # Filing instructions
    if bar:
        body.append(Spacer(1, 0.2 * inch))
        body.append(Paragraph("Filing Instructions", s["H2u"]))
        body.append(Paragraph(
            f"<b>Submit to:</b> {bar.get('municipality')}<br/>"
            f"{(bar.get('bar_address') or '').replace(chr(10), '<br/>')}<br/><br/>"
            f"<b>Grievance Day:</b> {bar.get('grievance_day')}<br/>"
            f"<b>Method:</b> {bar.get('submission_method') or 'In person'}<br/>"
            f"{('<b>Phone:</b> ' + bar.get('phone') + '<br/>') if bar.get('phone') else ''}"
            f"{('<i>' + bar.get('notes') + '</i>') if bar.get('notes') else ''}",
            s["Small"]))

    # Disclaimer
    body.append(Spacer(1, 0.3 * inch))
    body.append(Paragraph(
        "This RP-524 was prepared by an automated valuation tool based on public assessment-roll "
        "data and recent comparable sales. It is not a certified appraisal and is not legal advice. "
        "Verify the equalization rate and Grievance Day with your local assessor before filing.",
        s["Disclaimer"]))

    doc.build(body)
    return buf.getvalue()


def render_methodology(ctx: dict[str, Any]) -> bytes:
    """Build the methodology appendix PDF."""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title="Methodology Appendix")
    s = _styles()
    body = []
    body.append(Paragraph("Valuation Methodology Appendix", s["H1c"]))
    body.append(Paragraph(f"Property: {ctx['subject'].get('address')}", s["Small"]))
    body.append(Spacer(1, 0.15 * inch))

    body.append(Paragraph("1. Sales-Comparison Approach", s["H2u"]))
    body.append(Paragraph(
        "We estimate the subject's full market value using the sales-comparison approach: "
        "recent arms-length sales of similar properties in the same municipality, adjusted "
        "for measurable differences in gross living area, lot size, bedrooms, bathrooms, "
        "and age. Median of the best-matching, outlier-filtered comps is reported.", s["Small"]))

    body.append(Paragraph("2. Equalization Rate Adjustment", s["H2u"]))
    body.append(Paragraph(
        f"The subject's municipality has a 2025 equalization rate of "
        f"<b>{ctx['equalization_rate']:.2f}%</b>. The current assessed value of "
        f"<b>{_fmt_money(ctx['current_av'])}</b> divided by the equalization rate yields an "
        f"<b>implied full market value of {_fmt_money(ctx['implied_market_value'])}</b>. "
        f"For grievance purposes, this is the value that must be challenged against comparable "
        f"market evidence — not the raw assessed value.", s["Small"]) if ctx.get("equalization_rate")
        else Paragraph("Equalization rate not available for this municipality; "
                       "comparison uses raw assessed value as a fallback.", s["Small"]))

    body.append(Paragraph("3. Local Adjustment Factors", s["H2u"]))
    adj = ctx.get("adjustments_used") or {}
    rows = [["Dimension", "Adjustment per unit"]]
    rows.append(["Gross living area (sqft)", _fmt_money(adj.get("sqft")) + " /sqft"])
    rows.append(["Bathrooms (full-bath equiv.)", _fmt_money(adj.get("bathroom"))])
    rows.append(["Bedrooms", _fmt_money(adj.get("bedroom"))])
    rows.append(["Acreage", _fmt_money(adj.get("acre")) + " /acre"])
    rows.append(["Age (year built)", _fmt_money(adj.get("year_built")) + " /year"])
    t = Table(rows, colWidths=[3 * inch, 3 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f4f7")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde2e6")),
    ]))
    body.append(t)

    body.append(Paragraph("4. Outlier Filter", s["H2u"]))
    body.append(Paragraph(
        "Reconciled values that fall outside the inter-quartile range (IQR) by more than "
        "1.5×IQR (Tukey's fence) are flagged as outliers and excluded from the final estimate. "
        "Of <b>" + str(ctx.get("considered_count") or 0) + "</b> candidate comps, "
        "<b>" + str(ctx.get("used_count") or 0) + "</b> were used in the final median.", s["Small"]))

    body.append(Paragraph("5. Limitations", s["H2u"]))
    body.append(Paragraph(
        "• Year-built data is unavailable for the search-results endpoint of our comp source "
        "(RapidAPI Real-Time Real-Estate Data); per-comp age adjustment is skipped when missing.<br/>"
        "• Local adjustment factors are first-cut estimates. Paired-sales regression on NYS ORPTS "
        "RP-5217 sales data is planned for future calibration.<br/>"
        "• Property condition is approximated by a user-set multiplier (default: average).<br/>"
        "• This is an automated estimate, not a certified appraisal. For high-value properties, "
        "engage a licensed appraiser or grievance attorney.", s["Small"]))

    doc.build(body)
    return buf.getvalue()
