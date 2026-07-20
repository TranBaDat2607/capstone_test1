"""Evidence Service for ESG Evidence View.

Provides company lists, search filtering, and detailed 3-column ESG evidence
for requested issuers with comprehensive multi-year data (2022-2024) across all 5 companies.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
KPI_DEFS_FILE = REPO_ROOT / "kpi_definitions_construction.json"

# Load TT96 KPI definitions if file exists
KPI_DEFINITIONS: List[Dict[str, Any]] = []
if KPI_DEFS_FILE.exists():
    try:
        with open(KPI_DEFS_FILE, "r", encoding="utf-8") as f:
            KPI_DEFINITIONS = json.load(f)
    except Exception:
        pass

# Company Registry
COMPANIES = [
    {
        "ticker": "VNM",
        "name": "Công ty Cổ phần Sữa Việt Nam",
        "short": "Vinamilk",
        "industry": "Thực phẩm & Đồ uống",
        "year_range": "2022 - 2024",
        "available_years": ["2022 - 2024", "2024", "2023", "2022"]
    },
    {
        "ticker": "AAA",
        "name": "Công ty Cổ phần Nhựa An Phát Xanh",
        "short": "An Phát Xanh",
        "industry": "Bao bì & Nhựa sinh học",
        "year_range": "2022 - 2024",
        "available_years": ["2022 - 2024", "2024", "2023", "2022"]
    },
    {
        "ticker": "HPG",
        "name": "Tập đoàn Hòa Phát",
        "short": "Hòa Phát",
        "industry": "Thép & Khai khoáng",
        "year_range": "2022 - 2024",
        "available_years": ["2022 - 2024", "2024", "2023", "2022"]
    },
    {
        "ticker": "FPT",
        "name": "Công ty Cổ phần FPT",
        "short": "FPT",
        "industry": "Công nghệ thông tin & Viễn thông",
        "year_range": "2022 - 2024",
        "available_years": ["2022 - 2024", "2024", "2023", "2022"]
    },
    {
        "ticker": "MSN",
        "name": "Tập đoàn Masan",
        "short": "Masan Group",
        "industry": "Hàng tiêu dùng & Bán lẻ",
        "year_range": "2022 - 2024",
        "available_years": ["2022 - 2024", "2024", "2023", "2022"]
    }
]

# Rich Evidence Dataset for Demo with Year attributes (Multiple cards for 2022, 2023, 2024)
EVIDENCE_DATASTORE: Dict[str, Dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # 1. VINAMILK (VNM)
    # -------------------------------------------------------------------------
    "VNM": {
        "environment": {
            "verified": [
                # --- 2024 ---
                {
                    "year": "2024",
                    "standard_id": "TT96-6.1.1",
                    "standard_name": "Phát thải khí nhà kính Scope 1 & 2",
                    "gri_equivalent": "GRI 305-1",
                    "claim_quote": "Đạt mốc trung hòa carbon cho Trang trại sữa Nghệ An và Nhà máy Sữa Nước Bình Dương theo chuẩn PAS 2060.",
                    "claim_source": "Báo cáo Phát triển bền vững 2024, trang 22",
                    "verification": {
                        "verifier": "BSI Việt Nam (04/2024)",
                        "finding": "nghiệm thu và cấp chứng nhận Trung hòa Carbon cho 2 đơn vị.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2024",
                    "standard_id": "TT96-6.3.3",
                    "standard_name": "Năng lượng xanh mái nhà",
                    "gri_equivalent": "GRI 302-1",
                    "claim_quote": "Hoàn thành lắp đặt hệ thống pin năng lượng mặt trời mái nhà tại 100% trang trại sinh thái.",
                    "claim_source": "Báo cáo ESG 2024, trang 29",
                    "verification": {
                        "verifier": "Tập đoàn Điện lực EVN (04/2024)",
                        "finding": "nghiệm thu đấu nối và công nhận công suất phát điện xanh 7.2 MWp.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2024",
                    "standard_id": "TT96-6.2.2",
                    "standard_name": "Sử dụng nhựa rPET tái chế",
                    "gri_equivalent": "GRI 301-2",
                    "claim_quote": "Nâng tỷ lệ nhựa rPET tái chế lên 60% đối với toàn bộ bao bì đóng chai năm 2024.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 38",
                    "verification": {
                        "verifier": "SGS Việt Nam (05/2024)",
                        "finding": "kiểm tra độc lập xác nhận đạt tỷ lệ 61.2%.",
                        "status": "confirmed"
                    }
                },
                # --- 2023 ---
                {
                    "year": "2023",
                    "standard_id": "TT96-6.1.2",
                    "standard_name": "Mức giảm phát thải khí nhà kính",
                    "gri_equivalent": "GRI 305-5",
                    "claim_quote": "Chúng tôi đã giảm 15% tổng lượng phát thải khí nhà kính so với năm 2022 nhờ chuyển đổi sang năng lượng sinh khối.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 42",
                    "verification": {
                        "verifier": "PwC Việt Nam (15/05/2024)",
                        "finding": "ghi nhận mức giảm thực tế 15.2% — phù hợp với điều công ty đã công bố.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "ISO 14001",
                    "standard_name": "Quản lý môi trường nhà máy",
                    "gri_equivalent": "GRI 3-3",
                    "claim_quote": "Tất cả các nhà máy sản xuất sữa đều đạt chứng nhận ISO 14001 về hệ thống quản lý môi trường.",
                    "claim_source": "Báo cáo Phát triển bền vững 2023, trang 18",
                    "verification": {
                        "verifier": "Tổng cục Tiêu chuẩn Đo lường Chất lượng (01/2024)",
                        "finding": "cấp mới chứng chỉ cho toàn bộ 13 nhà máy.",
                        "status": "confirmed"
                    }
                },
                # --- 2022 ---
                {
                    "year": "2022",
                    "standard_id": "TT96-6.4.2",
                    "standard_name": "Tái sử dụng nước sạch",
                    "gri_equivalent": "GRI 303-5",
                    "claim_quote": "Tái sử dụng 25% tổng lượng nước thải sau xử lý cho mục đích tưới cây và vệ sinh công nghiệp.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 51",
                    "verification": {
                        "verifier": "Viện Môi trường & Tài nguyên (11/2022)",
                        "finding": "kết quả khảo sát độc lập đạt tỷ lệ tuần hoàn nước 26.1%.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.3.2",
                    "standard_name": "Tiết kiệm năng lượng chiếu sáng",
                    "gri_equivalent": "GRI 302-4",
                    "claim_quote": "Thay thế 100% đèn chiếu sáng nhà xưởng bằng đèn LED tiết kiệm điện năng năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 48",
                    "verification": {
                        "verifier": "Công ty Điện lực Lực lượng sản xuất (12/2022)",
                        "finding": "xác nhận số lượng điện năng tiết kiệm đạt 1.8 triệu kWh.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [
                # --- 2024 ---
                {
                    "year": "2024",
                    "standard_id": "TT96-6.2.2",
                    "standard_name": "Giảm thiểu bao bì nhựa PVC",
                    "gri_equivalent": "GRI 301-3",
                    "claim_quote": "Cắt giảm hoàn toàn màng bọc nhựa PVC trên tất cả các lốc sản phẩm sữa hộp phân phối tại siêu thị.",
                    "claim_source": "Báo cáo Phát triển bền vững 2024, trang 14",
                    "verification": {
                        "verifier": "Khảo sát Thị trường Độc lập (05/2024)",
                        "finding": "ghi nhận 35% dòng sản phẩm sữa chua uống vẫn lưu thông màng bọc PVC cũ.",
                        "status": "contradicted"
                    }
                },
                # --- 2023 ---
                {
                    "year": "2023",
                    "standard_id": "TT96-6.3.1",
                    "standard_name": "Sử dụng nước và xả thải",
                    "gri_equivalent": "GRI 303-4",
                    "claim_quote": "100% nước thải tại các nhà máy sản xuất được xử lý đạt chuẩn loại A trước khi xả ra môi trường.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 58",
                    "verification": {
                        "verifier": "Sở Tài nguyên & Môi trường (12/09/2023)",
                        "finding": "phát hiện 2 nhà máy xả thải vượt ngưỡng — mâu thuẫn với điều công ty đã công bố.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "GRI 302",
                    "standard_name": "Tỷ lệ năng lượng sinh khối",
                    "gri_equivalent": "GRI 302-1",
                    "claim_quote": "80% năng lượng tiêu thụ tại trang trại Tây Ninh đến từ nguồn sinh khối sạch.",
                    "claim_source": "Báo cáo ESG 2023, trang 25",
                    "verification": {
                        "verifier": "Kiểm toán Năng lượng Độc lập (03/2024)",
                        "finding": "tìm thấy tỷ lệ thực tế chỉ đạt 45% — thực tế không đúng như công bố.",
                        "status": "contradicted"
                    }
                },
                # --- 2022 ---
                {
                    "year": "2022",
                    "standard_id": "TT96-6.5.1",
                    "standard_name": "Tuân thủ luật môi trường",
                    "gri_equivalent": "GRI 2-27",
                    "claim_quote": "Không phát sinh bất kỳ vụ vi phạm quy định hành chính nào về bảo vệ môi trường trong năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 62",
                    "verification": {
                        "verifier": "Thanh tra Môi trường Tỉnh (10/2022)",
                        "finding": "xử phạt hành chính 110 triệu đồng đối với trang trại con do chậm nghiệm thu hệ thống xử lý mùi.",
                        "status": "contradicted"
                    }
                }
            ],
            "missing": [
                # --- 2024 ---
                {
                    "year": "2024",
                    "standard_id": "GRI 305-3",
                    "standard_name": "Phát thải gián tiếp Scope 3",
                    "gri_equivalent": "GRI 305-3",
                    "requirement": "Không công bố số liệu phát thải Scope 3 từ hoạt động vận tải của đối tác giao vận bên thứ ba.",
                    "note": "Lưu ý: GRI Standards 2021 yêu cầu bắt buộc lộ trình kiểm kê phát thải Scope 3."
                },
                # --- 2023 ---
                {
                    "year": "2023",
                    "standard_id": "TT96-6.4.1",
                    "standard_name": "Khai thác nước ngầm",
                    "gri_equivalent": "GRI 303-3",
                    "requirement": "Theo quy định TT96, công ty bắt buộc phải công bố thông tin về khối lượng nước ngầm khai thác — nhưng không tìm thấy bất kỳ số liệu nào.",
                    "note": "Lưu ý: Việc không công bố chỉ tiêu bắt buộc có thể là dấu hiệu công ty đang che giấu thông tin bất lợi."
                },
                # --- 2022 ---
                {
                    "year": "2022",
                    "standard_id": "TT96-6.5.2",
                    "standard_name": "Tổng tiền phạt môi trường",
                    "gri_equivalent": "GRI 2-27",
                    "requirement": "Chỉ tiêu tổng số tiền phạt do vi phạm môi trường hoàn toàn bị bỏ trống trong mục công khai.",
                    "note": "Lưu ý: Thiếu thông tin minh bạch tài chính về chi phí phạt môi trường."
                }
            ]
        },
        "social": {
            "verified": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.7.1",
                    "standard_name": "Quỹ sữa Vươn cao Việt Nam",
                    "gri_equivalent": "GRI 413-1",
                    "claim_quote": "Trao tặng 1.5 triệu ly sữa cho trẻ em vùng cao và trẻ em có hoàn cảnh đặc biệt.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 72",
                    "verification": {
                        "verifier": "Quỹ Bảo trợ Trẻ em Việt Nam (06/2024)",
                        "finding": "xác nhận biên bản bàn giao sữa tại 22 tỉnh thành.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.6.1",
                    "standard_name": "Mức lương trung bình người lao động",
                    "gri_equivalent": "GRI 401-1",
                    "claim_quote": "Duy trì việc làm cho 9.800 cán bộ công nhân viên với mức thu nhập bình quân tăng 8.5% so với 2022.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 64",
                    "verification": {
                        "verifier": "Kiểm toán Deloitte Việt Nam (04/2024)",
                        "finding": "xác nhận quỹ lương và chi phí lao động tăng tương ứng 8.6%.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.6.3",
                    "standard_name": "Số giờ đào tạo nhân viên",
                    "gri_equivalent": "GRI 404-1",
                    "claim_quote": "Đạt bình quân 38 giờ đào tạo trên mỗi cán bộ công nhân viên trong năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 58",
                    "verification": {
                        "verifier": "Trung tâm Kiểm định Nhân sự (12/2022)",
                        "finding": "xác nhận tổng số lượt đào tạo là 372.400 giờ.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [
                {
                    "year": "2023",
                    "standard_id": "TT96-6.6.2",
                    "standard_name": "An toàn và sức khỏe lao động",
                    "gri_equivalent": "GRI 403-9",
                    "claim_quote": "Không ghi nhận bất kỳ tai nạn lao động nghiêm trọng nào tại tất cả trang trại và nhà máy.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 68",
                    "verification": {
                        "verifier": "Thanh tra LĐ-TB&XH (08/2023)",
                        "finding": "ghi nhận 1 sự cố mất an toàn lao động dẫn tới thương tích nặng tại chi nhánh nhà máy phía Nam.",
                        "status": "contradicted"
                    }
                }
            ],
            "missing": [
                {
                    "year": "2023",
                    "standard_id": "GRI 405-2",
                    "standard_name": "Tỷ lệ lương theo giới tính",
                    "gri_equivalent": "GRI 405-2",
                    "requirement": "Không công bố chênh lệch mức lương cơ bản và thù lao giữa nam và nữ theo từng cấp bậc lao động.",
                    "note": "Lưu ý: Đây là chỉ tiêu cốt lõi theo GRI Standards về bình đẳng giới trong doanh nghiệp."
                }
            ]
        },
        "governance": {
            "verified": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.8.1",
                    "standard_name": "Tín dụng xanh",
                    "gri_equivalent": "GRI 2-23",
                    "claim_quote": "Tiếp tục duy trì gói tài chính xanh ưu đãi cùng các ngân hàng quốc tế để tài trợ dự án năng lượng mặt trời.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 18",
                    "verification": {
                        "verifier": "Ngân hàng Sumitomo Mitsui SMBC (03/2024)",
                        "finding": "xác nhận danh mục tài sản đạt chuẩn ESG.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.8.1",
                    "standard_name": "Huy động vốn xanh & ESG",
                    "gri_equivalent": "GRI 2-23",
                    "claim_quote": "Thành công ký kết gói tín dụng xanh trị giá 100 triệu USD cùng HSBC phục vụ phát triển trang trại sinh thái.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 12",
                    "verification": {
                        "verifier": "Ngân hàng HSBC Việt Nam (06/2023)",
                        "finding": "xác nhận giải ngân theo đúng khung tài chính bền vững.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [],
            "missing": [
                {
                    "year": "2023",
                    "standard_id": "GRI 2-15",
                    "standard_name": "Xung đột lợi ích HĐQT",
                    "gri_equivalent": "GRI 2-15",
                    "requirement": "Thiếu thông tin chi tiết về quy trình kiểm soát giao dịch với các bên liên quan của thành viên HĐQT độc lập.",
                    "note": "Lưu ý: Cần bổ sung theo thông lệ quản trị công ty tốt của OECD."
                }
            ]
        }
    },

    # -------------------------------------------------------------------------
    # 2. AN PHÁT XANH (AAA)
    # -------------------------------------------------------------------------
    "AAA": {
        "environment": {
            "verified": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.2.2",
                    "standard_name": "Mở rộng sản phẩm nhựa tự hủy AnEco",
                    "gri_equivalent": "GRI 301-2",
                    "claim_quote": "Xuất khẩu túi nhựa sinh học AnEco sang hơn 20 quốc gia châu Âu và Bắc Mỹ năm 2024.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 28",
                    "verification": {
                        "verifier": "Cục Hải quan Việt Nam (04/2024)",
                        "finding": "xác nhận kim ngạch xuất khẩu hạt nhựa và thành phẩm sinh học tăng 18.5%.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.3.2",
                    "standard_name": "Sáng kiến tiết kiệm năng lượng điện",
                    "gri_equivalent": "GRI 302-4",
                    "claim_quote": "Tiết kiệm 2.1 triệu kWh điện nhờ thay thế hệ thống máy ép phun công nghệ mới.",
                    "claim_source": "Báo cáo ESG 2023, trang 31",
                    "verification": {
                        "verifier": "Công ty Điện lực Hải Dương (01/2024)",
                        "finding": "xác nhận số liệu giảm tiêu thụ điện năng sản xuất thực tế 2.15 triệu kWh.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.2.2",
                    "standard_name": "Tỷ lệ nguyên vật liệu tự hủy",
                    "gri_equivalent": "GRI 301-2",
                    "claim_quote": "Phát triển dòng sản phẩm túi nhựa sinh học phân hủy hoàn toàn AnEco đạt chứng nhận quốc tế TÜV Austria năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 36",
                    "verification": {
                        "verifier": "TÜV Austria (2022)",
                        "finding": "cấp chứng chỉ OK biobased và OK compost INDUSTRIAL cho sản phẩm.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.2.1",
                    "standard_name": "Tỷ lệ hạt nhựa nguyên sinh vứt bỏ",
                    "gri_equivalent": "GRI 306-3",
                    "claim_quote": "Thu hồi và tái chế 100% phế liệu nhựa phát sinh trong quá trình thổi màng năm 2024.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 41",
                    "verification": {
                        "verifier": "Đoàn Kiểm tra Môi trường (03/2024)",
                        "finding": "phát hiện tỷ lệ phế liệu nhựa chưa qua xử lý lưu kho vượt thời hạn quy định.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.1.1",
                    "standard_name": "Kiểm kê phát thải KNK Scope 1 & 2",
                    "gri_equivalent": "GRI 305-1",
                    "claim_quote": "Hoàn thành kiểm kê toàn diện lượng phát thải khí nhà kính cho 3 nhà máy chủ lực năm 2023.",
                    "claim_source": "Báo cáo ESG 2023, trang 19",
                    "verification": {
                        "verifier": "Tổ chức Đánh giá Độc lập (10/2023)",
                        "finding": "báo cáo thiếu số liệu phát thải nhiên liệu đốt trực tiếp của nhà máy số 2.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.1.1",
                    "standard_name": "Tăng trưởng lợi nhuận bền vững",
                    "gri_equivalent": "GRI 201-1",
                    "claim_quote": "Đảm bảo tăng trưởng doanh thu và lợi nhuận đi đôi với mục tiêu bảo vệ môi trường.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 22",
                    "verification": {
                        "verifier": "Báo cáo Tài chính Kiểm toán 2022",
                        "finding": "ghi nhận lợi nhuận ròng giảm -42.3% so với kỳ trước.",
                        "status": "contradicted"
                    }
                }
            ],
            "missing": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.4.1",
                    "standard_name": "Tổng lượng nước tiêu thụ",
                    "gri_equivalent": "GRI 303-3",
                    "requirement": "Không công bố số liệu tiêu thụ nước công nghiệp tại Nhà máy bao bì An Phát 6 năm 2024.",
                    "note": "Lưu ý: Quy định TT96 yêu cầu rõ khối lượng nước tiêu thụ theo từng nhà máy sản xuất."
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.5.1",
                    "standard_name": "Số lần bị phạt vi phạm môi trường",
                    "gri_equivalent": "GRI 2-27",
                    "requirement": "Bỏ qua chỉ tiêu số lần bị kiểm tra và phạt vi phạm hành chính về môi trường năm 2023.",
                    "note": "Lưu ý: Thiếu tính minh bạch theo khuyến nghị của UBCKNN."
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.1.1",
                    "standard_name": "Tổng phát thải CO2 quy đổi",
                    "gri_equivalent": "GRI 305-1",
                    "requirement": "Không công bố số liệu tổng phát thải KNK quy đổi tCO2e cho cụm nhà máy tại Hải Dương năm 2022.",
                    "note": "Lưu ý: TT96 yêu cầu bắt buộc doanh nghiệp sản xuất niêm yết phải kiểm kê KNK."
                }
            ]
        },
        "social": {"verified": [], "contradicted": [], "missing": []},
        "governance": {"verified": [], "contradicted": [], "missing": []}
    },

    # -------------------------------------------------------------------------
    # 3. TẬP ĐOÀN HÒA PHÁT (HPG)
    # -------------------------------------------------------------------------
    "HPG": {
        "environment": {
            "verified": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.3.3",
                    "standard_name": "Tự chủ điện từ khí thải lò cao",
                    "gri_equivalent": "GRI 302-4",
                    "claim_quote": "Nâng tỷ lệ tự chủ điện toàn Tập đoàn lên 85% nhờ thu hồi triệt để khí dư lò cao để phát điện năm 2024.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 34",
                    "verification": {
                        "verifier": "EVN & Sở Công Thương Quảng Ngãi (03/2024)",
                        "finding": "xác nhận tổng sản lượng điện tự phát đạt 2.8 tỷ kWh.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.3.3",
                    "standard_name": "Tiết kiệm năng lượng & Thu hồi nhiệt dư",
                    "gri_equivalent": "GRI 302-4",
                    "claim_quote": "100% các liên hợp thép Dung Quất và Hải Dương áp dụng công nghệ thu hồi nhiệt dư để phát điện năm 2023.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 48",
                    "verification": {
                        "verifier": "Tập đoàn Điện lực Việt Nam EVN (02/2024)",
                        "finding": "xác nhận lượng điện tự dùng từ nhiệt khí thải đạt 2.4 tỷ kWh.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "ISO 14001",
                    "standard_name": "Chứng nhận quản lý môi trường thép",
                    "gri_equivalent": "GRI 3-3",
                    "claim_quote": "Khu liên hợp sản xuất Thép Hòa Phát Dung Quất đạt tiêu chuẩn quản lý môi trường ISO 14001:2015 năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 40",
                    "verification": {
                        "verifier": "Bureau Veritas Việt Nam (09/2022)",
                        "finding": "cấp chứng nhận đạt chuẩn ISO 14001.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.1.1",
                    "standard_name": "Cường độ phát thải CO2 trên tấn thép",
                    "gri_equivalent": "GRI 305-4",
                    "claim_quote": "Phấn đấu giảm cường độ phát thải khí nhà kính xuống 1.85 tấn CO2/tấn thép thô tại Khu liên hợp 2 năm 2024.",
                    "claim_source": "Báo cáo ESG 2024, trang 21",
                    "verification": {
                        "verifier": "Kiểm toán Môi trường Quốc tế (04/2024)",
                        "finding": "đo lường thực tế ghi nhận mức phát thải trung bình đạt 2.08 tấn CO2/tấn thép.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.1.1",
                    "standard_name": "Cường độ phát thải KNK",
                    "gri_equivalent": "GRI 305-4",
                    "claim_quote": "Giảm cường độ phát thải khí nhà kính xuống dưới 1.9 tấn CO2/tấn thép thô năm 2023.",
                    "claim_source": "Báo cáo Phát triển Bền vững 2023, trang 28",
                    "verification": {
                        "verifier": "Tổ chức Kiểm định Độc lập (11/2023)",
                        "finding": "đo lường thực tế tại lò cao 3 ghi nhận mức phát thải 2.12 tấn CO2/tấn thép.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.4.1",
                    "standard_name": "Kiểm soát nước xả thải làm mát lò cao",
                    "gri_equivalent": "GRI 303-4",
                    "claim_quote": "Nước làm mát lò cao được tuần hoàn kín 100% không xả ra vịnh Dung Quất năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 55",
                    "verification": {
                        "verifier": "Cục Môi trường Miền Trung (08/2022)",
                        "finding": "phát hiện hiện tượng rò rỉ nhiệt nước xả làm mát tại điểm xả ven bờ.",
                        "status": "contradicted"
                    }
                }
            ],
            "missing": [
                {
                    "year": "2024",
                    "standard_id": "GRI 305-3",
                    "standard_name": "Phát thải Scope 3 từ quặng sắt nhập khẩu",
                    "gri_equivalent": "GRI 305-3",
                    "requirement": "Chưa công bố dữ liệu phát thải gián tiếp từ quá trình khai thác và vận tải quặng sắt nhập từ Úc năm 2024.",
                    "note": "Lưu ý: Ngành thép chịu áp lực CBAM (Cơ chế điều chỉnh biên giới carbon) của EU."
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.4.2",
                    "standard_name": "Tỷ lệ nước tuần hoàn tái sử dụng",
                    "gri_equivalent": "GRI 303-5",
                    "requirement": "Chưa công bố chi tiết tỷ lệ tiêu hao nước trên tấn sản phẩm thép tại Đại dự án Dung Quất 2 năm 2023.",
                    "note": "Lưu ý: Cần minh bạch thông tin nguồn nước giải nhiệt lò cao."
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.5.2",
                    "standard_name": "Chi phí xử phạt vi phạm hành chính môi trường",
                    "gri_equivalent": "GRI 2-27",
                    "requirement": "Bỏ trống mục thông tin xử phạt vi phạm môi trường hành chính trong năm 2022.",
                    "note": "Lưu ý: Yêu cầu bắt buộc báo cáo công khai theo Thông tư 96."
                }
            ]
        },
        "social": {"verified": [], "contradicted": [], "missing": []},
        "governance": {"verified": [], "contradicted": [], "missing": []}
    },

    # -------------------------------------------------------------------------
    # 4. TẬP ĐOÀN FPT (FPT)
    # -------------------------------------------------------------------------
    "FPT": {
        "environment": {
            "verified": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.3.2",
                    "standard_name": "Tối ưu hóa năng lượng Data Center",
                    "gri_equivalent": "GRI 302-4",
                    "claim_quote": "Đạt chỉ số hiệu quả sử dụng năng lượng PUE = 1.4 tại Trung tâm Dữ liệu FPT Fornix năm 2024.",
                    "claim_source": "Báo cáo Thường niên 2024, trang 41",
                    "verification": {
                        "verifier": "Uptime Institute (02/2024)",
                        "finding": "chứng nhận thiết kế và vận hành Data Center Tier III đạt hiệu suất PUE công bố.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.1.2",
                    "standard_name": "Sáng kiến Văn phòng Xanh",
                    "gri_equivalent": "GRI 302-5",
                    "claim_quote": "Tất cả các tòa nhà FPT Complex và FPT Tower chuyển đổi 100% sang hệ thống chiếu sáng thông minh năm 2023.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 52",
                    "verification": {
                        "verifier": "Hội đồng Công trình Xanh VGBC (2023)",
                        "finding": "chứng nhận công trình đạt tiêu chuẩn Lotus Gold.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.2.2",
                    "standard_name": "Chuyển đổi số giảm văn phòng phẩm giấy",
                    "gri_equivalent": "GRI 301-2",
                    "claim_quote": "Cắt giảm 80% lượng giấy in văn phòng nhờ áp dụng chữ ký số và hệ thống phê duyệt FPT eContract năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 45",
                    "verification": {
                        "verifier": "Kiểm toán Nội bộ FPT (12/2022)",
                        "finding": "xác nhận số liệu chi phí mua sắm giấy in giảm 81.2%.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.3.1",
                    "standard_name": "Tổng năng lượng tiêu thụ công nghệ",
                    "gri_equivalent": "GRI 302-1",
                    "claim_quote": "Tiết kiệm 10% lượng điện tiêu thụ toàn hệ thống văn phòng phần mềm năm 2024.",
                    "claim_source": "Báo cáo ESG 2024, trang 18",
                    "verification": {
                        "verifier": "Kiểm toán Năng lượng Công nghệ (04/2024)",
                        "finding": "lượng điện thực tế tăng 6.1% do số lượng máy chủ AI hoạt động liên tục.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.3.1",
                    "standard_name": "Tiêu thụ năng lượng tổng thể",
                    "gri_equivalent": "GRI 302-1",
                    "claim_quote": "Tổng lượng điện tiêu thụ toàn hệ thống văn phòng giảm 5% so với năm 2022.",
                    "claim_source": "Báo cáo ESG 2023, trang 27",
                    "verification": {
                        "verifier": "Báo cáo Năng lượng Độc lập (03/2024)",
                        "finding": "tổng điện năng tiêu thụ thực tế tăng 4.2% do mở rộng quy mô hệ thống máy chủ.",
                        "status": "contradicted"
                    }
                }
            ],
            "missing": [
                {
                    "year": "2024",
                    "standard_id": "GRI 305-3",
                    "standard_name": "Kiểm kê Scope 3 từ dịch vụ đám mây",
                    "gri_equivalent": "GRI 305-3",
                    "requirement": "Chưa thực hiện đo lường lượng phát thải KNK Scope 3 từ hạ tầng điện toán đám mây thuê ngoài (AWS, Azure) năm 2024.",
                    "note": "Lưu ý: Yêu cầu quan trọng đối với tập đoàn công nghệ thông tin."
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.2.1",
                    "standard_name": "Quản lý rác thải điện tử (e-Waste)",
                    "gri_equivalent": "GRI 306-3",
                    "requirement": "Không công bố khối lượng thiết bị máy tính, linh kiện điện tử thanh lý và quy trình xử lý rác thải công nghệ năm 2023.",
                    "note": "Lưu ý: Khai báo rác thải điện tử là khuyến nghị hàng đầu cho doanh nghiệp ICT."
                }
            ]
        },
        "social": {"verified": [], "contradicted": [], "missing": []},
        "governance": {"verified": [], "contradicted": [], "missing": []}
    },

    # -------------------------------------------------------------------------
    # 5. TẬP ĐOÀN MASAN (MSN)
    # -------------------------------------------------------------------------
    "MSN": {
        "environment": {
            "verified": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.2.1",
                    "standard_name": "Nông nghiệp sạch WinEco",
                    "gri_equivalent": "GRI 301-1",
                    "claim_quote": "100% rau củ WinEco đạt tiêu chuẩn VietGAP/GlobalGAP và áp dụng công nghệ tưới nhỏ giọt Israel năm 2024.",
                    "claim_source": "Báo cáo Bền vững 2024, trang 33",
                    "verification": {
                        "verifier": "Bureau Veritas (03/2024)",
                        "finding": "cấp tái chứng nhận GlobalGAP toàn bộ 14 trang trại.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "ISO 14001",
                    "standard_name": "Quản lý môi trường chế biến thực phẩm",
                    "gri_equivalent": "GRI 3-3",
                    "claim_quote": "Tất cả các nhà máy Masan Consumer Goods đạt tiêu chuẩn quản lý môi trường ISO 14001 năm 2023.",
                    "claim_source": "Báo cáo Bền vững 2023, trang 39",
                    "verification": {
                        "verifier": "SGS Việt Nam (09/2023)",
                        "finding": "xác nhận hiệu lực chứng chỉ ISO 14001.",
                        "status": "confirmed"
                    }
                },
                {
                    "year": "2022",
                    "standard_id": "TT96-6.3.2",
                    "standard_name": "Sáng kiến bao bì mỏng giảm nhựa",
                    "gri_equivalent": "GRI 301-2",
                    "claim_quote": "Giảm 15% độ dày chai nhựa PET nước mắm Chin-su giúp cắt giảm 1.200 tấn nhựa nguyên sinh năm 2022.",
                    "claim_source": "Báo cáo Thường niên 2022, trang 48",
                    "verification": {
                        "verifier": "Kiểm toán Chuỗi cung ứng (11/2022)",
                        "finding": "xác nhận tổng khối lượng nhựa nguyên sinh giảm 1.240 tấn.",
                        "status": "confirmed"
                    }
                }
            ],
            "contradicted": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.2.2",
                    "standard_name": "Tỷ lệ phân loại rác thải tại WinMart",
                    "gri_equivalent": "GRI 306-2",
                    "claim_quote": "Thực hiện phân loại rác thải hữu cơ và nhựa túi dùng 1 lần tại 100% siêu thị WinMart năm 2024.",
                    "claim_source": "Báo cáo ESG 2024, trang 25",
                    "verification": {
                        "verifier": "Khảo sát Chi cục Môi trường (04/2024)",
                        "finding": "phát hiện 40% điểm bán lẻ chưa tuân thủ phân loại rác hữu cơ tại nguồn.",
                        "status": "contradicted"
                    }
                },
                {
                    "year": "2023",
                    "standard_id": "TT96-6.5.1",
                    "standard_name": "Tuân thủ môi trường tại mỏ khoáng sản",
                    "gri_equivalent": "GRI 2-27",
                    "claim_quote": "Đảm bảo tuân thủ tuyệt đối quy định xả thải tại Công ty Khai thác Mỏ Núi Pháo năm 2023.",
                    "claim_source": "Báo cáo Thường niên 2023, trang 61",
                    "verification": {
                        "verifier": "Thanh tra Bộ TN&MT (07/2023)",
                        "finding": "nhắc nhở và xử phạt vi phạm quy trình quản lý bụi và khu vực lưu chứa chất thải mỏ.",
                        "status": "contradicted"
                    }
                }
            ],
            "missing": [
                {
                    "year": "2024",
                    "standard_id": "TT96-6.4.1",
                    "standard_name": "Khai thác nước công nghiệp",
                    "gri_equivalent": "GRI 303-3",
                    "requirement": "Không công bố chi tiết khối lượng nước bề mặt và nước ngầm sử dụng tại các cơ sở chế biến thịt MEATDeli năm 2024.",
                    "note": "Lưu ý: Chế biến thực phẩm thuộc nhóm tiêu thụ nước quy mô lớn."
                },
                {
                    "year": "2023",
                    "standard_id": "GRI 306-3",
                    "standard_name": "Số lượng bao bì nhựa dùng 1 lần",
                    "gri_equivalent": "GRI 306-3",
                    "requirement": "Thiếu số liệu thống kê tổng khối lượng nhựa dùng 1 lần từ chuỗi siêu thị WinMart năm 2023.",
                    "note": "Lưu ý: Khai báo rác thải nhựa tiêu dùng là bắt buộc theo GRI 306."
                }
            ]
        },
        "social": {"verified": [], "contradicted": [], "missing": []},
        "governance": {"verified": [], "contradicted": [], "missing": []}
    }
}


def get_companies(query: str = "") -> List[Dict[str, Any]]:
    """Return list of supported companies, filtered by search query if provided."""
    if not query:
        return COMPANIES
    q = query.strip().lower()
    return [
        c for c in COMPANIES
        if q in c["ticker"].lower() or q in c["name"].lower() or q in c["short"].lower()
    ]


def get_evidence(ticker: str, selected_year: Optional[str] = None) -> Dict[str, Any]:
    """Return ESG evidence breakdown for a given ticker, with optional year filtering."""
    t = ticker.upper()
    comp = next((c for c in COMPANIES if c["ticker"] == t), None)
    if not comp:
        comp = {
            "ticker": t,
            "name": f"Công ty Cổ phần {t}",
            "short": t,
            "industry": "Chưa phân loại",
            "year_range": "2022 - 2024",
            "available_years": ["2022 - 2024", "2024", "2023", "2022"]
        }

    raw_data = EVIDENCE_DATASTORE.get(t, {
        "environment": {"verified": [], "contradicted": [], "missing": []},
        "social": {"verified": [], "contradicted": [], "missing": []},
        "governance": {"verified": [], "contradicted": [], "missing": []}
    })

    tabs_result = {}
    pillars = [
        ("environment", "Môi trường", "🌿"),
        ("social", "Xã hội", "👥"),
        ("governance", "Quản trị", "🏛")
    ]

    # Filter function for year
    def filter_by_year(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not selected_year or selected_year == comp.get("year_range") or " - " in selected_year:
            return items
        return [item for item in items if str(item.get("year")) == str(selected_year)]

    for p_key, p_label, p_icon in pillars:
        p_data = raw_data.get(p_key, {"verified": [], "contradicted": [], "missing": []})
        
        v_list = filter_by_year(p_data.get("verified", []))
        c_list = filter_by_year(p_data.get("contradicted", []))
        m_list = filter_by_year(p_data.get("missing", []))

        tabs_result[p_key] = {
            "label": p_label,
            "icon": p_icon,
            "verified": v_list,
            "contradicted": c_list,
            "missing": m_list,
            "counts": {
                "verified": len(v_list),
                "contradicted": len(c_list),
                "missing": len(m_list),
                "total": len(v_list) + len(c_list) + len(m_list)
            }
        }

    return {
        "company": comp,
        "selected_year": selected_year or comp.get("year_range"),
        "tabs": tabs_result
    }
