#!/usr/bin/env python3
"""
Stage 6 - Make the dataset extraction-ready, matching EmeraldMind/kpi_definitions.json
style (short `name` label + a measurable `definition` with unit/normalisation hints).

Why: the regulations state *topics to disclose*; the EFFAS-style original states
*metrics to measure*. Stages 2/4 extract verbatim (good provenance) but several
rows are too thin to drive numeric extraction (e.g. "Tái chế"). Here we attach a
curated, source-anchored metric definition to every KPI, while preserving the
verbatim source text in `source.excerpt` for audit.

Idempotent: re-running re-applies the map; the original verbatim is captured into
`source.excerpt` on first run and never overwritten.

Input/Output: ../kpi_definitions_construction.json (rewritten in place)

Run:
    python 06_enrich_kpis.py
"""

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "kpi_definitions_construction.json"

# id -> (short name label, measurable definition with unit/normalisation hints).
# Definitions are grounded in the source indicator/aspect; units reflect common
# ESG reporting practice (tCO2e, m3, kWh, %, VND, giờ/người, số vụ ...).
ENRICH = {
    # ---- Circular 96/2020 - Section 6 (Moi truong) ----
    "TT96-6.1.1": ("Tổng phát thải khí nhà kính (Scope 1 + Scope 2)",
                   "Tổng lượng phát thải khí nhà kính trực tiếp (Scope 1) và gián tiếp (Scope 2) trong kỳ báo cáo, quy đổi tấn CO2 tương đương (tCO2e)."),
    "TT96-6.1.2": ("Mức giảm phát thải khí nhà kính từ các sáng kiến",
                   "Lượng phát thải khí nhà kính giảm được nhờ các sáng kiến, biện pháp giảm thiểu trong kỳ, tính bằng tấn CO2 tương đương (tCO2e) hoặc phần trăm (%) so với kỳ gốc."),
    "TT96-6.2.1": ("Tổng lượng nguyên vật liệu sử dụng",
                   "Tổng khối lượng nguyên vật liệu sử dụng để sản xuất và đóng gói sản phẩm, dịch vụ chính trong năm (tấn hoặc m3)."),
    "TT96-6.2.2": ("Tỷ lệ nguyên vật liệu tái chế",
                   "Tỷ lệ phần trăm (%) nguyên vật liệu tái chế trên tổng nguyên vật liệu đầu vào dùng để sản xuất sản phẩm, dịch vụ chính."),
    "TT96-6.3.1": ("Tiêu thụ năng lượng trực tiếp và gián tiếp",
                   "Tổng năng lượng tiêu thụ trực tiếp (nhiên liệu) và gián tiếp (điện, nhiệt, hơi mua ngoài) trong kỳ (kWh, GJ hoặc TOE)."),
    "TT96-6.3.2": ("Năng lượng tiết kiệm được",
                   "Lượng năng lượng tiết kiệm được nhờ các sáng kiến sử dụng năng lượng hiệu quả trong kỳ (kWh, GJ hoặc % so với kỳ gốc)."),
    "TT96-6.3.3": ("Kết quả sáng kiến tiết kiệm năng lượng / năng lượng tái tạo",
                   "Kết quả định lượng của các sáng kiến tiết kiệm năng lượng hoặc sử dụng năng lượng tái tạo (ví dụ lượng năng lượng tái tạo sử dụng, kWh; hoặc tỷ lệ % trên tổng năng lượng)."),
    "TT96-6.4.1": ("Tổng lượng nước sử dụng",
                   "Tổng lượng nước sử dụng theo nguồn cung cấp trong kỳ (m3)."),
    "TT96-6.4.2": ("Tỷ lệ nước tái chế, tái sử dụng",
                   "Tỷ lệ phần trăm (%) và tổng lượng (m3) nước tái chế, tái sử dụng trên tổng lượng nước sử dụng."),
    "TT96-6.5.1": ("Số lần bị xử phạt vi phạm môi trường",
                   "Số lần bị xử phạt do không tuân thủ pháp luật, quy định về bảo vệ môi trường trong kỳ (số lần)."),
    "TT96-6.5.2": ("Tổng tiền phạt vi phạm môi trường",
                   "Tổng số tiền bị xử phạt do không tuân thủ pháp luật, quy định về môi trường trong kỳ (VND)."),
    # ---- Circular 96/2020 - Section 6 (Xa hoi) ----
    "TT96-6.6.1": ("Số lượng lao động và mức lương trung bình",
                   "Tổng số lao động (người) và mức lương/thu nhập trung bình của người lao động trong kỳ (VND/người/tháng)."),
    "TT96-6.6.2": ("Tỷ lệ lao động được bảo đảm an toàn, sức khỏe, phúc lợi",
                   "Mức độ thực hiện chính sách an toàn - sức khỏe - phúc lợi, ví dụ tỷ lệ phần trăm (%) lao động được đóng bảo hiểm hoặc khám sức khỏe định kỳ."),
    "TT96-6.6.3": ("Tỷ lệ lao động được đào tạo",
                   "Tỷ lệ phần trăm (%) lao động được tham gia đào tạo trong kỳ báo cáo."),
    "TT96-6.6.4": ("Số giờ đào tạo trung bình mỗi lao động",
                   "Số giờ đào tạo trung bình mỗi năm trên một lao động (giờ/người), có thể phân theo nhóm nhân viên."),
    "TT96-6.6.5": ("Số chương trình, lượt phát triển kỹ năng",
                   "Số chương trình hoặc số lượt người lao động tham gia phát triển kỹ năng, học tập liên tục trong kỳ (số chương trình hoặc số lượt)."),
    "TT96-6.7.1": ("Số chương trình, hoạt động vì cộng đồng",
                   "Số lượng chương trình, hoạt động đầu tư và phát triển cộng đồng địa phương thực hiện trong kỳ (số chương trình)."),
    "TT96-6.7.2": ("Giá trị đầu tư, đóng góp cho cộng đồng",
                   "Tổng giá trị đầu tư, đóng góp và hỗ trợ tài chính cho cộng đồng địa phương trong kỳ (VND)."),
    # ---- Circular 96/2020 - Section 6 (Quan tri) ----
    "TT96-6.8.1": ("Huy động vốn xanh",
                   "Giá trị vốn huy động qua thị trường vốn xanh (trái phiếu xanh, tín dụng xanh) theo hướng dẫn của UBCKNN trong kỳ (VND)."),
    # ---- Sector-specific ----
    "QD2171-1": ("Tỷ lệ sử dụng vật liệu xây không nung (VLXKN)",
                 "Tỷ lệ phần trăm (%) vật liệu xây không nung trên tổng vật liệu xây sử dụng (mục tiêu quốc gia 35-40% năm 2025, 40-45% năm 2030 theo QĐ 2171/QĐ-TTg)."),
    "QCVN09-1": ("Tỷ lệ công trình tuân thủ QCVN 09:2017/BXD",
                 "Tỷ lệ phần trăm (%) hoặc diện tích sàn (m2) công trình từ 2500 m2 trở lên tuân thủ quy chuẩn sử dụng năng lượng hiệu quả QCVN 09:2017/BXD (vỏ bao che, thông gió - điều hòa, chiếu sáng, thiết bị điện)."),
    "SSCIFC-E1": ("Tiết kiệm năng lượng",
                  "Lượng năng lượng tiết kiệm được trong kỳ (kWh, GJ hoặc % so với kỳ gốc)."),
    "SSCIFC-E2": ("Phát thải khí nhà kính (GHG)",
                  "Tổng phát thải khí nhà kính trong kỳ, quy đổi tấn CO2 tương đương (tCO2e), gồm Scope 1 và Scope 2."),
    "SSCIFC-E3": ("Bảo tồn đa dạng sinh học",
                  "Mức độ bảo tồn đa dạng sinh học, ví dụ diện tích đất được phục hồi/bảo tồn (ha) hoặc số dự án bảo tồn trong kỳ."),
    "SSCIFC-E4": ("Sử dụng nước",
                  "Tổng lượng nước khai thác và sử dụng trong kỳ (m3)."),
    "SSCIFC-E5": ("Sử dụng tài nguyên thiên nhiên",
                  "Khối lượng tài nguyên thiên nhiên khai thác/sử dụng trong kỳ (tấn hoặc m3)."),
    "SSCIFC-E6": ("Biến rác thải thành năng lượng",
                  "Khối lượng chất thải được chuyển hóa thành năng lượng (tấn) hoặc năng lượng thu hồi từ chất thải (kWh, GJ)."),
    "SSCIFC-E7": ("Tỷ lệ tái chế chất thải",
                  "Tỷ lệ phần trăm (%) hoặc khối lượng (tấn) chất thải, vật liệu được tái chế trên tổng khối lượng phát sinh."),
    "SSCIFC-S1": ("Chế độ lương thưởng cho nhân viên",
                  "Mức lương, thưởng trung bình cho người lao động (VND/người/tháng hoặc /năm)."),
    "SSCIFC-S2": ("Chế độ phúc lợi",
                  "Mức chi phúc lợi hoặc tỷ lệ phần trăm (%) lao động được hưởng phúc lợi (bảo hiểm, hỗ trợ) trong kỳ."),
    "SSCIFC-S3": ("Biến động nhân sự",
                  "Tỷ lệ phần trăm (%) lao động nghỉ việc/thay đổi trong kỳ (tỷ lệ luân chuyển lao động)."),
    "SSCIFC-S4": ("Sức khỏe của nhân viên",
                  "Tỷ lệ phần trăm (%) lao động được chăm sóc, khám sức khỏe định kỳ trong kỳ."),
    "SSCIFC-S5": ("Thông lệ về an toàn lao động",
                  "Chỉ số an toàn lao động: tần suất tai nạn (LTIFR) hoặc số vụ tai nạn lao động, số giờ huấn luyện an toàn trong kỳ."),
    "SSCIFC-S6": ("Mức độ đa dạng",
                  "Tỷ lệ phần trăm (%) đa dạng của lực lượng lao động, ví dụ tỷ lệ lao động nữ và tỷ lệ nữ trong quản lý."),
    "SSCIFC-S7": ("Củng cố cộng đồng địa phương",
                  "Giá trị đầu tư (VND) hoặc số chương trình hỗ trợ, củng cố cộng đồng địa phương trong kỳ."),
}


def main() -> None:
    kpis = json.loads(OUT.read_text("utf-8"))
    ids = {k["id"] for k in kpis}
    missing = ids - set(ENRICH)
    extra = set(ENRICH) - ids
    assert not missing, f"KPIs with no enrichment entry: {missing}"
    assert not extra, f"Enrichment entries with no KPI: {extra}"

    changed = 0
    for k in kpis:
        # Preserve the verbatim source text once.
        k.setdefault("source", {})
        if "excerpt" not in k["source"]:
            k["source"]["excerpt"] = k["definition"]
        name, definition = ENRICH[k["id"]]
        if k["name"] != name or k["definition"] != definition:
            changed += 1
        k["name"], k["definition"] = name, definition

    OUT.write_text(json.dumps(kpis, ensure_ascii=False, indent=2), encoding="utf-8")
    thin = sum(1 for k in kpis if k["name"].strip() == k["definition"].strip())
    print(f"Enriched {len(kpis)} KPIs ({changed} updated) -> {OUT}")
    print(f"name==definition rows now: {thin} (was 30)")
    print("Verbatim source text preserved in source.excerpt.")


if __name__ == "__main__":
    main()
