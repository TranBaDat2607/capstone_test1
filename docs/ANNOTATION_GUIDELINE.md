# Sổ tay gán nhãn — tính đúng của link `(claim, evidence)`

> **Trạng thái: CHUẨN THAO TÁC. Phiên bản v1.0 — FREEZE ngày `<điền khi commit>`.**
>
> **Quy tắc freeze:** một khi lượt gán nhãn đầu tiên đã bắt đầu, **không được sửa file này**.
> Muốn sửa ⇒ tăng lên v1.1, ghi vào §10, và **gán lại từ đầu**. Sửa guideline giữa chừng làm
> mọi con số so sánh trở nên vô nghĩa (`proposals/AGENT_AB_EVALUATION.md` §3.3).
>
> **Ai đọc file này:** người ngồi gán nhãn. File này **tự chứa** — bạn không cần biết gì về
> knowledge graph, Neo4j hay pipeline để làm được việc.
>
> **Vì sao lại gán nhãn này, và tại sao không gán nhãn khác:**
> [`LABELING_STRATEGY.md`](./LABELING_STRATEGY.md).

---

## 1. Việc bạn đang làm — và việc bạn KHÔNG làm

Bạn sẽ đọc **từng cặp hai đoạn text**:

- **CLAIM** — một câu công ty tự nói về mình trong báo cáo thường niên.
- **EVIDENCE** — một mẩu thông tin độc lập về công ty đó, thường lấy từ báo chí.

Và trả lời **đúng một câu hỏi**:

> **Mẩu bằng chứng này có nói về ĐÚNG cái mà claim khẳng định không — và nếu có, nó củng cố hay nghịch?**

| Bạn **đang** làm | Bạn **không** làm |
|---|---|
| Đánh giá **cái link** giữa hai đoạn text có đúng không | ❌ Đánh giá công ty có greenwashing không |
| Trả lời dựa trên **đúng hai đoạn text được đưa** | ❌ Tra Google, dùng kiến thức riêng về công ty |
| Gán nhãn cho **một cặp** | ❌ Kết luận gì về công ty, ngành, hay claim nói chung |

> ⚠️ **Nếu bạn thấy mình đang nghĩ "công ty này có vẻ gian dối" — bạn đang làm sai việc.**
> Câu hỏi duy nhất là: *bằng chứng này có nói đúng cái claim nói không?*

---

## 2. Ba nhãn

| Nhãn | Nghĩa | Dấu hiệu nhận biết |
|---|---|---|
| `supports` | Bằng chứng độc lập **củng cố** đúng điều claim khẳng định | Xác thực của bên thứ ba, chứng nhận, hoặc một chỉ số quan sát được **nhất quán** với claim |
| `contradicts` | Bằng chứng **nghịch** với đúng điều claim khẳng định, **trong cùng kỳ** | Án phạt, vi phạm, bê bối, hoặc một chỉ số bất lợi **cùng kỳ** và **cùng đại lượng** |
| `irrelevant` | Bằng chứng **không nói về cùng một thứ** | Khác chủ đề · khác đại lượng · khác chủ thể · khác kỳ · tin tài chính trung tính |

**`irrelevant` là nhãn phổ biến nhất và là nhãn mặc định.** Đừng ngại dùng nó. Phần lớn giá trị
của bộ nhãn này nằm ở việc bạn dám nói `irrelevant` ở chỗ máy nói `contradicts`.

---

## 3. ⭐ Cây quyết định — chạy theo đúng thứ tự

Chạy 4 bước. **Dừng ngay ở bước đầu tiên cho ra câu trả lời.** Không nhảy cóc.

```
        ┌─────────────────────────────────────────────┐
        │ Bước 1 — CÙNG CHỦ THỂ?                      │
        │ Evidence nói về chính công ty trong claim?   │
        │ (không phải toàn ngành, không phải cty khác)│
        └───────────────┬─────────────────────────────┘
                 KHÔNG  │  CÓ
             ┌──────────┘  └──────────┐
             ▼                        ▼
       ┌───────────┐   ┌─────────────────────────────────────┐
       │irrelevant │   │ Bước 2 — CÙNG ĐẠI LƯỢNG?            │
       └───────────┘   │ Evidence đo ĐÚNG THỨ claim khẳng    │
                       │ định? (không phải một chỉ số khác   │
                       │ nghe có vẻ liên quan)               │
                       └───────────────┬─────────────────────┘
                                KHÔNG  │  CÓ
                            ┌──────────┘  └──────────┐
                            ▼                        ▼
                      ┌───────────┐   ┌──────────────────────────────┐
                      │irrelevant │   │ Bước 3 — CÙNG KỲ?            │
                      └───────────┘   │ Evidence thuộc khoảng thời   │
                                      │ gian mà claim nói tới?       │
                                      └──────────────┬───────────────┘
                                               KHÔNG │  CÓ
                                           ┌─────────┘  └─────────┐
                                           ▼                      ▼
                                     ┌───────────┐   ┌────────────────────────┐
                                     │irrelevant │   │ Bước 4 — HƯỚNG         │
                                     └───────────┘   │ Củng cố → supports     │
                                                     │ Nghịch  → contradicts  │
                                                     └────────────────────────┘
```

### Diễn giải từng bước

**Bước 1 — Cùng chủ thể?**
Evidence phải nói về **chính pháp nhân** mà claim nói. Một con số của **toàn ngành**, của **đối thủ**,
hay của một công ty con **không liên quan đến điều claim nói**, đều trượt bước này.

**Bước 2 — Cùng đại lượng?** ← *bước bị bỏ sót nhiều nhất*
Hai con số cùng nói về "công ty" không có nghĩa chúng đo cùng một thứ. Hỏi thẳng:
*claim khẳng định đại lượng X; evidence có đo X không, hay đo một Y khác nghe na ná?*

**Bước 3 — Cùng kỳ?**
Claim nói về năm 2017 thì một con số của năm 2026 thường **không** bác bỏ được nó. Đặc biệt cẩn
thận với claim dạng *"cao nhất từ trước đến nay"* — nó nói về thời điểm phát biểu, không phải mãi mãi.

**Bước 4 — Hướng.**
Chỉ đến đây mới hỏi củng cố hay nghịch. Nếu đã qua 3 bước mà vẫn phân vân hướng ⇒ ghi `irrelevant`
và đánh dấu `difficulty=hard`.

---

## 4. Worked examples — lấy từ bộ 30 case đã gán

Đọc hết mục này trước khi gán case đầu tiên. Đây là phần quan trọng nhất của sổ tay.

### 4.1 `supports`

**Ví dụ A** (`S01`)

| | |
|---|---|
| **CLAIM** (2012) | *"Company implements monthly, quarterly, and annual bonus systems to motivate employees."* |
| **EVIDENCE** (2024) | *"Employee stock bonus payout for 2024 profits — Employee Stock Bonus 114.5 billion VND achieved"* |
| **Nhãn** | `supports` |
| **Vì sao** | B1 ✅ chính công ty · B2 ✅ cùng đại lượng (chi trả thưởng nhân viên ↔ hệ thống thưởng) · B3 ✅ claim là **chính sách thường trực**, không giới hạn một năm · B4 → củng cố. |

> 💡 Claim dạng **chính sách/thông lệ thường trực** ("thực hiện chế độ…", "duy trì chính sách…")
> có cửa sổ thời gian rộng — một quan sát ở năm sau vẫn hợp lệ ở bước 3.

**Ví dụ B** (`S03`)

| | |
|---|---|
| **CLAIM** (2016) | *"Resolution approving delisting on HNX and listing on HOSE"* |
| **EVIDENCE** (2016) | *"Listed on HOSE — listing status true, achieved"* |
| **Nhãn** | `supports` |
| **Vì sao** | Cả 3 bước ✅, cùng năm, đúng đại lượng. Đây là ca **dễ nhất** — nghị quyết được thực thi. |

### 4.2 `contradicts`

**Ví dụ C** (`C01` — worked example chuẩn của đề tài)

| | |
|---|---|
| **CLAIM** (2021) | *"Ensures growth in revenue and profit"* |
| **EVIDENCE** (2026) | *"Revenue decrease — Revenue −42.3 % achieved"* |
| **Nhãn** | `contradicts` |
| **Vì sao** | B1 ✅ · B2 ✅ **cùng đại lượng: doanh thu** · B3 ✅ claim *"ensures"* là cam kết thường trực · B4 → nghịch trực tiếp. |

**Ví dụ D** (`C06`)

| | |
|---|---|
| **CLAIM** (2019) | *"Earnings Per Share (EPS) expected to reach 2,550 VND in 2019"* |
| **EVIDENCE** (2026) | *"Earnings Per Share (last 4 quarters) — EPS 1213.0 VND/share achieved"* |
| **Nhãn** | `contradicts` |
| **Vì sao** | Cùng đại lượng EPS, quan sát thấp hơn xa mục tiêu ⇒ mục tiêu không đạt. |

### 4.3 ⭐ `irrelevant` — 5 ca KHÓ, nơi máy hay sai

Đây là phần có giá trị chẩn đoán cao nhất. Ở cả 5 ca dưới đây, **hệ thống nói `contradicts`,
người gán nói `irrelevant`**.

**Ví dụ E** (`IR01`) — **trượt bước 2: nhầm đại lượng**

| | |
|---|---|
| **CLAIM** (2012) | *"Uses recycled raw materials to ensure less waste."* |
| **EVIDENCE** (2025) | *"Dependency on imported raw materials — 80-85 % achieved"* |
| **Nhãn** | `irrelevant` |
| **Vì sao** | *Tỉ lệ nguyên liệu **nhập khẩu*** và *tỉ lệ nguyên liệu **tái chế*** là **hai đại lượng khác nhau**. Nguyên liệu nhập khẩu hoàn toàn có thể là nguyên liệu tái chế. Con số này **không đo** điều claim nói. |

**Ví dụ F** (`IR02`) — **trượt bước 2**

| | |
|---|---|
| **CLAIM** (2025) | *"Các BCTC… đã phản ánh trung thực và hợp lý… tình hình tài chính của Công ty tại ngày 31/12/2025"* |
| **EVIDENCE** (2026) | *"Total assets change from beginning of year — −11.5 % achieved"* |
| **Nhãn** | `irrelevant` |
| **Vì sao** | Claim nói về **tính trung thực của báo cáo tài chính**. Tài sản tăng hay giảm **không nói gì** về việc báo cáo có trung thực hay không — một báo cáo trung thực hoàn toàn có thể ghi nhận tài sản giảm. |

**Ví dụ G** (`IR03`) — **trượt bước 1: nhầm chủ thể**

| | |
|---|---|
| **CLAIM** (2022) | *"Plastic product export growth forecast at 22% in 2022"* (dự báo **của công ty**) |
| **EVIDENCE** (2024) | *"Vietnam plastic industry growth rate — 16-18 %/year achieved"* (**toàn ngành**) |
| **Nhãn** | `irrelevant` |
| **Vì sao** | Tăng trưởng **toàn ngành** không xác nhận cũng không bác bỏ dự báo **của riêng một công ty**. Công ty hoàn toàn có thể tăng 22% trong một ngành tăng 16%. |

**Ví dụ H** (`IR04`) — **trượt bước 3: lệch kỳ**

| | |
|---|---|
| **CLAIM** (2017) | *"2017 revenue and profit are the highest since establishment."* |
| **EVIDENCE** (2026) | *"Revenue decrease — Revenue −42.3 % achieved"* |
| **Nhãn** | `irrelevant` |
| **Vì sao** | Doanh thu giảm **năm 2026** không bác bỏ được rằng **năm 2017 là đỉnh tính đến thời điểm đó**. Hai mệnh đề cùng đúng được. |

**Ví dụ I** (`IR05`) — **phủ định kép**

| | |
|---|---|
| **CLAIM** (2021) | *"Company's strategy **not aligned** with market trends… regarding green consumption and potential shift away from plastic packaging."* |
| **EVIDENCE** (2025) | *"Total capacity of 07 plastic packaging factories — 108000 tons/year achieved"* |
| **Nhãn** | `irrelevant` |
| **Vì sao** | Claim là **một dòng trong sổ đăng ký rủi ro** — công ty đang **tự nêu rủi ro của mình**, không phải đang khoe. Với claim phủ định, hướng của `supports`/`contradicts` bị đảo và rất dễ gán sai ⇒ mặc định `irrelevant`. |

### 4.4 `irrelevant` — ca dễ (chủ đề khác hẳn)

**Ví dụ J** (`IR06`)

| | |
|---|---|
| **CLAIM** (2012) | *"Company implements monthly, quarterly, and annual bonus systems…"* (Xã hội) |
| **EVIDENCE** (2025) | *"Number of countries with business relationships — 50 countries achieved"* |
| **Nhãn** | `irrelevant` |
| **Vì sao** | Thưởng nhân viên vs độ phủ địa lý — hai chủ đề không liên quan. Trượt bước 2 ngay lập tức. |

---

## 5. Sáu quy tắc phụ bắt buộc

| # | Quy tắc | Vì sao |
|---|---|---|
| **R1** | **Nghi ngờ → `irrelevant`** | Khớp với chỉ dẫn của hệ thống: *"Do not guess."* Mặc định thận trọng, không mặc định gán ghép |
| **R2** | **Chỉ dùng hai đoạn text được đưa.** Không tra Google, không dùng kiến thức riêng | Hệ thống bị ràng buộc *"using ONLY the two texts"*. Nếu bạn biết nhiều hơn nó, bạn đang đo *"người hiểu biết hơn máy"*, không phải *"máy sai"* |
| **R3** | **Claim phủ định / mục rủi ro → mặc định `irrelevant`** trừ khi cực rõ | Xem Ví dụ I. Phủ định kép làm hướng đảo, tỉ lệ gán sai rất cao |
| **R4** | **Tin PR của chính công ty vẫn gán bình thường theo nội dung** | Việc chặn "tự khen tự xác thực" là của hệ thống (self-verification guard), không phải của bạn. Trộn vào là đo lẫn hai thứ |
| **R5** | **Không nhìn nhãn cũ, không nhìn verdict của máy** | File đề bài đã được làm mù. Nếu bạn vô tình thấy đáp án ở đâu đó, **bỏ case đó ra** và ghi vào `note` |
| **R6** | **Không sửa nhãn đã gán ở lượt trước** | Lượt 2 phải độc lập với lượt 1, nếu không κ tự-đồng-ý là số giả |

### 5.1 Bảng bỏ túi — dán cạnh màn hình

```
┌──────────────────────────────────────────────────────┐
│  1. Cùng CÔNG TY?     không → irrelevant             │
│  2. Cùng ĐẠI LƯỢNG?   không → irrelevant   ← hay sót │
│  3. Cùng KỲ?          không → irrelevant             │
│  4. Hướng:  củng cố → supports │ nghịch → contradicts│
│                                                      │
│  Phân vân?           → irrelevant + difficulty=hard  │
│  Claim phủ định?     → irrelevant                    │
│  Chỉ đọc 2 đoạn text. Không tra cứu thêm.            │
└──────────────────────────────────────────────────────┘
```

---

## 6. Quy trình gán

### 6.1 Chuẩn bị

| Bước | Việc |
|---|---|
| 1 | Nhận `config/evaluation/gold_links_aaa_items.jsonl` — **đề bài đã làm mù**, không chứa nhãn nào |
| 2 | Đọc hết §1–§5 của sổ tay này. Đọc kỹ §4 |
| 3 | Gán thử 10 case đầu, đối chiếu lại §4, chỉnh cách hiểu **rồi mới gán tiếp** — 10 case này **gán lại** khi vào lượt chính |
| 4 | Ghi tên bạn (`annotator`) và ngày bắt đầu |

### 6.2 Lượt 1 → nghỉ → lượt 2 (bắt buộc)

```
Lượt 1 (p1)  →  NGHỈ ≥ 3 NGÀY  →  Lượt 2 (p2, đề đã xáo thứ tự)  →  tính κ tự-đồng-ý
```

- **Nghỉ ≥3 ngày là bắt buộc.** Gán lại ngay trong ngày chỉ đo trí nhớ ngắn hạn, không đo tính
  nhất quán của guideline.
- **Đề lượt 2 phải được xáo thứ tự** so với lượt 1 (chống nhớ theo vị trí).
- **Không xem lại file lượt 1** trong khi gán lượt 2 (R6).

**Đọc kết quả κ tự-đồng-ý:**

| κ | Ý nghĩa | Hành động |
|---|---|---|
| ≥ 0,80 | Rất nhất quán | ✅ Đi tiếp |
| 0,60 – 0,79 | Nhất quán khá | ✅ Đi tiếp, ghi rõ κ trong báo cáo |
| < 0,60 | **Guideline chưa đủ chặt** | ⛔ Dừng. Xem các case lệch, bổ sung quy tắc vào §5, **tăng phiên bản sổ tay**, gán lại từ đầu |

> Mỏ neo kỳ vọng: trên nhiệm vụ tương tự (CLIMATE-FEVER), κ **giữa hai người** chỉ đạt **0,684**.
> Đừng hoảng nếu κ của bạn không phải 0,95 — hãy báo cáo trung thực con số thật.

### 6.3 Annotator thứ hai (rất nên có)

Mượn **một người khác** gán **60 case** lấy ngẫu nhiên từ cùng bộ đề mù.

- Không cần là chuyên gia ESG. Sổ tay này đủ để một sinh viên cùng ngành gán được.
- Người đó chỉ đọc sổ tay này, **không** đọc `LABELING_STRATEGY.md`, **không** biết kết quả của máy.
- Kết quả: **κ người–người** — đây là con số trả lời trực diện chất vấn *"tác giả tự gán thì
  khách quan chỗ nào"*.

### 6.4 Adjudication

Với mọi case mà **lượt 1 ≠ lượt 2** hoặc **bạn ≠ annotator 2**:

1. Mở lại cặp text, chạy lại cây quyết định §3 một cách chậm rãi.
2. Chốt `label_final`.
3. **Bắt buộc ghi `note`**: lý do, và bước nào của cây quyết định gây tranh cãi.
4. Đặt `difficulty = "hard"`.

> Tập bất đồng chính là phần thú vị nhất để viết vào báo cáo — nó chỉ ra **guideline mơ hồ ở đâu**
> và **hệ thống hay sai ở đâu**. Đừng giấu nó, hãy phân tích nó.

---

## 7. Định dạng file

### 7.1 `gold_links_aaa_items.jsonl` — đề bài (KHÔNG chứa nhãn)

```json
{"id": "GL0001", "claim_id": "AAA_SC_001", "claim_year": 2021, "claim_text": "Ensures growth in revenue and profit", "evidence_key": "sha1:3f9a2c81", "evidence_class": "KPIObservation", "evidence_year": 2026, "evidence_text": "Revenue decrease Revenue -42.3 % achieved", "evidence_meta": "KPIObservation from news, year 2026", "esg_category": "Governance"}
```

| Trường | Nghĩa |
|---|---|
| `id` | Mã case, duy nhất, `GL####` |
| `claim_id` | Khoá nối về dossier — **không dùng `claim_node_index`** (đã lệch, xem `proposals/EVALUATION_WITHOUT_LABELS.md` §9.1) |
| `evidence_key` | Khoá định danh bằng chứng = 8 ký tự đầu của `sha1(evidence_text)`. Dùng để chống gán trùng. **Không dùng `node_index`** — nó là chỉ số mảng, lệch theo phiên bản đồ thị đúng như `claim_node_index` |
| `claim_year` / `evidence_year` | Năm, dùng cho **bước 3** của cây quyết định |
| `evidence_class` | Loại node bằng chứng (`KPIObservation`, `MediaReport`, …) |
| `esg_category` | Trụ E/S/G — **chỉ để tham khảo**, không quyết định nhãn |

> ⚠️ File này **tuyệt đối không** được chứa: `verdict`, `confidence`, `rationale`, `note`,
> `reference_verdict`, hay bất kỳ trường `label*` nào. `test/test_gold_links.py` kiểm điều này.

### 7.2 `gold_links_aaa_labels_<annotator>_p<N>.jsonl` — đáp án

```json
{"id": "GL0001", "label": "contradicts", "difficulty": "easy", "note": "", "annotator": "ducntm", "pass": 1, "labeled_at": "2026-08-04"}
```

| Trường | Giá trị |
|---|---|
| `label` | `supports` \| `contradicts` \| `irrelevant` |
| `difficulty` | `easy` \| `medium` \| `hard` — đánh dấu `hard` cho mọi case bạn phân vân |
| `note` | Bắt buộc khi `difficulty=hard`; ghi **bước nào** của cây quyết định gây khó |

### 7.3 `gold_links_aaa_final.jsonl` — bộ chốt

```json
{"id": "GL0001", "label_pass1": "contradicts", "label_pass2": "contradicts", "label_annotator2": "contradicts", "label_final": "contradicts", "difficulty": "easy", "note": "", "adjudicated": false, "data_revision": "<hash trong data_version.json>"}
```

Trường `data_revision` bắt buộc: bộ nhãn gắn với **một snapshot dữ liệu cụ thể**. Bỏ trống là
cách bộ nhãn trở nên mồ côi — đã xảy ra một lần với `ablation_cases.json`
([`LABELING_STRATEGY.md`](./LABELING_STRATEGY.md) §3.1).

---

## 8. Tính κ (Cohen's kappa) — script thuần Python, không cần cài gì

Chạy được ngay bằng thư viện chuẩn, **không thêm dependency nào vào repo**. Đặt ở thư mục tạm
ngoài các package code (quy tắc layout của `CLAUDE.md`), hoặc gộp thành một hàm trong
`test/test_gold_links.py`.

```python
"""Cohen's kappa giữa hai lượt/hai người gán. Chạy: python kappa.py a.jsonl b.jsonl"""
import json, sys
from collections import Counter

def load(path):
    with open(path, encoding="utf-8") as f:
        return {json.loads(l)["id"]: json.loads(l)["label"] for l in f if l.strip()}

a, b = load(sys.argv[1]), load(sys.argv[2])
ids = sorted(set(a) & set(b))
assert ids, "Hai file không có id chung"
print(f"n chung = {len(ids)}  (a={len(a)}, b={len(b)})")

n = len(ids)
agree = sum(1 for i in ids if a[i] == b[i])
po = agree / n

ca, cb = Counter(a[i] for i in ids), Counter(b[i] for i in ids)
pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))

kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
print(f"đồng ý thô  po = {po:.3f}  ({agree}/{n})")
print(f"kỳ vọng     pe = {pe:.3f}")
print(f"Cohen kappa    = {kappa:.3f}")

print("\nCác case lệch (đem đi adjudication):")
for i in ids:
    if a[i] != b[i]:
        print(f"  {i}: {a[i]:<12} vs {b[i]}")
```

**Thang đọc κ (Landis & Koch):**

| κ | Diễn giải |
|---|---|
| < 0,20 | Rất kém |
| 0,21 – 0,40 | Kém |
| 0,41 – 0,60 | Trung bình |
| 0,61 – 0,80 | **Tốt** ← vùng thực tế cho nhiệm vụ này |
| 0,81 – 1,00 | Rất tốt |

---

## 9. Checklist trước khi nộp bộ nhãn

- [ ] Sổ tay này đã **freeze và commit trước** khi gán case đầu tiên
- [ ] File `_items.jsonl` **không chứa** trường nhãn nào (`test/test_gold_links.py` xanh)
- [ ] Đã gán đủ **2 lượt**, cách nhau **≥3 ngày**, đề lượt 2 **đã xáo thứ tự**
- [ ] κ tự-đồng-ý đã tính và **≥ 0,60** (nếu thấp hơn: đã sửa guideline, tăng version, gán lại)
- [ ] Annotator thứ 2 đã gán ≥60 case, κ người–người đã tính
- [ ] Mọi case bất đồng đã adjudication, có `note` và `difficulty=hard`
- [ ] `data_revision` đã điền vào file final
- [ ] Mọi case `difficulty=hard` có `note` không rỗng
- [ ] Phân bố lớp: không lớp nào dưới 10% mẫu
- [ ] Đã commit cả `_items`, `_p1`, `_p2`, `_final` và script tính κ

---

## 10. Nhật ký phiên bản

| Version | Ngày | Thay đổi | Hệ quả |
|---|---|---|---|
| v1.0 | `<điền khi commit>` | Bản đầu. Cây quyết định 4 bước + 6 quy tắc phụ, kế thừa `label_policy` của `config/evaluation/ablation_cases.json` và `ADJUDICATE_SYSTEM` của `claims_vs_conduct.py:156–171` | — |

> **Mọi thay đổi từ v1.1 trở đi bắt buộc gán lại từ đầu.** Ghi rõ vì sao đổi, và **không bao giờ**
> đổi sau khi đã nhìn thấy kết quả của hệ thống — đó là p-hacking (`proposals/AGENT_AB_EVALUATION.md` §3.3).

---

## 11. Câu hỏi thường gặp

**H: Claim và evidence đều nói về doanh thu, nhưng một cái là doanh thu quý, một cái là doanh thu năm?**
Đ: Trượt **bước 2** (khác đại lượng) ⇒ `irrelevant`, `difficulty=hard`, ghi rõ vào `note`.

**H: Evidence rõ ràng liên quan nhưng quá mơ hồ để nói củng cố hay nghịch?**
Đ: `irrelevant` + `difficulty=hard`. Đừng đoán (R1).

**H: Claim viết tiếng Việt, evidence tiếng Anh (hoặc ngược lại)?**
Đ: Bình thường, gán như thường. Ngôn ngữ không ảnh hưởng đến nhãn.

**H: Evidence là bài PR của chính công ty, tự khen mình?**
Đ: Vẫn gán theo nội dung (R4). Việc xử lý tính độc lập là của hệ thống, không phải của bạn.

**H: Tôi thấy claim này rõ ràng là nói phóng đại / greenwashing?**
Đ: **Không liên quan đến việc bạn đang làm.** Bạn chỉ trả lời: bằng chứng này có nói đúng cái
claim nói không (§1).

**H: Evidence có năm sau claim rất xa (vd. claim 2012, evidence 2026)?**
Đ: Phụ thuộc **loại claim**. Claim về **chính sách thường trực** ("duy trì chế độ…") → cửa sổ rộng,
vẫn có thể `supports` (Ví dụ A). Claim về **một sự kiện/một kỳ cụ thể** ("2017 là năm cao nhất")
→ cửa sổ hẹp, thường `irrelevant` (Ví dụ H).

**H: Hai cặp gần như giống hệt nhau, tôi có được copy nhãn không?**
Đ: Có, nếu chúng thật sự giống. Nhưng đọc lại evidence — khác biệt nhỏ về **năm** hoặc **đơn vị**
có thể lật nhãn.

---

## 12. Tham chiếu

- [`LABELING_STRATEGY.md`](./LABELING_STRATEGY.md) — vì sao gán nhãn này, thiết kế lấy mẫu, cỡ mẫu, phát biểu được gì
- `config/evaluation/ablation_cases.json` — 30 case tiền lệ; nguồn của mọi worked example ở §4
- `src/esg_kg/crosscheck/claims_vs_conduct.py:156–171` — `ADJUDICATE_SYSTEM`, định nghĩa nhãn mà **máy** dùng (guideline này bám sát nó có chủ đích)
- [`proposals/EVALUATION_WITHOUT_LABELS.md`](./proposals/EVALUATION_WITHOUT_LABELS.md) §9.1 — vì sao nối bằng `claim_id`, không bao giờ bằng `claim_node_index`
- Diggelmann et al. (2020), *CLIMATE-FEVER* — [arxiv.org/pdf/2012.00614](https://arxiv.org/pdf/2012.00614) — nhiệm vụ tương tự, κ người–người 0,684
- Stammbach et al. (2023), *Environmental Claim Detection*, ACL — [aclanthology.org/2023.acl-short.91](https://aclanthology.org/2023.acl-short.91/) — khuôn mẫu guideline + adjudication
