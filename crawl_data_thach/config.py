# -*- coding: utf-8 -*-
"""
Cấu hình danh sách công ty và từ khóa ESG cho News Crawler.
"""

# ============================================================
# DANH SÁCH CÔNG TY (CHỈ CÁC CÔNG TY ĐƯỢC YÊU CẦU)
# ============================================================
COMPANIES = [
    # --- Nhựa / Sản xuất ---
    "CTCP Nhựa An Phát Xanh",
    "CTCP Tập đoàn An Phát Holdings",
    "CTCP Nhựa Bình Minh",
    "CTCP Sản xuất và Công nghệ Nhựa Pha Lê",
    "CTCP Nhựa Tân Đại Hưng",
    "CTCP An Tiến Industries",
    "CTCP Vật tư - Xăng Dầu",

    # --- Bất động sản / Xây dựng ---
    "CTCP Đầu tư và Xây dựng Bình Dương ACC",
    "CTCP Gỗ An Cường",
    "CTCP Sơn Á Đông",
    "CTCP Đầu tư và Phát triển Bất động sản An Gia",
    "CTCP Xây dựng và Giao thông Bình Dương",
    "Tập đoàn Đầu tư và Phát triển Công nghiệp Becamex - CTCP",
    "CTCP Nhiệt điện Bà Rịa",
    "CTCP Đầu tư và Xây dựng 3-2",
    "CTCP Xây dựng 47",
    "CTCP Xây dựng CDC",
    "CTCP Đầu tư Phát triển Công nghiệp Thương mại Củ Chi",
    "CTCP Đầu tư và Phát triển Đô thị Dầu khí Cửu Long",
    "CTCP Chương Dương",
    "CTCP Đầu tư Hạ tầng Kỹ thuật Thành phố Hồ Chí Minh",
    "CTCP Tập đoàn CIC",
    "CTCP Bất động sản Thế Kỷ",
    "CTCP Tập đoàn Bất động sản CRV",
    "CTCP Công nghiệp Cao su Miền Nam",
    "CTCP Xây dựng Coteccons",
    "CTCP Đầu tư Phát triển Cường Thuận IDICO",
    "Tổng Công ty cổ phần Công trình Viettel",
    "CTCP Phát triển Đô thị Công nghiệp số 2",
    "CTCP DICERA Holdings",
    "CTCP Hóa An",
    "Tổng Công ty cổ phần Đầu tư Phát triển Xây dựng",
    "CTCP DRH Holdings",
    "CTCP Đệ Tam",
    "CTCP Kỹ nghệ Đô Thành",
    "CTCP Dịch vụ Bất động sản Đất Xanh",
    "CTCP Tập đoàn EverLand",
    "CTCP Bê tông Phan Vũ Hà Nam",
    "CTCP FECON",
    "CTCP Địa ốc First Real",
    "CTCP Chế biến gỗ Thuận An",
    "CTCP Đầu tư Thương mại Bất động sản An Dương Thảo Điền",
    "CTCP Phát triển Nhà Bà Rịa - Vũng Tàu",
    "CTCP Tập đoàn Hà Đô",
    "CTCP Halcom Việt Nam",
    "CTCP Xi Măng Vicem Hà Tiên",
    "CTCP Đầu tư Phát triển Hạ tầng IDICO",
    "CTCP Hưng Thịnh Incons",
    "CTCP Đầu tư và Xây dựng HUD1",
    "CTCP Xây lắp Thừa Thiên Huế",
    "CTCP Phát triển Hạ tầng Kỹ thuật",
    "CTCP Đầu tư và Kinh doanh Nhà",
    "Tổng Công ty Phát triển Đô thị Kinh Bắc - CTCP",
    "CTCP Đầu tư và Kinh doanh Nhà Khang Điền",
    "CTCP Tập đoàn Khải Hoàn Land",
    "CTCP KOSY",
    "CTCP Khoáng sản và Xây dựng Bình Dương",
    "CTCP Lilama 10",
    "CTCP Khoáng sản và Vật liệu Xây dựng Lâm Đồng",
    "CTCP Lizen",
    "CTCP Đầu tư LDG",
    "CTCP Đầu tư Cầu đường CII",
    "CTCP Đầu tư và Phát triển Đô thị Long Giang",
    "CTCP Long Hậu",
    "CTCP Lilama 18",
    "CTCP Miền Đông",
    "CTCP Đầu tư Năm Bảy Bảy",
    "CTCP Đầu tư Nam Long",
    "CTCP Phát triển Đô thị Từ Liêm",
    "CTCP Tập đoàn Đầu tư Địa ốc No Va",
    "CTCP Bất động sản Du lịch Ninh Vân Bay",
    "CTCP Tập Đoàn PC1",
    "CTCP Phát triển Bất động sản Phát Đạt",
    "CTCP Xây dựng Phục Hưng Holdings",
    "CTCP Victory Group",
    "CTCP Quốc Cường Gia Lai",
    "CTCP Xây dựng Số 5",
    "CTCP Địa ốc Sài Gòn Thương Tín",
    "CTCP Tổng CTCP Địa ốc Sài Gòn",
    "CTCP Quốc tế Sơn Hà",
    "CTCP SJ Group",
    "CTCP SEAREFICO",
    "CTCP Sonadezi Châu Đức",
    "CTCP Sonadezi Long Thành",
    "CTCP Đầu tư Bất động sản Taseco",
    "CTCP Tập đoàn Xây dựng TRACODI",
    "CTCP Phát triển Nhà Thủ Đức",
    "CTCP Đầu tư và Xây dựng Tiền Giang",
    "CTCP Tập đoàn Kỹ nghệ gỗ Trường Thành",
    "CTCP Tư vấn Xây dựng Điện 2",
    "CTCP Đầu tư Phát triển Nhà và Đô thị IDICO",
    "Tổng Công ty cổ phần Xuất nhập khẩu và Xây dựng Việt Nam",
    "Tổng Công ty Viglacera - CTCP",
    "CTCP Vinhomes",
    "Tổng Công ty cổ phần Xây dựng Điện Việt Nam",
    "CTCP Vạn Phát Hưng",
    "CTCP Phát triển Bất động sản Văn Phú",
    "CTCP Vincom Retail",
    "CTCP Đầu tư Hải Phát",
    "CTCP Tư vấn Thương mại Dịch vụ Địa Ốc Hoàng Quân",

    # --- Thép / Kim khí ---
    "CTCP Kim khí Thành phố Hồ Chí Minh - VNSTEEL",
    "CTCP Tập đoàn Hòa Phát",
    "CTCP Tập đoàn Hoa Sen",
    "CTCP Thép Nam Kim",
    "CTCP Thép VICASA",

    # --- Cao su ---
    "CTCP Cao su Bến Thành",
    "Tập đoàn Công nghiệp Cao su Việt Nam - CTCP",

    # --- Năng lượng / Điện ---
    "CTCP Trường Thành Energy Group",
    "CTCP Cơ Điện Lạnh",

    # --- Tập đoàn / Đa ngành ---
    "CTCP Tập đoàn Sao Mai",
    "CTCP Tập đoàn F.I.T",
    "CTCP Tập đoàn Đại Dương",
    "CTCP SAM Holdings",
    "CTCP Janus Group",

    # --- Tập đoàn lớn ---
    "Tập đoàn VINGROUP - CTCP",
]

# ============================================================
# DANH SÁCH TỪ KHÓA ESG
# Dùng để lọc nội dung bài báo (content filtering)
# ============================================================
KEYWORDS = [
    # --- Từ khóa mạnh (match 1 là đủ để coi bài báo liên quan ESG) ---
    "ESG",
    "NetZero",
    "Net Zero",
    "Zero Carbon",
    "phát triển bền vững",
    "báo cáo bền vững",
    # --- Từ khóa thường (cần match >= 2 để giảm false positive) ---
    "CO2e",
    "dự án xanh",
    "năng lượng tái tạo",
    "năng lượng sạch",
    "biến đổi khí hậu",
    "rủi ro khí hậu",
    "tác động môi trường",
    "bảo vệ môi trường",
    "tín dụng xanh",
    "giảm phát thải",
    "phát thải cacbon",
    "trung hòa cacbon",
    "hiệu ứng nhà kính",
    "công nghệ xanh",
    "chuyển đổi xanh",
    "kinh tế tuần hoàn",
    "trách nhiệm xã hội",
    "quản trị rủi ro",
    "tiêu chuẩn xanh",
]

# Từ khóa mạnh — match 1 từ khóa là đủ (dùng trong crawler để phân biệt)
STRONG_KEYWORDS = {
    "esg", "netzero", "net zero", "zero carbon",
    "phát triển bền vững", "báo cáo bền vững",
}

# ============================================================
# NHÓM TỪ KHÓA ĐỂ TÌM KIẾM (gom nhóm để tối ưu số lượng query)
# Mỗi nhóm tạo 1 search query cho mỗi công ty
# Giảm từ 8 -> 4 nhóm để giảm ~50% lượng request
# ============================================================
KEYWORD_GROUPS = [
    ["ESG", "phát triển bền vững", "báo cáo bền vững"],
    ["NetZero", "Net Zero", "giảm phát thải", "trung hòa cacbon"],
    ["năng lượng tái tạo", "tín dụng xanh", "chuyển đổi xanh"],
    ["biến đổi khí hậu", "phát thải cacbon", "kinh tế tuần hoàn"],
]
