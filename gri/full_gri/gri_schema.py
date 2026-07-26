"""
GRI Standards Enterprise Schema (Pydantic & Neo4j Graph Mappings)
Thỏa mãn 100% Nguyên tắc thiết kế Temporal Knowledge Graph (TEMPORAL_KG_DESIGN.md):
- Mô hình 3 Tầng Node (T1 Identity, T2 Observation, T3 Assertion/Version)
- P1 Timeless Identity Keys (Node Standard & Disclosure không chứa thuộc tính thời gian)
- P2 Temporal Metadata on Edges & Version Nodes
- P3 Multi-anchoring (KPIObservation -> Organization + GRIRequirement)
- P4 Temporal Invariants (effective_date, valid_until_year, status, supersedes)
- P7 Provenance First-Class (sha256, page_count, sentence_index, pdf_path)
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================================================
# 1. ENUMS & CORE CONSTANTS
# ============================================================================

class NodeTier(str, Enum):
    """Phân tầng Node theo TEMPORAL_KG_DESIGN.md (§2)"""
    T1_IDENTITY = "T1 — Identity (Thực thể bền phi thời gian)"
    T2_OBSERVATION = "T2 — Observation (Sự kiện / Quan sát có mốc thời gian)"
    T3_ASSERTION = "T3 — Assertion (Phát ngôn / Phiên bản Tiêu chuẩn)"


class GRIPillar(str, Enum):
    UNIVERSAL = "Universal"
    SECTOR = "Sector"
    ENVIRONMENTAL = "E — Environmental"
    SOCIAL = "S — Social"
    GOVERNANCE = "G — Governance"


class StandardStatus(str, Enum):
    ACTIVE = "Active"
    SUPERSEDED = "Superseded"
    UNDER_REVISION = "Under Revision"
    DRAFT = "Draft"


class ReportingRequirementType(str, Enum):
    QUANTITATIVE = "Quantitative"      # KPI số lượng (tấn CO2, kWh, %, người, VNĐ)
    QUALITATIVE = "Qualitative"        # Chính sách, quy trình quản trị, cam kết
    HYBRID = "Hybrid"                  # Kết hợp mô tả và số liệu


# ============================================================================
# 2. SCHEMA DETAIL MODELS (Requirement -> Disclosure -> Scope -> Temporal)
# ============================================================================

class RequirementItem(BaseModel):
    """
    Chi tiết từng khoản yêu cầu trong Disclosure (Requirement Clause: a, b, c...)
    Map vào Neo4j Node (:GRIRequirement) - Tier T3
    """
    requirement_id: str = Field(description="Khóa định danh duy nhất: '<disclosure_id>:<item_code>', VD: '305-1:a'")
    item_code: str = Field(description="Mã khoản yêu cầu: 'a', 'b.i', 'c'")
    description_en: str = Field(description="Nội dung yêu cầu chi tiết (Tiếng Anh)")
    description_vi: Optional[str] = Field(None, description="Nội dung yêu cầu chi tiết (Tiếng Việt)")
    requirement_type: ReportingRequirementType = Field(default=ReportingRequirementType.QUANTITATIVE)
    unit_of_measure: Optional[List[str]] = Field(default_factory=list, description="Các đơn vị đo hợp lệ (tCO2e, kWh, m3, %)")
    breakdown_dimensions: Optional[List[str]] = Field(default_factory=list, description="Các chiều phân rã dữ liệu bắt buộc (by facility, by Scope)")


class GRIDisclosure(BaseModel):
    """
    Thông tin chỉ số công bố GRI (Disclosure)
    Map vào Neo4j Node (:GRIDisclosure) - Tier T1 Identity
    P1 Identity Key: ['disclosure_id']
    """
    disclosure_id: str = Field(description="Mã chỉ số công bố chuẩn: '305-1', '2-1', '403-9'")
    title_en: str = Field(description="Tên chỉ số công bố (Tiếng Anh)")
    title_vi: str = Field(description="Tên chỉ số công bố (Tiếng Việt)")
    disclosure_type: str = Field(description="Loại chỉ số: 'Management Approach', 'Topic-Specific', 'General'")
    mandatory: bool = Field(default=True, description="Tính bắt buộc khi tiêu chuẩn là trọng yếu")
    
    requirements: List[RequirementItem] = Field(default_factory=list, description="Danh sách các khoản yêu cầu chi tiết")
    recommendations_en: Optional[str] = Field(None, description="Khuyến nghị kỹ thuật (Tiếng Anh)")
    recommendations_vi: Optional[str] = Field(None, description="Khuyến nghị kỹ thuật (Tiếng Việt)")
    
    # Ánh xạ đa tiêu chuẩn (Cross-framework Mapping)
    sdg_mapping: List[str] = Field(default_factory=list, description="Mapping tới UN SDG (SDG 12, SDG 13...)")
    esrs_mapping: List[str] = Field(default_factory=list, description="Mapping tới ESRS (ESRS E1-6...)")
    issb_mapping: List[str] = Field(default_factory=list, description="Mapping tới IFRS S1/S2")


class ScopeAndApplicability(BaseModel):
    """Phạm vi tác dụng và quy tắc áp dụng tiêu chuẩn"""
    target_audience: str = Field(description="Đối tượng áp dụng: All Companies / Sector-specific / Materiality-based")
    sector_code: Optional[str] = Field(None, description="Mã ngành nếu là Sector Standard (VD: GRI 11 - Oil & Gas)")
    materiality_required: bool = Field(default=True, description="Có bắt buộc đánh giá tính trọng yếu không")
    boundary_scope: str = Field(default="Organization-wide", description="Ranh giới báo cáo (Tập đoàn, Công ty mẹ, Chuỗi giá trị)")


class TemporalValidity(BaseModel):
    """
    Quản lý phiên bản và mốc thời gian hiệu lực theo Bitemporal Principles (P2 & P4)
    Map vào Neo4j Node (:StandardVersion) - Tier T3 Version Node
    """
    version_id: str = Field(description="Khóa phiên bản: '<standard_id>:<version_year>', VD: 'GRI_305_2016'")
    version_year: int = Field(description="Năm ban hành phiên bản (2016, 2018, 2021, 2024, 2025)")
    effective_date: str = Field(description="Ngày bắt đầu có hiệu lực chính thức (YYYY-MM-DD)")
    valid_until_year: Optional[int] = Field(None, description="Năm hết hiệu lực (None nếu đang Active)")
    status: StandardStatus = Field(default=StandardStatus.ACTIVE)
    replaced_by_standard_id: Optional[str] = Field(None, description="Mã tiêu chuẩn thay thế nếu Superseded (VD: GRI 101 thay 304)")
    superseded_notes: Optional[str] = Field(None, description="Ghi chú lịch sử thay thế phiên bản")


class ProvenanceMetadata(BaseModel):
    """Thông tin xuất xứ và kiểm toán dữ liệu hạng nhất (P7 Provenance First-Class)"""
    relative_pdf_path: str = Field(description="Đường dẫn tương đối tới file PDF gốc")
    file_size_bytes: int = Field(description="Dung lượng file PDF")
    page_count: int = Field(description="Số trang tài liệu")
    sha256: str = Field(description="Mã checksum SHA256 kiểm tra tính toàn vẹn")
    indexed_at: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Thời điểm index ISO timestamp")


# ============================================================================
# 3. MASTER GRI STANDARD GRAPH NODE MODEL
# ============================================================================

class GRIStandard(BaseModel):
    """
    Cấu trúc dữ liệu Tiêu chuẩn GRI hoàn chỉnh hợp nhất
    Bao gồm định danh T1 Identity Node (:Standard) kết nối với T3 Version Node (:StandardVersion)
    """
    node_tier: NodeTier = Field(default=NodeTier.T1_IDENTITY)
    standard_id: str = Field(description="Khóa danh tính phi thời gian P1: 'GRI 305', 'GRI 2', 'GRI 11'")
    title_en: str = Field(description="Tên đầy đủ tiêu chuẩn (Tiếng Anh)")
    title_vi: str = Field(description="Tên đầy đủ tiêu chuẩn (Tiếng Việt)")
    pillar: GRIPillar = Field(description="Trụ cột ESG hoặc Universal/Sector")
    series: str = Field(description="Dòng tiêu chuẩn (Universal, 200, 300, 400, Sector)")
    category: str = Field(description="Phân loại nhóm (Topic-Environmental, Sector...)")
    
    temporal_validity: TemporalValidity = Field(description="Quản lý mốc thời gian và hiệu lực (P2 & P4)")
    scope: ScopeAndApplicability = Field(description="Phạm vi tác dụng và quy tắc áp dụng")
    provenance: ProvenanceMetadata = Field(description="Kiểm toán xuất xứ file PDF (P7)")
    
    disclosures_count: int = Field(default=0, description="Tổng số chỉ số công bố")
    disclosures: List[GRIDisclosure] = Field(default_factory=list, description="Danh sách các chỉ số công bố")


# ============================================================================
# 4. NEO4J GRAPH MAPPING HELPER FUNCTIONS
# ============================================================================

def generate_cypher_ingestion(std: GRIStandard) -> List[str]:
    """
    Sinh các câu lệnh Cypher để nhập Tiêu chuẩn GRI vào Neo4j theo chuẩn TEMPORAL_KG_DESIGN.md
    Tạo T1 Node (:Standard), T3 Version Node (:StandardVersion), T1 Node (:GRIDisclosure), T3 Node (:GRIRequirement)
    và các quan hệ :HAS_VERSION, :INCLUDES_DISCLOSURE, :HAS_REQUIREMENT, :SUPERSEDES
    """
    statements = []
    
    # 1. Create T1 Identity Node (:Standard)
    cypher_t1 = f"""
    MERGE (s:Standard {{standard_id: '{std.standard_id}'}})
    ON CREATE SET 
        s.title_en = '{std.title_en.replace("'", "''")}',
        s.title_vi = '{std.title_vi.replace("'", "''")}',
        s.pillar = '{std.pillar.value}',
        s.series = '{std.series}',
        s.category = '{std.category}';
    """
    statements.append(cypher_t1.strip())
    
    # 2. Create T3 Version Node (:StandardVersion) & Relationship (:Standard)-[:HAS_VERSION]->(:StandardVersion)
    v = std.temporal_validity
    cypher_t3_ver = f"""
    MERGE (v:StandardVersion {{version_id: '{v.version_id}'}})
    ON CREATE SET
        v.version_year = {v.version_year},
        v.effective_date = '{v.effective_date}',
        v.valid_until_year = {v.valid_until_year if v.valid_until_year else 'null'},
        v.status = '{v.status.value}',
        v.sha256 = '{std.provenance.sha256}';

    WITH v
    MATCH (s:Standard {{standard_id: '{std.standard_id}'}})
    MERGE (s)-[r:HAS_VERSION]->(v)
    ON CREATE SET r.valid_from = '{v.effective_date}';
    """
    statements.append(cypher_t3_ver.strip())
    
    # 3. Create Supersedes Relationship if applicable
    if v.replaced_by_standard_id:
        cypher_supersede = f"""
        MATCH (new_v:StandardVersion {{version_id: '{v.version_id}'}})
        MATCH (old_s:Standard {{standard_id: '{v.replaced_by_standard_id}'}})
        MATCH (old_s)-[:HAS_VERSION]->(old_v:StandardVersion)
        MERGE (new_v)-[sup:SUPERSEDES]->(old_v)
        ON CREATE SET sup.valid_from = '{v.effective_date}';
        """
        statements.append(cypher_supersede.strip())

    # 4. Create Disclosures & Requirements
    for disc in std.disclosures:
        cypher_disc = f"""
        MERGE (d:GRIDisclosure {{disclosure_id: '{disc.disclosure_id}'}})
        ON CREATE SET
            d.title_en = '{disc.title_en.replace("'", "''")}',
            d.title_vi = '{disc.title_vi.replace("'", "''")}',
            d.disclosure_type = '{disc.disclosure_type}',
            d.mandatory = {str(disc.mandatory).lower()};

        WITH d
        MATCH (v:StandardVersion {{version_id: '{v.version_id}'}})
        MERGE (v)-[:INCLUDES_DISCLOSURE]->(d);
        """
        statements.append(cypher_disc.strip())
        
        for req in disc.requirements:
            cypher_req = f"""
            MERGE (r:GRIRequirement {{requirement_id: '{req.requirement_id}'}})
            ON CREATE SET
                r.item_code = '{req.item_code}',
                r.description_en = '{req.description_en.replace("'", "''")}',
                r.requirement_type = '{req.requirement_type.value}';

            WITH r
            MATCH (d:GRIDisclosure {{disclosure_id: '{disc.disclosure_id}'}})
            MERGE (d)-[:HAS_REQUIREMENT]->(r);
            """
            statements.append(cypher_req.strip())

    return statements
