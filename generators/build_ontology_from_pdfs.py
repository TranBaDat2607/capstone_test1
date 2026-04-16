"""
generators/build_ontology_from_pdfs.py
# -*- coding: utf-8 -*-

Regenerates ontology/framework_indicators.json from actual PDF sources.
No LLM required — uses pdfplumber + regex only.

Coverage:
  - GRI 302 Energy 2016          → extracted from PDF
  - GRI 303 Water and Effluents  → extracted from PDF
  - GRI 305 Emissions 2016       → extracted from PDF
  - GRI 306 Effluents and Waste  → extracted from PDF
  - TT96/2020 indicators         → kept manually (appendix PDFs not available)
  - TT08/2026 indicators         → kept manually (standard not yet published as PDF)
  - TCFD indicators              → kept manually (official recommendations)

Usage:
  python generators/build_ontology_from_pdfs.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber not installed. Run: pip install pdfplumber")

# Fix Windows console encoding for Vietnamese characters
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # Python < 3.7

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
GRI_DIR = ROOT / "data" / "raw" / "gri_indicators"
ONTOLOGY_DIR = ROOT / "ontology"

GRI_PDFS = {
    "GRI 302": GRI_DIR / "GRI 302 Energy 2016.pdf",
    "GRI 303": GRI_DIR / "GRI 303 Water and Effluents 2018.pdf",
    "GRI 305": GRI_DIR / "GRI 305 Emissions 2016.pdf",
    "GRI 306": GRI_DIR / "GRI 306 Effluents and Waste 2016.pdf",
}

# ---------------------------------------------------------------------------
# Category / pillar / unit inference tables
# ---------------------------------------------------------------------------
STANDARD_META = {
    "GRI 302": {"category": "Energy",     "pillar": "E"},
    "GRI 303": {"category": "Water",      "pillar": "E"},
    "GRI 305": {"category": "Emissions",  "pillar": "E"},
    "GRI 306": {"category": "Waste",      "pillar": "E"},
}

# Units commonly mentioned in each standard — used for best-guess unit field
UNIT_HINTS = {
    "302": {"default": "GJ",        "patterns": [r"\bGJ\b", r"gigajoule", r"joules", r"watt.hour"]},
    "303": {"default": "m³",        "patterns": [r"\bm3\b", r"megaliter", r"ML\b", r"cubic meter"]},
    "305": {"default": "metric ton CO2e", "patterns": [r"metric ton", r"tCO2", r"CO2.equivalent", r"mt CO2"]},
    "306": {"default": "metric ton", "patterns": [r"metric ton", r"tonne", r"\bkg\b", r"kilogram"]},
}

# Keywords per indicator code (will be auto-built from requirement text too)
KEYWORD_SEEDS_EN = {
    "302-1": "energy consumption|fuel|electricity|renewable|non-renewable|heating|cooling|steam|GJ|gigajoule",
    "302-2": "upstream energy|downstream energy|value chain energy|supply chain energy|scope 3 energy",
    "302-3": "energy intensity|intensity ratio|energy per unit",
    "302-4": "reduction energy|energy saving|conservation|efficiency|reductions",
    "302-5": "product energy|service energy|energy requirement|design improvement",
    "303-1": "water interaction|shared resource|water source|water body|water stress",
    "303-2": "water discharge|discharge impact|effluent quality|water management",
    "303-3": "water withdrawal|freshwater|surface water|groundwater|third-party water",
    "303-4": "water discharge|effluent|treatment|destination",
    "303-5": "water consumption|net consumption|water use",
    "305-1": "scope 1|direct emissions|GHG|greenhouse gas|CO2|methane|N2O|HFC|PFC|SF6",
    "305-2": "scope 2|indirect emissions|purchased electricity|energy indirect|location-based|market-based",
    "305-3": "scope 3|other indirect|value chain emissions|upstream|downstream",
    "305-4": "GHG intensity|emissions per unit|carbon intensity",
    "305-5": "GHG reduction|emission reduction|decarbonization|abatement",
    "305-6": "ozone-depleting|ODS|CFC|HCFC|halon",
    "305-7": "NOx|SOx|nitrogen oxides|sulfur oxides|air emissions|particulate|volatile organic",
    "306-1": "waste generation|waste impact|significant waste",
    "306-2": "waste management|waste prevention|circular economy|reuse|recycling strategy",
    "306-3": "waste generated|total waste|hazardous waste|non-hazardous waste",
    "306-4": "waste diverted|reuse|recycling|composting|recovery",
    "306-5": "waste disposal|landfill|incineration|open burning|deep well injection",
}

KEYWORD_SEEDS_VI = {
    "302-1": "tiêu thụ năng lượng|điện tiêu thụ|nhiên liệu|năng lượng tái tạo|năng lượng không tái tạo|tổng năng lượng",
    "302-2": "năng lượng chuỗi cung ứng|năng lượng ngoài tổ chức|hạ nguồn|thượng nguồn",
    "302-3": "cường độ năng lượng|tỷ lệ năng lượng|năng lượng trên đơn vị",
    "302-4": "tiết kiệm năng lượng|giảm tiêu thụ|hiệu quả năng lượng|bảo tồn",
    "302-5": "năng lượng sản phẩm|yêu cầu năng lượng|cải tiến thiết kế",
    "303-1": "tương tác nước|nguồn nước chung|nguồn nước|khan hiếm nước|căng thẳng nước",
    "303-2": "xả thải nước|tác động xả thải|chất lượng nước thải|quản lý nước",
    "303-3": "lấy nước|nước ngọt|nước mặt|nước ngầm|nước từ bên thứ ba",
    "303-4": "xả nước|nước thải|xử lý|điểm đến xả thải",
    "303-5": "tiêu thụ nước|sử dụng nước ròng|lượng nước dùng",
    "305-1": "phạm vi 1|phát thải trực tiếp|khí nhà kính|CO2|metan|GHG",
    "305-2": "phạm vi 2|phát thải gián tiếp|điện mua|năng lượng mua",
    "305-3": "phạm vi 3|chuỗi giá trị|phát thải gián tiếp khác",
    "305-4": "cường độ phát thải|phát thải trên đơn vị|carbon trên doanh thu",
    "305-5": "giảm phát thải|cắt giảm GHG|mục tiêu carbon",
    "305-6": "chất làm suy giảm ozone|ODS|CFC|HCFC",
    "305-7": "NOx|SOx|oxit nitơ|oxit lưu huỳnh|khí thải không khí|bụi mịn",
    "306-1": "phát sinh chất thải|tác động chất thải",
    "306-2": "quản lý chất thải|ngăn ngừa chất thải|kinh tế tuần hoàn|tái sử dụng|tái chế",
    "306-3": "chất thải phát sinh|tổng chất thải|chất thải nguy hại|chất thải không nguy hại",
    "306-4": "chất thải chuyển hướng|tái sử dụng|tái chế|ủ phân|thu hồi",
    "306-5": "xử lý chất thải|chôn lấp|đốt rác|đổ thải lộ thiên",
}

# FIX 1: Clean prose descriptions replacing raw semicolon-joined PDF fragments
DESCRIPTION_EN_OVERRIDES: dict[str, str] = {
    "302-1": "Total energy consumption within the organization from non-renewable and renewable fuel sources, purchased electricity, heating, cooling, and steam (GJ).",
    "302-2": "Energy consumed outside the organization from upstream and downstream value chain activities, in joules or multiples.",
    "302-3": "Energy intensity ratio for the organization calculated as energy consumption divided by an organization-specific output metric.",
    "302-4": "Amount of energy reductions achieved directly from conservation and efficiency initiatives, in joules or multiples.",
    "302-5": "Reductions in energy requirements of sold products and services achieved during the reporting period, in joules or multiples.",
    "303-1": "Description of how the organization interacts with water as a shared resource, including the approach to identifying water-related impacts across operations.",
    "303-2": "Description of minimum standards for effluent discharge quality and how the organization manages water discharge-related impacts on the environment.",
    "303-3": "Total water withdrawal from all sources (surface water, groundwater, seawater, produced water, third-party water) in megaliters, broken down by source.",
    "303-4": "Total water discharge to all destinations in megaliters, broken down by destination, treatment level, and whether reused by another organization.",
    "303-5": "Total water consumption within the organization in megaliters, including water consumed in water-stressed areas.",
    "305-1": "Gross direct (Scope 1) GHG emissions in metric tons of CO2 equivalent, covering CO2, CH4, N2O, HFCs, PFCs, SF6, and NF3.",
    "305-2": "Gross location-based and market-based energy indirect (Scope 2) GHG emissions in metric tons of CO2 equivalent from purchased electricity, heat, cooling, and steam.",
    "305-3": "Gross other indirect (Scope 3) GHG emissions in metric tons of CO2 equivalent from upstream and downstream value chain activities.",
    "305-4": "GHG emissions intensity ratio (metric tons CO2e per organization-specific output metric), covering the gases and scopes included.",
    "305-5": "GHG emissions reduced as a direct result of reduction initiatives in metric tons of CO2 equivalent, excluding reductions from offsets.",
    "305-6": "Production, imports, and exports of ozone-depleting substances (ODS) in metric tons of CFC-11 equivalent.",
    "305-7": "Emissions of nitrogen oxides (NOx), sulfur oxides (SOx), persistent organic pollutants (POP), volatile organic compounds (VOC), hazardous air pollutants (HAP), and particulate matter (PM) in kilograms or multiples.",
    "306-1": "Description of waste generation and significant waste-related impacts across the organization's activities and value chain.",
    "306-2": "Description of actions taken to prevent waste and manage significant waste-related impacts, including circular economy approaches.",
    "306-3": "Total waste generated in metric tons, broken down by hazardous and non-hazardous waste and by composition where applicable.",
    "306-4": "Total waste diverted from disposal in metric tons, broken down by recovery operation (reuse, recycling, composting, recovery of other materials, energy recovery).",
    "306-5": "Total waste directed to disposal in metric tons, broken down by disposal operation (landfill, incineration, open burning, deep-well injection, other).",
}

# FIX 2: Vietnamese descriptions for all 22 PDF-extracted GRI indicators
DESCRIPTION_VI_OVERRIDES: dict[str, str] = {
    "302-1": "Tổng tiêu thụ năng lượng trong tổ chức từ nhiên liệu tái tạo và không tái tạo, điện, hơi nước, sưởi và làm mát mua ngoài (GJ).",
    "302-2": "Năng lượng tiêu thụ bên ngoài tổ chức từ các hoạt động thượng nguồn và hạ nguồn trong chuỗi giá trị, tính bằng joule hoặc bội số.",
    "302-3": "Tỷ lệ cường độ năng lượng của tổ chức, tính bằng tiêu thụ năng lượng chia cho chỉ số đầu ra đặc thù của tổ chức.",
    "302-4": "Lượng năng lượng tiết kiệm được trực tiếp từ các sáng kiến bảo tồn và nâng cao hiệu quả, tính bằng joule hoặc bội số.",
    "302-5": "Giảm yêu cầu năng lượng của sản phẩm và dịch vụ đã bán trong kỳ báo cáo, tính bằng joule hoặc bội số.",
    "303-1": "Mô tả cách tổ chức tương tác với nước như một nguồn tài nguyên chung, bao gồm cách xác định các tác động liên quan đến nước.",
    "303-2": "Mô tả các tiêu chuẩn tối thiểu về chất lượng nước thải xả ra và cách tổ chức quản lý tác động môi trường từ việc xả thải.",
    "303-3": "Tổng lượng nước lấy vào từ mọi nguồn (nước mặt, nước ngầm, nước biển, nước từ bên thứ ba) tính bằng megalít, phân theo nguồn.",
    "303-4": "Tổng lượng nước xả ra tại tất cả các điểm đến tính bằng megalít, phân theo đích đến, mức xử lý và khả năng tái sử dụng.",
    "303-5": "Tổng lượng nước tiêu thụ trong tổ chức tính bằng megalít, bao gồm lượng nước tiêu thụ tại các vùng khan hiếm nước.",
    "305-1": "Tổng phát thải KNK trực tiếp (Phạm vi 1) tính bằng tấn CO2 tương đương, bao gồm CO2, CH4, N2O, HFC, PFC, SF6 và NF3.",
    "305-2": "Tổng phát thải KNK gián tiếp từ năng lượng (Phạm vi 2) theo vị trí và thị trường tính bằng tấn CO2 tương đương từ điện, hơi nước, sưởi và làm mát mua ngoài.",
    "305-3": "Tổng phát thải KNK gián tiếp khác (Phạm vi 3) tính bằng tấn CO2 tương đương từ các hoạt động thượng nguồn và hạ nguồn trong chuỗi giá trị.",
    "305-4": "Tỷ lệ cường độ phát thải KNK (tấn CO2e trên chỉ số đầu ra đặc thù), bao gồm các loại khí và phạm vi phát thải được tính.",
    "305-5": "Phát thải KNK giảm được trực tiếp từ các sáng kiến giảm phát thải tính bằng tấn CO2 tương đương, không bao gồm bù đắp carbon.",
    "305-6": "Sản xuất, nhập khẩu và xuất khẩu các chất làm suy giảm tầng ozone (ODS) tính bằng tấn CFC-11 tương đương.",
    "305-7": "Phát thải NOx, SOx, chất ô nhiễm hữu cơ khó phân hủy (POP), hợp chất hữu cơ dễ bay hơi (VOC), chất ô nhiễm không khí nguy hại (HAP) và bụi hạt (PM) tính bằng kilogram.",
    "306-1": "Mô tả việc phát sinh chất thải và các tác động trọng yếu liên quan đến chất thải trong các hoạt động và chuỗi giá trị của tổ chức.",
    "306-2": "Mô tả các hành động thực hiện để ngăn ngừa chất thải và quản lý các tác động trọng yếu liên quan đến chất thải, bao gồm các cách tiếp cận kinh tế tuần hoàn.",
    "306-3": "Tổng chất thải phát sinh tính bằng tấn, phân theo chất thải nguy hại và không nguy hại, và theo thành phần khi có thể.",
    "306-4": "Tổng chất thải chuyển hướng khỏi xử lý tính bằng tấn, phân theo hình thức thu hồi (tái sử dụng, tái chế, ủ phân, thu hồi năng lượng).",
    "306-5": "Tổng chất thải đưa đến xử lý tính bằng tấn, phân theo phương pháp xử lý (chôn lấp, đốt, đổ lộ thiên, bơm giếng sâu, khác).",
}

# ---------------------------------------------------------------------------
# Extraction hints — guidance for LLM-based claim extraction from ESG reports.
# Keyed by indicator code (e.g. "302-1", "TT96-ENV-1", "TCFD-GOV-A").
# Applied in post-processing to set the "extraction_hint" field on each indicator.
# Indicators not listed here get an auto-generated default based on is_quantitative.
# ---------------------------------------------------------------------------
EXTRACTION_HINTS: dict[str, str] = {
    # --- GRI 302 Energy ---
    "302-1": (
        "Extract the total energy consumption in GJ or kWh for the reporting year, broken down "
        "by renewable and non-renewable sources if available. A valid disclosure contains an "
        "actual measured figure. Statements like 'we aim to reduce energy use' are ASPIRATIONAL "
        "— not a valid quantitative disclosure."
    ),
    "302-2": (
        "Extract energy consumed outside the organization (upstream/downstream value chain) in GJ. "
        "Valid if a specific measured figure is provided. Absence of this for large supply-chain "
        "companies may be a strategic omission."
    ),
    "302-3": (
        "Extract the energy intensity ratio for the reporting year. Must include both the "
        "numerator (energy in GJ) and the denominator metric (revenue, m², FTE, etc.)."
    ),
    "302-4": (
        "Extract quantified energy savings in GJ or kWh achieved through specific initiatives. "
        "Must cite the initiative and the saving — a general efficiency claim without a figure "
        "is NOT a valid disclosure."
    ),
    "302-5": (
        "Extract reductions in energy requirements of sold products/services in GJ. "
        "Relevant for product companies; often not reported by service or IT firms."
    ),
    # --- GRI 303 Water ---
    "303-1": (
        "Look for a description of how the organization interacts with water as a shared resource. "
        "A valid qualitative disclosure names specific water bodies or stress areas and describes "
        "the approach to identifying impacts. Generic 'responsible water use' statements are weak."
    ),
    "303-2": (
        "Look for minimum standards for discharge quality (e.g., compliance with QCVN standards). "
        "A valid disclosure specifies the standards applied and monitoring processes used."
    ),
    "303-3": (
        "Extract total water withdrawal volume in m³ or ML for the reporting year, broken down "
        "by source (surface water, groundwater, third-party). At minimum, total annual volume is required."
    ),
    "303-4": (
        "Extract total water discharge volume in m³, destination type, and treatment level applied."
    ),
    "303-5": (
        "Extract net water consumption in m³ (withdrawal minus discharge). This is different from "
        "total withdrawal — the net figure must account for water returned to source."
    ),
    # --- GRI 305 Emissions ---
    "305-1": (
        "Extract Scope 1 direct GHG emissions in tCO2e for the reporting year. Must include the "
        "GHG accounting standard used (GHG Protocol, ISO 14064, etc.). "
        "'Net Zero by 2040' is a target — NOT a Scope 1 reported disclosure."
    ),
    "305-2": (
        "Extract Scope 2 energy-indirect GHG emissions in tCO2e. Look for location-based and/or "
        "market-based figures. Purchased electricity converted to tCO2e is the main component."
    ),
    "305-3": (
        "Extract Scope 3 other-indirect GHG emissions in tCO2e if reported. Many companies do not "
        "report Scope 3 — note the absence as a potential strategic omission for high-emission sectors."
    ),
    "305-4": (
        "Extract the GHG intensity ratio (tCO2e per revenue unit, per employee, or per product). "
        "Must state both the emissions figure and the denominator metric used."
    ),
    "305-5": (
        "Extract quantified GHG emission reductions in tCO2e achieved from specific reduction "
        "initiatives, excluding offsets. A target like 'reduce by 30% by 2030' is a COMMITTED "
        "claim — not a reported reduction unless the reduction has already been achieved."
    ),
    "305-6": (
        "Extract production, import, and export of ozone-depleting substances in kg CFC-11 "
        "equivalent. Often not applicable for office-based or IT companies."
    ),
    "305-7": (
        "Extract NOx, SOx, or particulate matter emissions in kg. Typically not applicable "
        "for service-sector companies with no direct industrial emissions."
    ),
    # --- GRI 306 Waste ---
    "306-1": (
        "Look for identification of significant waste streams and their environmental impacts. "
        "A valid disclosure names the main waste types and their destination — not just a generic "
        "commitment to reduce waste."
    ),
    "306-2": (
        "Look for specific waste prevention and circular economy actions taken during the year. "
        "Must describe actual initiatives, not just policy intent."
    ),
    "306-3": (
        "Extract total waste generated in metric tons broken down by hazardous and non-hazardous. "
        "Absence of this figure for manufacturing or logistics companies is a significant omission."
    ),
    "306-4": (
        "Extract total waste diverted from disposal (recycled, reused, composted, energy-recovered) "
        "in metric tons with breakdown by recovery method."
    ),
    "306-5": (
        "Extract total waste directed to disposal (landfill, incineration, open burning) in metric "
        "tons with breakdown by disposal method."
    ),
    # --- TT96/2020 indicators ---
    "TT96-ENV-1": (
        "Extract total energy consumption (electricity + fuel) in kWh or GJ. Mandatory under TT96. "
        "Absence of this figure is a compliance gap."
    ),
    "TT96-ENV-2": (
        "Extract Scope 1 + Scope 2 GHG emissions in tCO2e. Mandatory under TT96. "
        "Net-Zero targets are commitments, not annual reported disclosures."
    ),
    "TT96-ENV-3": (
        "Extract total solid waste volume in kg or tons and the disposal method breakdown. "
        "Mandatory under TT96."
    ),
    "TT96-ENV-4": (
        "Extract total water withdrawal by source (m³). Mandatory under TT96."
    ),
    "TT96-ENV-5": (
        "Look for any environmental violations, regulatory fines, or penalties received. "
        "Zero violations must be explicitly stated to be a valid negative disclosure."
    ),
    "TT96-SOC-1": (
        "Extract total headcount broken down by gender and contract type (permanent/temporary). "
        "Mandatory under TT96."
    ),
    "TT96-SOC-2": (
        "Extract total training expenditure (VND) and average training hours per employee per year."
    ),
    "TT96-SOC-3": (
        "Extract number of work-related injuries and occupational disease cases. "
        "Zero incidents must be explicitly stated — absence of the figure is not the same as zero."
    ),
    "TT96-SOC-4": (
        "Look for a description of salary structure and benefit types provided (insurance, "
        "health care, bonus schemes, etc.)."
    ),
    "TT96-SOC-5": (
        "Extract the percentage of women in management or leadership positions."
    ),
    "TT96-GOV-1": (
        "Look for board composition details: total members, number of independent directors, "
        "tenure, and gender breakdown."
    ),
    "TT96-GOV-2": (
        "Look for anti-corruption policy description and training coverage data (% of employees trained)."
    ),
    "TT96-GOV-3": (
        "Look for disclosure of related-party transactions: counterparty name, transaction value, "
        "and material terms."
    ),
    "TT96-GOV-4": (
        "Extract total remuneration paid to board members and senior management in VND."
    ),
    "TT96-GOV-5": (
        "Look for description of the internal control framework and risk management system "
        "(e.g., three-lines-of-defense model, risk register, audit committee)."
    ),
    # --- TT08/2026 indicators ---
    "TT08-CLI-1": (
        "Look for identification of specific physical climate risks (flooding, heat stress, drought) "
        "with assessment of operational exposure. Generic mention of climate change is NOT sufficient."
    ),
    "TT08-CLI-2": (
        "Look for assessment of transition risks: carbon pricing exposure, regulatory changes, "
        "stranded asset risk. Must be specific to the company's operations."
    ),
    "TT08-CLI-3": (
        "Look for scenario analysis results under 1.5°C or 2°C warming. A valid disclosure reports "
        "outcomes of the analysis — not just a statement that analysis was conducted."
    ),
    "TT08-CLI-4": (
        "Look for a net-zero or carbon neutrality commitment WITH specific interim milestones and "
        "target years. 'Net Zero by 2040' alone is ASPIRATIONAL — a valid disclosure includes a "
        "decarbonization pathway with interim targets."
    ),
    "TT08-WAT-1": (
        "Look for identification of operations in water-stressed areas using a recognized tool "
        "(e.g., WRI Aqueduct). Generic water conservation statements are not valid."
    ),
    "TT08-WAT-2": (
        "Extract wastewater treatment volume (m³) and evidence of compliance with QCVN discharge "
        "quality standards."
    ),
    "TT08-WST-1": (
        "Extract hazardous waste volumes generated and disposal method. Must reference Vietnamese "
        "regulatory classification (e.g., QCVN 07)."
    ),
    "TT08-WST-2": (
        "Extract waste diversion rate (%) and description of circular economy initiatives. "
        "A target diversion rate is COMMITTED; an achieved rate is REPORTED."
    ),
    "TT08-LAB-1": (
        "Look for supply chain labour due diligence process including supplier audit scope "
        "and ILO standard references."
    ),
    "TT08-LAB-2": (
        "Look for employee well-being programs: mental health support, EAP, fitness, "
        "work-life balance initiatives."
    ),
    "TT08-GOV-1": (
        "Look for board-level ESG oversight structures: committee mandate, meeting frequency, "
        "and how ESG risks are escalated to the board."
    ),
    "TT08-GOV-2": (
        "Look for explicit linkage between executive pay and ESG KPIs. A policy saying "
        "'ESG is considered' is weak — valid disclosure names specific metrics and weightings."
    ),
    "TT08-GOV-3": (
        "Look for a third-party assurance statement covering ESG data. Note the assurance "
        "provider name and assurance level (limited vs. reasonable)."
    ),
    "TT08-GOV-4": (
        "Look for sustainability report publication date, GRI Content Index, and explicit "
        "statement of TT08 format compliance."
    ),
    "TT08-GOV-5": (
        "Look for description of whistleblower channels (hotline, portal) and non-retaliation "
        "policy. Must be specific — a general ethics policy is not sufficient."
    ),
    # --- TCFD indicators ---
    "TCFD-GOV-A": (
        "Look for board-level climate oversight processes: committee mandates, meeting frequency, "
        "and specific climate agenda items reviewed."
    ),
    "TCFD-GOV-B": (
        "Look for management roles and responsibilities for climate risk: C-suite owner, "
        "reporting lines, and accountability structure."
    ),
    "TCFD-STR-A": (
        "Look for identification of specific climate risks AND opportunities categorized by "
        "short (0-2yr), medium (2-5yr), and long-term (5yr+) horizons."
    ),
    "TCFD-STR-B": (
        "Look for description of how identified climate risks affect business strategy, "
        "product mix, or capital allocation decisions."
    ),
    "TCFD-STR-C": (
        "Look for scenario analysis results: how the business strategy holds up under 1.5°C, "
        "2°C, or higher warming scenarios. Stating that analysis was done is not enough — "
        "outcomes must be described."
    ),
    "TCFD-RSK-A": (
        "Look for the process used to identify and assess climate risks: methodology, tools "
        "(e.g., physical risk mapping), and review frequency."
    ),
    "TCFD-RSK-B": (
        "Look for specific climate risk mitigation or adaptation measures in place, "
        "not just a list of risks."
    ),
    "TCFD-RSK-C": (
        "Look for how climate risk is integrated into the enterprise risk management (ERM) "
        "framework: risk registers, appetite statements, audit committee oversight."
    ),
    "TCFD-MET-A": (
        "Extract the specific metrics used to track climate-related risks and opportunities "
        "(e.g., carbon price assumptions, physical risk scores, climate-adjusted revenue)."
    ),
    "TCFD-MET-B": (
        "Extract Scope 1, 2, and 3 GHG emissions in tCO2e — same data as GRI 305-1/2/3."
    ),
    "TCFD-MET-C": (
        "Extract GHG reduction targets with base year, target year, and % reduction. "
        "Distinguish science-based targets (SBTi-validated) from self-set targets. "
        "A target is a COMMITTED claim; an achieved reduction is a REPORTED claim."
    ),
    # --- Manual extra GRI (Social/Governance) ---
    "401-1": (
        "Extract new hire count and turnover rate by gender and age group. "
        "Valid if specific numerical data is provided for the reporting year."
    ),
    "401-2": (
        "Look for description of benefit types provided to full-time vs. part-time employees "
        "(health insurance, pension, parental leave, etc.)."
    ),
    "401-3": (
        "Extract the number of employees who used parental leave and the return-to-work rate "
        "by gender."
    ),
    "403-1": (
        "Look for OHS management system description: scope, certification status (ISO 45001), "
        "and whether third-party audited."
    ),
    "403-2": (
        "Look for hazard identification and incident investigation process: tools used, "
        "frequency, and who is responsible."
    ),
    "403-3": (
        "Look for occupational health services offered to workers: medical surveillance, "
        "specialist access, health monitoring programs."
    ),
    "403-4": (
        "Look for worker participation mechanisms in OHS: safety committees, consultation "
        "processes, and how worker concerns are addressed."
    ),
    "403-5": (
        "Extract OHS training hours per employee per year and the main topics covered."
    ),
    "403-6": (
        "Look for employee wellness programs beyond OHS requirements: mental health, "
        "fitness, nutrition, EAP programs."
    ),
    "403-7": (
        "Look for OHS requirements extended to suppliers and contractors: audit scope, "
        "contractual clauses, or supplier safety standards."
    ),
    "403-8": (
        "Extract the percentage of workforce covered by an OHS management system."
    ),
    "403-9": (
        "Extract work injury rate (LTIFR or TRI rate) and fatality count for the reporting year. "
        "Zero injuries must be explicitly stated — absence is not the same as zero."
    ),
    "403-10": (
        "Extract the number of occupational disease cases and rate per 200,000 hours worked."
    ),
    "405-1": (
        "Extract governance body and employee diversity breakdown by gender and age group. "
        "Percentage figures are preferred over raw counts."
    ),
    "405-2": (
        "Extract female-to-male base salary ratio by employee category."
    ),
    "205-1": (
        "Extract the number or percentage of operations assessed for corruption risk during "
        "the reporting year."
    ),
    "205-2": (
        "Extract the percentage of governance body members and employees who received "
        "anti-corruption training."
    ),
    "205-3": (
        "Extract the number of confirmed corruption incidents and the disciplinary or legal "
        "actions taken."
    ),
    "2-9": (
        "Look for governance body composition: total members, number of independent directors, "
        "skills matrix, gender, age, and tenure breakdown."
    ),
    "2-10": (
        "Look for board nomination and selection criteria, including diversity requirements "
        "and shareholder nomination process."
    ),
    "2-26": (
        "Look for description of ethics helpline, grievance portal, or concern-raising "
        "mechanism with non-retaliation guarantee."
    ),
    "2-27": (
        "Extract the number and type of non-compliance incidents and total monetary fines "
        "received during the reporting year."
    ),
}

# ---------------------------------------------------------------------------
# Valid claim types per indicator code — used by LLM to classify extracted claims.
# "reported"     — historical measured data with a specific value for the reporting year
# "committed"    — specific target with a year and quantity (binding commitment)
# "aspirational" — vague goal without specific data, timeline, or accountability
# "qualitative"  — policy, process, or management approach description
# Indicators not listed here get a default derived from is_quantitative in post-processing:
#   is_quantitative=True  → ["reported", "committed"]
#   is_quantitative=False → ["reported", "qualitative", "aspirational"]
# ---------------------------------------------------------------------------
VALID_CLAIM_TYPES: dict[str, list[str]] = {
    # Strictly reported-only: these must contain actual measured annual data
    "302-1": ["reported"],
    "302-3": ["reported"],
    "303-3": ["reported"],
    "303-4": ["reported"],
    "303-5": ["reported"],
    "305-1": ["reported"],
    "305-2": ["reported"],
    "305-4": ["reported"],
    "306-3": ["reported"],
    "306-4": ["reported"],
    "306-5": ["reported"],
    "TT96-ENV-1": ["reported"],
    "TT96-ENV-2": ["reported"],
    "TT96-ENV-3": ["reported"],
    "TT96-ENV-4": ["reported"],
    "TT96-SOC-1": ["reported"],
    "TT96-SOC-2": ["reported"],
    "TT96-SOC-3": ["reported"],
    "TT96-SOC-5": ["reported"],
    "403-9": ["reported"],
    "403-10": ["reported"],
    "405-1": ["reported"],
    "405-2": ["reported"],
    "2-27": ["reported"],
    # Reported + committed: both are valid (achieved reductions and forward targets)
    "302-4": ["reported", "committed"],
    "305-3": ["reported", "committed"],
    "305-5": ["reported", "committed"],
    "TT08-WAT-2": ["reported", "committed"],
    "TT08-WST-1": ["reported"],
    "TT08-WST-2": ["reported", "committed"],
    "TCFD-MET-B": ["reported"],
    "TCFD-MET-C": ["reported", "committed"],
    # Commitment-primary: the indicator is explicitly about targets/pathways
    "TT08-CLI-4": ["committed", "aspirational"],
    # Qualitative-only indicators where aspirational is a greenwashing signal
    "TT08-GOV-2": ["reported", "qualitative"],  # pay-link must be actual, not aspirational
    "TT08-GOV-3": ["reported"],                  # assurance is either in place or not
}

# mandatory_for values are now lists at source.
# The post-processing string→list conversion below is kept as a safety net only.
MANDATORY_FOR: dict[str, list[str]] = {
    "302-1": ["REG_TT96_2020", "REG_TT08_2026"],
    "302-2": ["REG_TT08_2026"],
    "302-3": ["REG_TT08_2026"],
    "302-4": ["REG_TT08_2026"],
    # 302-5: voluntary only — key omitted
    "303-1": ["REG_TT08_2026"],
    "303-2": ["REG_TT08_2026"],
    "303-3": ["REG_TT08_2026"],
    "303-4": ["REG_TT08_2026"],
    "303-5": ["REG_TT96_2020", "REG_TT08_2026"],
    "305-1": ["REG_TT96_2020", "REG_TT08_2026"],
    "305-2": ["REG_TT96_2020", "REG_TT08_2026"],
    "305-3": ["REG_TT08_2026"],
    "305-4": ["REG_TT08_2026"],
    "305-5": ["REG_TT08_2026"],
    # 305-6, 305-7: voluntary — keys omitted
    "306-1": ["REG_TT08_2026"],
    "306-2": ["REG_TT08_2026"],
    "306-3": ["REG_TT96_2020", "REG_TT08_2026"],
    "306-4": ["REG_TT08_2026"],
    "306-5": ["REG_TT08_2026"],
    # GRI 2 / 205 / 401 / 403 / 405 — required under TT08 social/governance chapters
    "2-9":   ["REG_TT96_2020", "REG_TT08_2026"],
    "2-10":  ["REG_TT96_2020"],
    "2-26":  ["REG_TT08_2026"],
    "2-27":  ["REG_TT08_2026"],
    "205-2": ["REG_TT96_2020", "REG_TT08_2026"],
    "205-3": ["REG_TT08_2026"],
    "401-1": ["REG_TT96_2020", "REG_TT08_2026"],
    "401-2": ["REG_TT96_2020"],
    "403-9": ["REG_TT96_2020", "REG_TT08_2026"],
    "405-1": ["REG_TT96_2020", "REG_TT08_2026"],
}

QUANTITATIVE_CODES = {
    "302-1", "302-2", "302-3", "302-4", "302-5",
    "303-3", "303-4", "303-5",
    "305-1", "305-2", "305-3", "305-4", "305-5", "305-6", "305-7",
    "306-3", "306-4", "306-5",
}

# GRI 306 2016 has different indicator titles than the 2020 revision used in the pipeline.
# Override titles and categories here so the IDs stay compatible with the rest of the pipeline.
GRI_306_TITLE_OVERRIDES = {
    "306-1": ("Waste generation and significant waste-related impacts", False),
    "306-2": ("Management of significant waste-related impacts", False),
    "306-3": ("Waste generated", True),
    "306-4": ("Waste diverted from disposal", True),
    "306-5": ("Waste directed to disposal", True),
}

# ---------------------------------------------------------------------------
# PDF extraction helpers
# ---------------------------------------------------------------------------

def extract_full_text(pdf_path: Path) -> str:
    """Extract all text from a PDF, one page per section, UTF-8 safe."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


# Pattern: "Disclosure 302-1 Energy consumption within the organization"
# Handles optional line breaks between number and title in some PDFs.
_DISCLOSURE_HEADING = re.compile(
    r"Disclosure\s+(\d{3}-\d+)\s*\n?\s*([A-Z][^\n]{3,80})",
    re.MULTILINE,
)

# Requirement items — lines starting with a letter + period or letter + "."
_REQ_ITEM = re.compile(r"^\s*[a-z]\.\s+(.+)", re.MULTILINE)

# REQUIREMENTS section sentinel
_REQ_SECTION = re.compile(
    r"REQUIREMENTS\s*\n(.*?)(?=Compilation requirements|RECOMMENDATIONS|Guidance for Disclosure|\Z)",
    re.DOTALL,
)


def _infer_unit(code: str, text: str) -> str:
    """Best-guess unit from disclosure text."""
    prefix = code.split("-")[0]
    hints = UNIT_HINTS.get(prefix, {})
    for pat in hints.get("patterns", []):
        if re.search(pat, text, re.IGNORECASE):
            return hints["default"]
    return hints.get("default", "")


def _description_from_requirements(req_text: str, max_chars: int = 300) -> str:
    """Build a compact description from the REQUIREMENTS section items."""
    items = _REQ_ITEM.findall(req_text)
    if not items:
        # Fall back: first two sentences of the block
        sentences = re.split(r"(?<=[.!?])\s+", req_text.strip())
        desc = " ".join(sentences[:2])
    else:
        # Join first 3 items with semicolons
        desc = "; ".join(i.strip() for i in items[:3])
    return desc[:max_chars].strip()


_NOISE_TITLES = re.compile(
    r"^(GUIDANCE|RECOMMENDATIONS|Compilation requirements|"
    r"For an example|Background|Bibliography|Glossary|Note:)",
    re.IGNORECASE,
)

def _is_toc_or_noise_match(title: str, block: str) -> bool:
    """Return True if this match looks like a TOC entry, GUIDANCE, or noise — not the real disclosure section."""
    # TOC entries: title ends with a page number like "...organization 8"
    if re.search(r"\s+\d{1,3}\s*$", title):
        return True
    # GUIDANCE / RECOMMENDATIONS / Compilation sub-sections
    if _NOISE_TITLES.match(title.strip()):
        return True
    # Glossary / bibliography sections that don't contain the requirements narrative
    if not re.search(r"REQUIREMENTS|shall report|reporting organization shall", block[:600]):
        if len(block.strip()) < 300:
            return True
    return False


def parse_gri_pdf(standard: str, pdf_path: Path) -> list[dict]:
    """
    Extract all Disclosure indicators from a GRI topic standard PDF.
    Returns a list of indicator dicts ready for framework_indicators.json.
    Deduplicates by indicator_id, keeping the entry with the richest description.
    """
    print(f"  Parsing {pdf_path.name} ...")
    full_text = extract_full_text(pdf_path)
    meta = STANDARD_META[standard]

    # Find all disclosure headings and their positions
    matches = list(_DISCLOSURE_HEADING.finditer(full_text))
    if not matches:
        print(f"    WARNING: no Disclosure headings found in {pdf_path.name}")
        return []

    # First pass — collect all raw candidates
    candidates: list[dict] = []
    for idx, m in enumerate(matches):
        code = m.group(1).strip()          # e.g. "302-1"
        raw_title = m.group(2).strip()
        # Clean up title — remove page header noise and trailing page numbers
        title = re.sub(r"\s+", " ", raw_title)
        title = re.sub(r"Note:.*", "", title).strip()
        title = re.sub(r"\s+\d{1,3}\s*$", "", title).strip()   # strip trailing page number

        # Slice the text block belonging to this disclosure
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        block = full_text[start:end]

        if _is_toc_or_noise_match(raw_title, block):
            continue

        # Extract REQUIREMENTS block
        req_match = _REQ_SECTION.search(block)
        req_text = req_match.group(1) if req_match else block[:600]

        unit = _infer_unit(code, block)
        indicator_id = f"IND_GRI_{code.replace('-', '_')}"

        # GRI 306 2016 titles differ from 2020 revision — override for pipeline compatibility
        if standard == "GRI 306" and code in GRI_306_TITLE_OVERRIDES:
            title, is_quant = GRI_306_TITLE_OVERRIDES[code]
        else:
            is_quant = code in QUANTITATIVE_CODES

        ind = {
            "indicator_id": indicator_id,
            "framework": "GRI",
            "code": code,
            "standard": standard,
            "title": title,
            "pillar": meta["pillar"],
            "category": meta["category"],
            "is_quantitative": is_quant,
            "source": "pdf_extracted",
            "source_file": pdf_path.name,
        }
        if unit:
            ind["unit"] = unit
        # FIX 3+4: mandatory_for as list, omit key entirely when empty
        mandatory = MANDATORY_FOR.get(code)
        if mandatory:
            ind["mandatory_for"] = mandatory
        # FIX 5: no gri_code on GRI indicators — it's redundant (code already carries this)
        # FIX 1: use clean prose description override instead of raw PDF fragments
        ind["description_en"] = DESCRIPTION_EN_OVERRIDES.get(
            code, _description_from_requirements(req_text)
        )
        # FIX 2: add Vietnamese description
        if code in DESCRIPTION_VI_OVERRIDES:
            ind["description_vi"] = DESCRIPTION_VI_OVERRIDES[code]
        if code in KEYWORD_SEEDS_EN:
            ind["keywords_en"] = KEYWORD_SEEDS_EN[code]
        if code in KEYWORD_SEEDS_VI:
            ind["keywords_vi"] = KEYWORD_SEEDS_VI[code]

        candidates.append(ind)

    # Deduplicate: prefer entries whose title looks like a real indicator title
    # (not GUIDANCE / For an example / etc.), then break ties by longer description_en.
    def _title_score(ind: dict) -> int:
        """Higher = better candidate. Real titles score 1, noise titles score 0."""
        t = ind.get("title", "")
        if _NOISE_TITLES.match(t.strip()):
            return 0
        if re.search(r"^(GUIDANCE|For an example)", t, re.IGNORECASE):
            return 0
        return 1

    seen: dict[str, dict] = {}
    for ind in candidates:
        iid = ind["indicator_id"]
        if iid not in seen:
            seen[iid] = ind
        else:
            prev = seen[iid]
            # Prefer better title score, then longer description
            if (_title_score(ind), len(ind["description_en"])) > \
               (_title_score(prev), len(prev["description_en"])):
                seen[iid] = ind

    indicators = list(seen.values())
    for ind in indicators:
        print(f"    + {ind['indicator_id']}  [{ind['code']}] {ind['title'][:60]}")

    return indicators


# ---------------------------------------------------------------------------
# Manual indicator banks (TT96, TT08, TCFD)
# These are manually maintained because source PDFs are unavailable.
# source: "manual" marks them for future replacement when PDFs are obtained.
# ---------------------------------------------------------------------------

MANUAL_TT96_INDICATORS = [
    {
        "indicator_id": "IND_TT96_ENV_1",
        "framework": "TT96",
        "code": "TT96-ENV-1",
        "standard": "TT96/2020",
        "title": "Tiêu thụ năng lượng (điện, nhiên liệu)",
        "pillar": "E",
        "category": "Energy",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 4.1",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 302-1",
        "description_en": "Total energy consumption (electricity, fuel) within the organization per year.",
        "description_vi": "Tổng tiêu thụ năng lượng (điện, nhiên liệu) của tổ chức trong năm.",
        "keywords_vi": "tiêu thụ năng lượng|điện tiêu thụ|nhiên liệu|tổng năng lượng|kWh|GJ",
        "keywords_en": "energy consumption|electricity|fuel|total energy|kWh|GJ",
    },
    {
        "indicator_id": "IND_TT96_ENV_2",
        "framework": "TT96",
        "code": "TT96-ENV-2",
        "standard": "TT96/2020",
        "title": "Khí thải nhà kính (Phạm vi 1 và 2)",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 4.2",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 305-1",
        "description_en": "Scope 1 and Scope 2 greenhouse gas emissions in tCO2e.",
        "description_vi": "Phát thải khí nhà kính Phạm vi 1 và Phạm vi 2 tính bằng tấn CO2 tương đương.",
        "keywords_vi": "phát thải|khí nhà kính|CO2|phạm vi 1|phạm vi 2|tCO2e",
        "keywords_en": "GHG|emissions|scope 1|scope 2|CO2|tCO2e|greenhouse gas",
    },
    {
        "indicator_id": "IND_TT96_ENV_3",
        "framework": "TT96",
        "code": "TT96-ENV-3",
        "standard": "TT96/2020",
        "title": "Chất thải rắn và xử lý chất thải",
        "pillar": "E",
        "category": "Waste",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 4.3",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 306-3",
        "description_en": "Total solid waste generated and disposal methods used.",
        "description_vi": "Tổng chất thải rắn phát sinh và phương pháp xử lý.",
        "keywords_vi": "chất thải|rác thải|xử lý chất thải|tái chế|chôn lấp|chất thải nguy hại",
        "keywords_en": "waste|solid waste|disposal|recycling|landfill|hazardous waste",
    },
    {
        "indicator_id": "IND_TT96_ENV_4",
        "framework": "TT96",
        "code": "TT96-ENV-4",
        "standard": "TT96/2020",
        "title": "Sử dụng nước và nguồn nước",
        "pillar": "E",
        "category": "Water",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 4.4",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 303-3",
        "description_en": "Total water withdrawal by source.",
        "description_vi": "Tổng lượng nước lấy vào theo nguồn.",
        "keywords_vi": "sử dụng nước|lấy nước|nguồn nước|nước ngầm|nước mặt|tiêu thụ nước",
        "keywords_en": "water use|withdrawal|water source|groundwater|surface water|consumption",
    },
    {
        "indicator_id": "IND_TT96_ENV_5",
        "framework": "TT96",
        "code": "TT96-ENV-5",
        "standard": "TT96/2020",
        "title": "Vi phạm môi trường và xử phạt",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 4.5",
        "mandatory_for": ["REG_TT96_2020"],
        "description_en": "Number and nature of environmental violations and fines received.",
        "description_vi": "Số lượng và tính chất vi phạm môi trường và tiền phạt.",
        "keywords_vi": "vi phạm môi trường|xử phạt|phạt tiền|vi phạm|cơ quan môi trường",
        "keywords_en": "environmental violation|fine|penalty|non-compliance|regulatory violation",
    },
    {
        "indicator_id": "IND_TT96_SOC_1",
        "framework": "TT96",
        "code": "TT96-SOC-1",
        "standard": "TT96/2020",
        "title": "Tổng số nhân viên theo giới tính và loại hợp đồng",
        "pillar": "S",
        "category": "Employment",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 5.1",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 401-1",
        "description_en": "Total number of employees broken down by gender and contract type.",
        "description_vi": "Tổng số nhân viên chia theo giới tính và loại hợp đồng lao động.",
        "keywords_vi": "số nhân viên|lao động|giới tính|hợp đồng lao động|nhân sự",
        "keywords_en": "employees|workforce|gender|contract type|headcount",
    },
    {
        "indicator_id": "IND_TT96_SOC_2",
        "framework": "TT96",
        "code": "TT96-SOC-2",
        "standard": "TT96/2020",
        "title": "Chi phí đào tạo và số giờ đào tạo bình quân",
        "pillar": "S",
        "category": "Employment",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 5.2",
        "mandatory_for": ["REG_TT96_2020"],
        "description_en": "Total training expenditure and average training hours per employee.",
        "description_vi": "Tổng chi phí đào tạo và số giờ đào tạo bình quân mỗi nhân viên.",
        "keywords_vi": "đào tạo|chi phí đào tạo|giờ đào tạo|phát triển nhân viên",
        "keywords_en": "training|training hours|training cost|employee development|learning",
    },
    {
        "indicator_id": "IND_TT96_SOC_3",
        "framework": "TT96",
        "code": "TT96-SOC-3",
        "standard": "TT96/2020",
        "title": "Tai nạn lao động và bệnh nghề nghiệp",
        "pillar": "S",
        "category": "Health_Safety",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 5.3",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 403-9",
        "description_en": "Number of work-related injuries and occupational diseases.",
        "description_vi": "Số ca tai nạn lao động và bệnh nghề nghiệp trong năm.",
        "keywords_vi": "tai nạn lao động|bệnh nghề nghiệp|thương tích|an toàn lao động|tử vong",
        "keywords_en": "work injury|occupational disease|accident|safety|fatality|lost time",
    },
    {
        "indicator_id": "IND_TT96_SOC_4",
        "framework": "TT96",
        "code": "TT96-SOC-4",
        "standard": "TT96/2020",
        "title": "Chính sách lương và phúc lợi nhân viên",
        "pillar": "S",
        "category": "Employment",
        "is_quantitative": False,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 5.4",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 401-2",
        "description_en": "Description of salary policies and employee benefits provided.",
        "description_vi": "Mô tả chính sách lương và phúc lợi dành cho nhân viên.",
        "keywords_vi": "lương|phúc lợi|thu nhập|bảo hiểm|thưởng|đãi ngộ",
        "keywords_en": "salary|wages|benefits|compensation|insurance|bonus",
    },
    {
        "indicator_id": "IND_TT96_SOC_5",
        "framework": "TT96",
        "code": "TT96-SOC-5",
        "standard": "TT96/2020",
        "title": "Tỷ lệ nhân viên nữ trong ban lãnh đạo",
        "pillar": "S",
        "category": "Employment",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục IV — Mục 5.5",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 405-1",
        "description_en": "Percentage of women in management and governance positions.",
        "description_vi": "Tỷ lệ phần trăm phụ nữ trong các vị trí quản lý và quản trị.",
        "keywords_vi": "tỷ lệ nữ|phụ nữ lãnh đạo|bình đẳng giới|đa dạng|ban giám đốc nữ",
        "keywords_en": "female ratio|women leadership|gender diversity|board diversity|women management",
    },
    {
        "indicator_id": "IND_TT96_GOV_1",
        "framework": "TT96",
        "code": "TT96-GOV-1",
        "standard": "TT96/2020",
        "title": "Thành phần Hội đồng quản trị",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": False,
        "source": "manual",
        "tt96_article": "Phụ lục V — Mục 1",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 2-9",
        "description_en": "Board composition including number of members, independence status, and diversity.",
        "description_vi": "Thành phần HĐQT bao gồm số thành viên, tính độc lập và đa dạng.",
        "keywords_vi": "hội đồng quản trị|thành viên HĐQT|thành viên độc lập|quản trị|ban kiểm soát",
        "keywords_en": "board composition|board members|independent directors|governance|supervisory board",
    },
    {
        "indicator_id": "IND_TT96_GOV_2",
        "framework": "TT96",
        "code": "TT96-GOV-2",
        "standard": "TT96/2020",
        "title": "Chính sách chống tham nhũng và hối lộ",
        "pillar": "G",
        "category": "Anti_corruption",
        "is_quantitative": False,
        "source": "manual",
        "tt96_article": "Phụ lục V — Mục 4",
        "mandatory_for": ["REG_TT96_2020"],
        "gri_code": "GRI 205-2",
        "description_en": "Anti-corruption and anti-bribery policies, training, and incident reporting.",
        "description_vi": "Chính sách chống tham nhũng và hối lộ, đào tạo và báo cáo sự cố.",
        "keywords_vi": "chống tham nhũng|hối lộ|đạo đức kinh doanh|tuân thủ|vi phạm",
        "keywords_en": "anti-corruption|anti-bribery|ethics|compliance|violation|training",
    },
    {
        "indicator_id": "IND_TT96_GOV_3",
        "framework": "TT96",
        "code": "TT96-GOV-3",
        "standard": "TT96/2020",
        "title": "Giao dịch với bên liên quan",
        "pillar": "G",
        "category": "Transparency",
        "is_quantitative": False,
        "source": "manual",
        "tt96_article": "Phụ lục V — Mục 5",
        "mandatory_for": ["REG_TT96_2020"],
        "description_en": "Disclosure of related-party transactions and their material terms.",
        "description_vi": "Công bố giao dịch với bên liên quan và các điều khoản trọng yếu.",
        "keywords_vi": "giao dịch bên liên quan|người có liên quan|công ty liên kết|minh bạch",
        "keywords_en": "related party|related transactions|affiliated|transparency|disclosure",
    },
    {
        "indicator_id": "IND_TT96_GOV_4",
        "framework": "TT96",
        "code": "TT96-GOV-4",
        "standard": "TT96/2020",
        "title": "Thù lao Hội đồng quản trị và Ban điều hành",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": True,
        "source": "manual",
        "tt96_article": "Phụ lục V — Mục 3",
        "mandatory_for": ["REG_TT96_2020"],
        "description_en": "Total remuneration paid to board members and senior management.",
        "description_vi": "Tổng thù lao trả cho thành viên HĐQT và ban điều hành.",
        "keywords_vi": "thù lao HĐQT|lương ban điều hành|thù lao lãnh đạo|chi phí quản lý",
        "keywords_en": "board remuneration|executive compensation|management salary|director fees",
    },
    {
        "indicator_id": "IND_TT96_GOV_5",
        "framework": "TT96",
        "code": "TT96-GOV-5",
        "standard": "TT96/2020",
        "title": "Kiểm soát nội bộ và quản lý rủi ro",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": False,
        "source": "manual",
        "tt96_article": "Phụ lục V — Mục 6",
        "mandatory_for": ["REG_TT96_2020"],
        "description_en": "Internal control framework and risk management practices.",
        "description_vi": "Khung kiểm soát nội bộ và thực hành quản lý rủi ro.",
        "keywords_vi": "kiểm soát nội bộ|quản lý rủi ro|kiểm toán nội bộ|hệ thống kiểm soát",
        "keywords_en": "internal control|risk management|internal audit|control system",
    },
]

MANUAL_TT08_INDICATORS = [
    {
        "indicator_id": "IND_TT08_CLI_1",
        "framework": "TT08",
        "code": "TT08-CLI-1",
        "standard": "TT08/2026",
        "title": "Physical climate risks (flooding, heat stress, drought)",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 3 — Khoản 1",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Identification and assessment of physical climate risks including flooding, extreme heat, and drought.",
        "description_vi": "Xác định và đánh giá rủi ro khí hậu vật lý bao gồm lũ lụt, nắng nóng cực đoan và hạn hán.",
        "keywords_vi": "rủi ro khí hậu vật lý|lũ lụt|nắng nóng|hạn hán|biến đổi khí hậu",
        "keywords_en": "physical climate risk|flood|heat stress|drought|climate change|TCFD",
    },
    {
        "indicator_id": "IND_TT08_CLI_2",
        "framework": "TT08",
        "code": "TT08-CLI-2",
        "standard": "TT08/2026",
        "title": "Transition climate risks (policy, regulatory, stranded assets)",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 3 — Khoản 2",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Transition risks from climate policy changes, carbon pricing, and technology shifts.",
        "description_vi": "Rủi ro chuyển đổi từ thay đổi chính sách khí hậu, định giá carbon và thay đổi công nghệ.",
        "keywords_vi": "rủi ro chuyển đổi|chính sách carbon|tài sản mắc kẹt|chuyển đổi năng lượng",
        "keywords_en": "transition risk|carbon pricing|stranded assets|energy transition|policy risk",
    },
    {
        "indicator_id": "IND_TT08_CLI_3",
        "framework": "TT08",
        "code": "TT08-CLI-3",
        "standard": "TT08/2026",
        "title": "Climate scenario analysis (1.5°C, 2°C, baseline)",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 3 — Khoản 3",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Scenario analysis of business resilience under 1.5°C, 2°C, and baseline warming scenarios.",
        "description_vi": "Phân tích kịch bản khả năng chịu đựng kinh doanh theo kịch bản ấm lên 1.5°C, 2°C và cơ sở.",
        "keywords_vi": "phân tích kịch bản|1.5 độ|2 độ|khả năng chịu đựng|kịch bản khí hậu",
        "keywords_en": "scenario analysis|1.5°C|2°C|resilience|climate scenario|IPCC",
    },
    {
        "indicator_id": "IND_TT08_CLI_4",
        "framework": "TT08",
        "code": "TT08-CLI-4",
        "standard": "TT08/2026",
        "title": "Net-zero commitment and decarbonization pathway",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 3 — Khoản 4",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 305-5",
        "description_en": "Net-zero or carbon neutrality commitment with decarbonization milestones.",
        "description_vi": "Cam kết trung hòa carbon/net-zero với các cột mốc khử carbon.",
        "keywords_vi": "trung hòa carbon|net-zero|khử carbon|lộ trình giảm phát thải|cam kết 2050",
        "keywords_en": "net-zero|carbon neutrality|decarbonization|emission reduction pathway|2050",
    },
    {
        "indicator_id": "IND_TT08_WAT_1",
        "framework": "TT08",
        "code": "TT08-WAT-1",
        "standard": "TT08/2026",
        "title": "Water stress area disclosure and dependency assessment",
        "pillar": "E",
        "category": "Water",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 4 — Khoản 1",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 303-1",
        "description_en": "Disclosure of operations in water-stressed areas and dependency on shared water resources.",
        "description_vi": "Công bố hoạt động tại vùng khan hiếm nước và phụ thuộc nguồn nước chung.",
        "keywords_vi": "vùng khan hiếm nước|phụ thuộc nước|WRI Aqueduct|căng thẳng nước",
        "keywords_en": "water stress|water scarcity|dependency|shared resource|WRI Aqueduct",
    },
    {
        "indicator_id": "IND_TT08_WAT_2",
        "framework": "TT08",
        "code": "TT08-WAT-2",
        "standard": "TT08/2026",
        "title": "Wastewater treatment and discharge quality standards",
        "pillar": "E",
        "category": "Water",
        "is_quantitative": True,
        "source": "manual",
        "tt08_article": "Điều 4 — Khoản 2",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 303-4",
        "description_en": "Volume and quality of wastewater treated and discharged meeting regulatory standards.",
        "description_vi": "Khối lượng và chất lượng nước thải được xử lý và xả đáp ứng tiêu chuẩn.",
        "keywords_vi": "xử lý nước thải|chất lượng nước thải|tiêu chuẩn xả thải|QCVN",
        "keywords_en": "wastewater treatment|discharge quality|effluent standards|treatment volume",
    },
    {
        "indicator_id": "IND_TT08_WST_1",
        "framework": "TT08",
        "code": "TT08-WST-1",
        "standard": "TT08/2026",
        "title": "Hazardous waste management and disposal tracking",
        "pillar": "E",
        "category": "Waste",
        "is_quantitative": True,
        "source": "manual",
        "tt08_article": "Điều 5 — Khoản 1",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 306-4",
        "description_en": "Tracking and reporting of hazardous waste generated, stored, and disposed.",
        "description_vi": "Theo dõi và báo cáo chất thải nguy hại phát sinh, lưu trữ và xử lý.",
        "keywords_vi": "chất thải nguy hại|xử lý chất thải nguy hại|lưu trữ|mã chất thải",
        "keywords_en": "hazardous waste|disposal|tracking|storage|waste management|dangerous goods",
    },
    {
        "indicator_id": "IND_TT08_WST_2",
        "framework": "TT08",
        "code": "TT08-WST-2",
        "standard": "TT08/2026",
        "title": "Circular economy initiatives and waste diversion rate",
        "pillar": "E",
        "category": "Waste",
        "is_quantitative": True,
        "source": "manual",
        "tt08_article": "Điều 5 — Khoản 2",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 306-4",
        "description_en": "Circular economy initiatives and percentage of waste diverted from disposal.",
        "description_vi": "Sáng kiến kinh tế tuần hoàn và tỷ lệ chất thải chuyển hướng khỏi xử lý.",
        "keywords_vi": "kinh tế tuần hoàn|tái chế|tái sử dụng|tỷ lệ chuyển hướng|chất thải",
        "keywords_en": "circular economy|recycling|reuse|diversion rate|waste recovery",
    },
    {
        "indicator_id": "IND_TT08_LAB_1",
        "framework": "TT08",
        "code": "TT08-LAB-1",
        "standard": "TT08/2026",
        "title": "Supply chain labour standards and due diligence",
        "pillar": "S",
        "category": "Employment",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 6 — Khoản 1",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Due diligence processes for labour standards across the supply chain.",
        "description_vi": "Quy trình thẩm định tiêu chuẩn lao động trong chuỗi cung ứng.",
        "keywords_vi": "chuỗi cung ứng|tiêu chuẩn lao động|thẩm định|nhà cung cấp|lao động cưỡng bức",
        "keywords_en": "supply chain|labour standards|due diligence|supplier|forced labour|ILO",
    },
    {
        "indicator_id": "IND_TT08_LAB_2",
        "framework": "TT08",
        "code": "TT08-LAB-2",
        "standard": "TT08/2026",
        "title": "Employee well-being and mental health programs",
        "pillar": "S",
        "category": "Health_Safety",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 6 — Khoản 2",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 403-6",
        "description_en": "Programs for employee well-being, mental health, and work-life balance.",
        "description_vi": "Các chương trình phúc lợi nhân viên, sức khỏe tâm thần và cân bằng công việc-cuộc sống.",
        "keywords_vi": "sức khỏe nhân viên|sức khỏe tâm thần|phúc lợi|cân bằng cuộc sống|EAP",
        "keywords_en": "well-being|mental health|work-life balance|employee assistance|wellness",
    },
    {
        "indicator_id": "IND_TT08_GOV_1",
        "framework": "TT08",
        "code": "TT08-GOV-1",
        "standard": "TT08/2026",
        "title": "Board oversight of ESG risks and strategy",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 7 — Khoản 1",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 2-9",
        "description_en": "Board-level oversight structures for ESG risks and sustainability strategy.",
        "description_vi": "Cơ cấu giám sát cấp HĐQT về rủi ro ESG và chiến lược phát triển bền vững.",
        "keywords_vi": "HĐQT giám sát ESG|chiến lược bền vững|ủy ban ESG|quản trị rủi ro",
        "keywords_en": "board ESG oversight|sustainability strategy|ESG committee|risk governance",
    },
    {
        "indicator_id": "IND_TT08_GOV_2",
        "framework": "TT08",
        "code": "TT08-GOV-2",
        "standard": "TT08/2026",
        "title": "Executive ESG incentives and remuneration linkage",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 7 — Khoản 2",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Linkage of executive remuneration to ESG performance targets.",
        "description_vi": "Liên kết thù lao điều hành với mục tiêu hiệu suất ESG.",
        "keywords_vi": "thù lao ESG|KPI bền vững|lương gắn ESG|hiệu suất ESG",
        "keywords_en": "ESG remuneration|sustainability KPI|pay linked to ESG|executive incentive",
    },
    {
        "indicator_id": "IND_TT08_GOV_3",
        "framework": "TT08",
        "code": "TT08-GOV-3",
        "standard": "TT08/2026",
        "title": "Third-party ESG assurance and external verification",
        "pillar": "G",
        "category": "Transparency",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 7 — Khoản 3",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Third-party assurance or limited assurance of ESG data and sustainability reports.",
        "description_vi": "Đảm bảo bên thứ ba hoặc xác minh hạn chế về dữ liệu ESG và báo cáo bền vững.",
        "keywords_vi": "kiểm toán ESG|đảm bảo bên thứ ba|xác minh độc lập|assurance",
        "keywords_en": "ESG assurance|third-party verification|independent audit|limited assurance",
    },
    {
        "indicator_id": "IND_TT08_GOV_4",
        "framework": "TT08",
        "code": "TT08-GOV-4",
        "standard": "TT08/2026",
        "title": "Sustainability report publication timeline and format compliance",
        "pillar": "G",
        "category": "Transparency",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 7 — Khoản 4",
        "mandatory_for": ["REG_TT08_2026"],
        "description_en": "Compliance with TT08 timelines and format requirements for sustainability report publication.",
        "description_vi": "Tuân thủ thời hạn và yêu cầu định dạng TT08 cho việc công bố báo cáo bền vững.",
        "keywords_vi": "báo cáo bền vững|thời hạn công bố|định dạng GRI|tuân thủ TT08",
        "keywords_en": "sustainability report|publication deadline|GRI format|TT08 compliance",
    },
    {
        "indicator_id": "IND_TT08_GOV_5",
        "framework": "TT08",
        "code": "TT08-GOV-5",
        "standard": "TT08/2026",
        "title": "Whistleblower protection mechanisms",
        "pillar": "G",
        "category": "Anti_corruption",
        "is_quantitative": False,
        "source": "manual",
        "tt08_article": "Điều 7 — Khoản 5",
        "mandatory_for": ["REG_TT08_2026"],
        "gri_code": "GRI 2-26",
        "description_en": "Mechanisms for employees and stakeholders to raise concerns without retaliation.",
        "description_vi": "Cơ chế để nhân viên và các bên liên quan báo cáo lo ngại mà không bị trả thù.",
        "keywords_vi": "tố giác|bảo vệ người tố cáo|kênh phản ánh|không trả thù",
        "keywords_en": "whistleblower|protection|speak-up|reporting channel|retaliation",
    },
]

MANUAL_TCFD_INDICATORS = [
    {
        "indicator_id": "IND_TCFD_GOV_A",
        "framework": "TCFD",
        "code": "TCFD-GOV-A",
        "standard": "TCFD 2023",
        "title": "Board's oversight of climate-related risks and opportunities",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Board-level processes, controls, and procedures for overseeing climate-related risks and opportunities.",
        "description_vi": "Quy trình, kiểm soát và thủ tục cấp HĐQT để giám sát rủi ro và cơ hội liên quan khí hậu.",
        "keywords_vi": "HĐQT khí hậu|giám sát rủi ro khí hậu|quản trị TCFD|ủy ban khí hậu",
        "keywords_en": "board climate oversight|climate risk governance|TCFD governance|board committee",
        "gri_code": "GRI 2-9",
    },
    {
        "indicator_id": "IND_TCFD_GOV_B",
        "framework": "TCFD",
        "code": "TCFD-GOV-B",
        "standard": "TCFD 2023",
        "title": "Management's role in assessing and managing climate-related risks",
        "pillar": "G",
        "category": "Board_Governance",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Management's role and responsibilities in assessing, identifying, and managing climate risks.",
        "description_vi": "Vai trò và trách nhiệm của ban quản lý trong đánh giá, xác định và quản lý rủi ro khí hậu.",
        "keywords_vi": "ban quản lý khí hậu|quản lý rủi ro khí hậu|phân công trách nhiệm",
        "keywords_en": "management climate role|climate risk management|responsibility assignment|C-suite",
    },
    {
        "indicator_id": "IND_TCFD_STR_A",
        "framework": "TCFD",
        "code": "TCFD-STR-A",
        "standard": "TCFD 2023",
        "title": "Climate-related risks and opportunities over short, medium, long term",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Climate-related risks and opportunities identified over short, medium, and long-term time horizons.",
        "description_vi": "Rủi ro và cơ hội liên quan khí hậu được xác định trong ngắn hạn, trung hạn và dài hạn.",
        "keywords_vi": "rủi ro khí hậu|cơ hội khí hậu|ngắn hạn|dài hạn|chiến lược khí hậu",
        "keywords_en": "climate risk|climate opportunity|time horizon|short-term|long-term|strategy",
    },
    {
        "indicator_id": "IND_TCFD_STR_B",
        "framework": "TCFD",
        "code": "TCFD-STR-B",
        "standard": "TCFD 2023",
        "title": "Impact of climate-related risks and opportunities on business strategy",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Impact of climate-related risks and opportunities on the organization's businesses, strategy, and financial planning.",
        "description_vi": "Tác động của rủi ro và cơ hội khí hậu lên kinh doanh, chiến lược và kế hoạch tài chính.",
        "keywords_vi": "tác động khí hậu|chiến lược kinh doanh|kế hoạch tài chính|kịch bản",
        "keywords_en": "climate impact|business strategy|financial planning|scenario",
    },
    {
        "indicator_id": "IND_TCFD_STR_C",
        "framework": "TCFD",
        "code": "TCFD-STR-C",
        "standard": "TCFD 2023",
        "title": "Resilience of strategy under different climate scenarios including 2°C",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Resilience of the organization's strategy under different climate-related scenarios, including a 2°C or lower scenario.",
        "description_vi": "Khả năng chịu đựng của chiến lược theo các kịch bản khí hậu khác nhau, bao gồm 2°C.",
        "keywords_vi": "khả năng chịu đựng|kịch bản 2 độ|phân tích kịch bản|chiến lược bền vững",
        "keywords_en": "resilience|2°C scenario|scenario analysis|strategy stress test|climate resilience",
    },
    {
        "indicator_id": "IND_TCFD_RSK_A",
        "framework": "TCFD",
        "code": "TCFD-RSK-A",
        "standard": "TCFD 2023",
        "title": "Processes for identifying and assessing climate-related risks",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Processes for identifying and assessing climate-related risks across the organization.",
        "description_vi": "Quy trình xác định và đánh giá rủi ro khí hậu trong toàn tổ chức.",
        "keywords_vi": "quy trình rủi ro khí hậu|xác định rủi ro|đánh giá rủi ro|TCFD",
        "keywords_en": "climate risk identification|risk assessment process|climate risk process",
    },
    {
        "indicator_id": "IND_TCFD_RSK_B",
        "framework": "TCFD",
        "code": "TCFD-RSK-B",
        "standard": "TCFD 2023",
        "title": "Processes for managing climate-related risks",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "Processes used by the organization to manage climate-related risks.",
        "description_vi": "Quy trình tổ chức sử dụng để quản lý rủi ro khí hậu.",
        "keywords_vi": "quản lý rủi ro khí hậu|giảm thiểu rủi ro|thích ứng khí hậu",
        "keywords_en": "climate risk management|mitigation|adaptation|risk response",
    },
    {
        "indicator_id": "IND_TCFD_RSK_C",
        "framework": "TCFD",
        "code": "TCFD-RSK-C",
        "standard": "TCFD 2023",
        "title": "Integration of climate risk into overall enterprise risk management",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": False,
        "source": "manual",
        "description_en": "How climate risk identification, assessment, and management processes are integrated into overall risk management.",
        "description_vi": "Tích hợp quy trình xác định, đánh giá và quản lý rủi ro khí hậu vào quản lý rủi ro tổng thể.",
        "keywords_vi": "tích hợp rủi ro khí hậu|ERM|quản lý rủi ro doanh nghiệp",
        "keywords_en": "climate risk integration|enterprise risk management|ERM|overall risk",
    },
    {
        "indicator_id": "IND_TCFD_MET_A",
        "framework": "TCFD",
        "code": "TCFD-MET-A",
        "standard": "TCFD 2023",
        "title": "Metrics used to assess climate-related risks and opportunities",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": True,
        "source": "manual",
        "description_en": "Metrics used by the organization to assess climate-related risks and opportunities in line with its strategy and risk management process.",
        "description_vi": "Các chỉ số tổ chức sử dụng để đánh giá rủi ro và cơ hội khí hậu.",
        "keywords_vi": "chỉ số khí hậu|KPI khí hậu|đo lường rủi ro khí hậu",
        "keywords_en": "climate metrics|KPI|climate risk measurement|carbon metric|climate KPI",
    },
    {
        "indicator_id": "IND_TCFD_MET_B",
        "framework": "TCFD",
        "code": "TCFD-MET-B",
        "standard": "TCFD 2023",
        "title": "Scope 1, 2, and 3 greenhouse gas emissions",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": True,
        "source": "manual",
        "unit": "metric ton CO2e",
        "description_en": "Scope 1, Scope 2, and if appropriate, Scope 3 GHG emissions and related risks.",
        "description_vi": "Phát thải KNK Phạm vi 1, 2 và (nếu phù hợp) Phạm vi 3 và rủi ro liên quan.",
        "keywords_vi": "phạm vi 1|phạm vi 2|phạm vi 3|tổng phát thải|GHG TCFD",
        "keywords_en": "scope 1|scope 2|scope 3|GHG emissions|TCFD emissions|tCO2e",
        "gri_code": "GRI 305-1",
    },
    {
        "indicator_id": "IND_TCFD_MET_C",
        "framework": "TCFD",
        "code": "TCFD-MET-C",
        "standard": "TCFD 2023",
        "title": "GHG emissions reduction targets and performance",
        "pillar": "E",
        "category": "Emissions",
        "is_quantitative": True,
        "source": "manual",
        "description_en": "Targets used by the organization to manage climate-related risks and opportunities and performance against targets.",
        "description_vi": "Mục tiêu giảm phát thải và hiệu suất so với mục tiêu.",
        "keywords_vi": "mục tiêu giảm phát thải|hiệu suất khí hậu|KPI carbon|tiến độ net-zero",
        "keywords_en": "emission reduction target|climate target|carbon KPI|net-zero progress|science-based target",
        "gri_code": "GRI 305-5",
    },
]

# GRI indicators not in the available PDFs (GRI 2, 205, 401, 403, 405)
# These are retained manually with source="manual" for completeness.
MANUAL_EXTRA_GRI_INDICATORS = [
    {
        "indicator_id": "IND_GRI_401_1", "framework": "GRI", "code": "401-1", "standard": "GRI 401",
        "title": "New employee hires and employee turnover", "pillar": "S", "category": "Employment",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 401-1",
        "description_en": "Total number and rate of new employee hires and turnover by age group, gender, and region.",
        "keywords_en": "new hires|employee turnover|attrition|retention|workforce|hiring rate",
        "keywords_vi": "nhân viên mới|tỷ lệ thôi việc|nghỉ việc|giữ chân nhân viên|tuyển dụng",
    },
    {
        "indicator_id": "IND_GRI_401_2", "framework": "GRI", "code": "401-2", "standard": "GRI 401",
        "title": "Benefits provided to full-time employees", "pillar": "S", "category": "Employment",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 401-2",
        "description_en": "Benefits provided to full-time employees that are not provided to temporary or part-time employees.",
        "keywords_en": "employee benefits|health insurance|pension|parental leave|full-time benefits",
        "keywords_vi": "phúc lợi nhân viên|bảo hiểm y tế|lương hưu|nghỉ thai sản",
    },
    {
        "indicator_id": "IND_GRI_401_3", "framework": "GRI", "code": "401-3", "standard": "GRI 401",
        "title": "Parental leave", "pillar": "S", "category": "Employment",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 401-3",
        "description_en": "Total number of employees entitled to parental leave by gender, and return-to-work rates.",
        "keywords_en": "parental leave|maternity|paternity|return to work|family leave",
        "keywords_vi": "nghỉ thai sản|nghỉ thai sản nam|trở lại làm việc|nghỉ phép gia đình",
    },
    {
        "indicator_id": "IND_GRI_403_1", "framework": "GRI", "code": "403-1", "standard": "GRI 403",
        "title": "Occupational health and safety management system", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 403-1",
        "description_en": "OHS management system scope and whether third-party audited.",
        "keywords_en": "OHS management system|ISO 45001|safety system|occupational health",
        "keywords_vi": "hệ thống quản lý an toàn|ISO 45001|OHSMS|kiểm toán bên thứ ba",
    },
    {
        "indicator_id": "IND_GRI_403_2", "framework": "GRI", "code": "403-2", "standard": "GRI 403",
        "title": "Hazard identification, risk assessment, and incident investigation", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 403-2",
        "description_en": "Processes for identifying hazards, assessing risks, and investigating work-related incidents.",
        "keywords_en": "hazard identification|risk assessment|incident investigation|safety process",
        "keywords_vi": "nhận diện mối nguy|đánh giá rủi ro|điều tra sự cố|quy trình an toàn",
    },
    {
        "indicator_id": "IND_GRI_403_3", "framework": "GRI", "code": "403-3", "standard": "GRI 403",
        "title": "Occupational health services", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 403-3",
        "description_en": "Occupational health services offered to workers.",
        "keywords_en": "occupational health services|medical surveillance|health program|worker health",
        "keywords_vi": "dịch vụ y tế lao động|khám sức khỏe|chương trình y tế",
    },
    {
        "indicator_id": "IND_GRI_403_4", "framework": "GRI", "code": "403-4", "standard": "GRI 403",
        "title": "Worker participation, consultation, and communication on OHS", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 403-4",
        "description_en": "Worker participation and consultation processes on OHS.",
        "keywords_en": "worker participation|OHS consultation|safety committee|worker voice",
        "keywords_vi": "tham gia người lao động|tham vấn an toàn|ủy ban an toàn",
    },
    {
        "indicator_id": "IND_GRI_403_5", "framework": "GRI", "code": "403-5", "standard": "GRI 403",
        "title": "Worker training on occupational health and safety", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 403-5",
        "description_en": "OHS training provided to workers including hours and topics.",
        "keywords_en": "safety training|OHS training|training hours|worker education",
        "keywords_vi": "đào tạo an toàn|giờ đào tạo ATLD|huấn luyện an toàn",
    },
    {
        "indicator_id": "IND_GRI_403_6", "framework": "GRI", "code": "403-6", "standard": "GRI 403",
        "title": "Promotion of worker health", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 403-6",
        "description_en": "Programs for promoting worker health beyond OHS requirements.",
        "keywords_en": "worker health promotion|wellness program|health initiative|EAP",
        "keywords_vi": "thúc đẩy sức khỏe|chương trình sức khỏe|EAP|phúc lợi sức khỏe",
    },
    {
        "indicator_id": "IND_GRI_403_7", "framework": "GRI", "code": "403-7", "standard": "GRI 403",
        "title": "Prevention and mitigation of OHS impacts directly linked to business relationships", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 403-7",
        "description_en": "Prevention and mitigation of OHS impacts linked to suppliers and contractors.",
        "keywords_en": "supplier OHS|contractor safety|value chain OHS|business relationship safety",
        "keywords_vi": "an toàn nhà cung cấp|an toàn nhà thầu|OHS chuỗi cung ứng",
    },
    {
        "indicator_id": "IND_GRI_403_8", "framework": "GRI", "code": "403-8", "standard": "GRI 403",
        "title": "Workers covered by an occupational health and safety management system", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 403-8",
        "description_en": "Number and percentage of workers covered by an OHS management system.",
        "keywords_en": "OHS coverage|workers covered|safety system coverage|ISO 45001 coverage",
        "keywords_vi": "tỷ lệ bao phủ OHSMS|người lao động được bảo vệ",
    },
    {
        "indicator_id": "IND_GRI_403_9", "framework": "GRI", "code": "403-9", "standard": "GRI 403",
        "title": "Work-related injuries", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 403-9",
        "description_en": "Number and rate of work-related injuries, including fatalities.",
        "keywords_en": "work injury|fatality|injury rate|LTIFR|accident|recordable incident",
        "keywords_vi": "tai nạn lao động|tỷ lệ tai nạn|tử vong|LTIFR|sự cố có ghi nhận",
    },
    {
        "indicator_id": "IND_GRI_403_10", "framework": "GRI", "code": "403-10", "standard": "GRI 403",
        "title": "Work-related ill health", "pillar": "S", "category": "Health_Safety",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 403-10",
        "description_en": "Number and rate of work-related ill health cases.",
        "keywords_en": "occupational disease|ill health|work illness|occupational health rate",
        "keywords_vi": "bệnh nghề nghiệp|tỷ lệ bệnh|sức khỏe nghề nghiệp",
    },
    {
        "indicator_id": "IND_GRI_405_1", "framework": "GRI", "code": "405-1", "standard": "GRI 405",
        "title": "Diversity of governance bodies and employees", "pillar": "S", "category": "Employment",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 405-1",
        "description_en": "Percentage of individuals within governance bodies and employees by gender, age group, and other diversity indicators.",
        "keywords_en": "diversity|gender|age|governance body diversity|employee diversity",
        "keywords_vi": "đa dạng|giới tính|độ tuổi|đa dạng HĐQT|đa dạng nhân viên",
    },
    {
        "indicator_id": "IND_GRI_405_2", "framework": "GRI", "code": "405-2", "standard": "GRI 405",
        "title": "Ratio of basic salary and remuneration of women to men", "pillar": "S", "category": "Employment",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 405-2",
        "description_en": "Ratio of basic salary and remuneration of women to men by employee category.",
        "keywords_en": "gender pay gap|salary ratio|women salary|pay equity|equal pay",
        "keywords_vi": "khoảng cách lương giới tính|tỷ lệ lương nữ/nam|bình đẳng lương",
    },
    {
        "indicator_id": "IND_GRI_205_1", "framework": "GRI", "code": "205-1", "standard": "GRI 205",
        "title": "Operations assessed for risks related to corruption", "pillar": "G", "category": "Anti_corruption",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 205-1",
        "description_en": "Total number and percentage of operations assessed for corruption-related risks.",
        "keywords_en": "corruption risk|operations assessed|anti-corruption|risk assessment",
        "keywords_vi": "rủi ro tham nhũng|đánh giá hoạt động|chống tham nhũng",
    },
    {
        "indicator_id": "IND_GRI_205_2", "framework": "GRI", "code": "205-2", "standard": "GRI 205",
        "title": "Communication and training about anti-corruption policies and procedures", "pillar": "G", "category": "Anti_corruption",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 205-2",
        "description_en": "Total number of governance body members, employees, and business partners communicated and trained on anti-corruption policies.",
        "keywords_en": "anti-corruption training|policy communication|compliance training|code of conduct",
        "keywords_vi": "đào tạo chống tham nhũng|truyền thông chính sách|đào tạo tuân thủ",
    },
    {
        "indicator_id": "IND_GRI_205_3", "framework": "GRI", "code": "205-3", "standard": "GRI 205",
        "title": "Confirmed incidents of corruption and actions taken", "pillar": "G", "category": "Anti_corruption",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 205-3",
        "description_en": "Total number and nature of confirmed incidents of corruption and actions taken.",
        "keywords_en": "corruption incident|confirmed corruption|disciplinary action|legal case|bribery",
        "keywords_vi": "sự cố tham nhũng|vi phạm xác nhận|xử lý kỷ luật|vụ kiện",
    },
    {
        "indicator_id": "IND_GRI_2_9", "framework": "GRI", "code": "2-9", "standard": "GRI 2",
        "title": "Governance structure and composition", "pillar": "G", "category": "Board_Governance",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 2-9",
        "description_en": "Governance structure, composition of the highest governance body including skills, tenure, independence, and diversity.",
        "keywords_en": "governance structure|board composition|independence|skills matrix|board diversity",
        "keywords_vi": "cơ cấu quản trị|thành phần HĐQT|tính độc lập|kỹ năng HĐQT|đa dạng HĐQT",
    },
    {
        "indicator_id": "IND_GRI_2_10", "framework": "GRI", "code": "2-10", "standard": "GRI 2",
        "title": "Nomination and selection of the highest governance body", "pillar": "G", "category": "Board_Governance",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 2-10",
        "description_en": "Nomination and selection criteria for governance body members.",
        "keywords_en": "board nomination|director selection|governance criteria|board appointment",
        "keywords_vi": "đề cử HĐQT|lựa chọn thành viên|tiêu chí bổ nhiệm",
    },
    {
        "indicator_id": "IND_GRI_2_26", "framework": "GRI", "code": "2-26", "standard": "GRI 2",
        "title": "Mechanisms for seeking advice and raising concerns", "pillar": "G", "category": "Transparency",
        "is_quantitative": False, "source": "manual", "gri_code": "GRI 2-26",
        "description_en": "Mechanisms for workers and other stakeholders to seek advice on ethical behavior and raise concerns.",
        "keywords_en": "ethics helpline|concern reporting|advice mechanism|grievance|whistleblower",
        "keywords_vi": "đường dây tư vấn đạo đức|báo cáo lo ngại|cơ chế khiếu nại|tố giác",
    },
    {
        "indicator_id": "IND_GRI_2_27", "framework": "GRI", "code": "2-27", "standard": "GRI 2",
        "title": "Compliance with laws and regulations", "pillar": "G", "category": "Transparency",
        "is_quantitative": True, "source": "manual", "gri_code": "GRI 2-27",
        "description_en": "Instances of non-compliance with laws and regulations and monetary fines.",
        "keywords_en": "legal compliance|non-compliance|fines|regulatory violation|penalties",
        "keywords_vi": "tuân thủ pháp luật|vi phạm|phạt tiền|vi phạm quy định",
    },
]

# ---------------------------------------------------------------------------
# Cross-framework maps (unchanged — based on domain knowledge)
# ---------------------------------------------------------------------------
CROSS_FRAMEWORK_MAPS = [
    {"from": "IND_TT96_ENV_1", "to": "IND_GRI_302_1"},
    {"from": "IND_TT96_ENV_2", "to": "IND_GRI_305_1"},
    {"from": "IND_TT96_ENV_2", "to": "IND_GRI_305_2"},
    {"from": "IND_TT96_ENV_3", "to": "IND_GRI_306_3"},
    {"from": "IND_TT96_ENV_4", "to": "IND_GRI_303_3"},
    {"from": "IND_TT96_SOC_1", "to": "IND_GRI_401_1"},
    {"from": "IND_TT96_SOC_3", "to": "IND_GRI_403_9"},
    {"from": "IND_TT96_SOC_4", "to": "IND_GRI_401_2"},
    {"from": "IND_TT96_SOC_5", "to": "IND_GRI_405_1"},
    {"from": "IND_TT96_GOV_1", "to": "IND_GRI_2_9"},
    {"from": "IND_TT96_GOV_2", "to": "IND_GRI_205_2"},
    {"from": "IND_TT08_CLI_4", "to": "IND_GRI_305_5"},
    {"from": "IND_TT08_WAT_1", "to": "IND_GRI_303_1"},
    {"from": "IND_TT08_WAT_2", "to": "IND_GRI_303_4"},
    {"from": "IND_TT08_WST_1", "to": "IND_GRI_306_4"},
    {"from": "IND_TT08_WST_2", "to": "IND_GRI_306_4"},
    {"from": "IND_TT08_LAB_2", "to": "IND_GRI_403_6"},
    {"from": "IND_TT08_GOV_1", "to": "IND_GRI_2_9"},
    {"from": "IND_TT08_GOV_5", "to": "IND_GRI_2_26"},
    {"from": "IND_TCFD_MET_B", "to": "IND_GRI_305_1"},
    {"from": "IND_TCFD_MET_B", "to": "IND_GRI_305_2"},
    {"from": "IND_TCFD_MET_B", "to": "IND_GRI_305_3"},
    {"from": "IND_TCFD_MET_C", "to": "IND_GRI_305_5"},
    {"from": "IND_TCFD_GOV_A", "to": "IND_GRI_2_9"},
    {"from": "IND_TCFD_STR_C", "to": "IND_TT08_CLI_3"},
]

# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_framework_indicators() -> dict:
    print("Building framework_indicators.json from PDFs + manual data...\n")

    all_indicators = []

    # 1. Extract from GRI PDFs
    print("=== Extracting from GRI PDFs ===")
    for standard, pdf_path in GRI_PDFS.items():
        if not pdf_path.exists():
            print(f"  WARNING: {pdf_path} not found — skipping {standard}")
            continue
        indicators = parse_gri_pdf(standard, pdf_path)
        all_indicators.extend(indicators)

    print(f"\n  GRI PDF extraction complete: {len(all_indicators)} indicators\n")

    # 2. Add manual extra GRI (not in available PDFs)
    print("=== Adding manual GRI indicators (GRI 2, 205, 401, 403, 405) ===")
    for ind in MANUAL_EXTRA_GRI_INDICATORS:
        all_indicators.append(ind)
        print(f"  + {ind['indicator_id']}  [{ind['code']}] {ind['title'][:60]}")

    # 3. Add TT96
    print(f"\n=== Adding manual TT96 indicators ===")
    for ind in MANUAL_TT96_INDICATORS:
        all_indicators.append(ind)
        print(f"  + {ind['indicator_id']}  [{ind['code']}] {ind['title'][:60]}")

    # 4. Add TT08
    print(f"\n=== Adding manual TT08 indicators ===")
    for ind in MANUAL_TT08_INDICATORS:
        all_indicators.append(ind)
        print(f"  + {ind['indicator_id']}  [{ind['code']}] {ind['title'][:60]}")

    # 5. Add TCFD
    print(f"\n=== Adding manual TCFD indicators ===")
    for ind in MANUAL_TCFD_INDICATORS:
        all_indicators.append(ind)
        print(f"  + {ind['indicator_id']}  [{ind['code']}] {ind['title'][:60]}")

    # -------------------------------------------------------------------------
    # Post-processing: apply fixes and enrich all indicators uniformly
    # -------------------------------------------------------------------------
    for ind in all_indicators:
        code = ind.get("code", "")

        # mandatory_for: convert string → list (safety net; source dicts now use lists)
        mf = ind.get("mandatory_for")
        if isinstance(mf, str):
            if mf:
                ind["mandatory_for"] = [r.strip() for r in mf.split(",") if r.strip()]
            else:
                del ind["mandatory_for"]

        # Apply MANDATORY_FOR to indicators that are missing the field (e.g. MANUAL_EXTRA_GRI)
        if "mandatory_for" not in ind and code in MANDATORY_FOR:
            ind["mandatory_for"] = MANDATORY_FOR[code]

        # Remove redundant gri_code from GRI indicators (duplicates the code field)
        if ind.get("framework") == "GRI" and "gri_code" in ind:
            del ind["gri_code"]

        # Add extraction_hint for LLM-based claim extraction
        if "extraction_hint" not in ind:
            hint = EXTRACTION_HINTS.get(code)
            if hint is None:
                is_quant = ind.get("is_quantitative", False)
                unit = ind.get("unit", "")
                if is_quant and unit:
                    hint = (
                        f"Extract the specific numerical value in {unit} for the reporting year. "
                        "A valid reported disclosure contains actual measured data. "
                        "Aspirational statements without data are NOT valid quantitative disclosures."
                    )
                elif is_quant:
                    hint = (
                        "Extract the specific numerical value (count, percentage, or ratio) for "
                        "the reporting year. A valid disclosure reports actual measured data. "
                        "Goals or targets without current-year data are NOT valid reported disclosures."
                    )
                else:
                    hint = (
                        "Look for a description of policies, systems, or practices in place. "
                        "A valid disclosure describes actual implemented measures and outcomes, "
                        "not just commitments or intentions."
                    )
            ind["extraction_hint"] = hint

        # Add valid_claim_types for LLM claim classification
        if "valid_claim_types" not in ind:
            vct = VALID_CLAIM_TYPES.get(code)
            if vct is None:
                if ind.get("is_quantitative", False):
                    vct = ["reported", "committed"]
                else:
                    vct = ["reported", "qualitative", "aspirational"]
            ind["valid_claim_types"] = vct

    # Summary by framework and source
    by_framework: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for ind in all_indicators:
        by_framework[ind["framework"]] = by_framework.get(ind["framework"], 0) + 1
        src = ind.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    print(f"\n=== Summary ===")
    print(f"  Total indicators: {len(all_indicators)}")
    for fw, cnt in sorted(by_framework.items()):
        print(f"    {fw}: {cnt}")
    print(f"  By source:")
    for src, cnt in sorted(by_source.items()):
        print(f"    {src}: {cnt}")

    output = {
        "_meta": {
            "version": "2.1.0",
            "generated": datetime.now().strftime("%Y-%m-%d"),
            "description": (
                "ESG framework indicator catalog for the Vietnamese corporate ESG greenwashing detection pipeline. "
                "GRI 302/303/305/306 indicators extracted from official GRI PDFs using pdfplumber. "
                "TT96, TT08, TCFD, and GRI 2/205/401/403/405 indicators are manually maintained "
                "(source='manual') because source PDFs are unavailable. "
                "source='pdf_extracted' indicates data grounded directly in an official PDF. "
                "Each indicator carries extraction_hint (LLM guidance on valid disclosures) and "
                "valid_claim_types (list of acceptable claim classifications: reported/committed/"
                "aspirational/qualitative)."
            ),
            "total_indicators": len(all_indicators),
            "frameworks": sorted(by_framework.keys()),
            "by_framework": by_framework,
            "by_source": by_source,
            "category_values": [
                "Emissions", "Energy", "Water", "Waste",
                "Employment", "Health_Safety",
                "Board_Governance", "Anti_corruption", "Transparency",
            ],
            "pillar_values": ["E", "S", "G"],
            "notes": (
                "GRI indicators sourced from: GRI 302 Energy 2016, GRI 303 Water and Effluents 2018, "
                "GRI 305 Emissions 2016, GRI 306 Effluents and Waste 2016. "
                "TT96 indicators derived from Phụ lục IV (Annual Report) and Phụ lục V "
                "(Corporate Governance Report) appendices — appendix PDFs not available separately. "
                "TT08 indicators based on draft/published standard text. "
                "TCFD indicators are the 11 official recommended disclosures (FSB 2023)."
            ),
        },
        "cross_framework_maps": CROSS_FRAMEWORK_MAPS,
        "indicators": all_indicators,
    }
    return output


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    output = build_framework_indicators()

    out_path = ONTOLOGY_DIR / "framework_indicators.json"
    ONTOLOGY_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {out_path}")

    # Also bump the generated date in ontology_schema.json
    schema_path = ONTOLOGY_DIR / "ontology_schema.json"
    if schema_path.exists():
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        schema["_meta"]["generated"] = datetime.now().strftime("%Y-%m-%d")
        schema["_meta"]["version"] = "2.0.0"
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        print(f"Updated {schema_path} (version + generated date)")


if __name__ == "__main__":
    main()
