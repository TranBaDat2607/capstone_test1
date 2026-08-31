# Đo cải thiện khi thêm Agent, không có nhãn chuẩn — giao thức so sánh cặp (paired A/B)

> **Trạng thái: ĐỀ XUẤT, chưa triển khai.** Không có dòng code nào trong repo hiện thực
> các phép đo dưới đây. Đọc như một *giao thức thí nghiệm*, không phải mô tả code đang chạy.
>
> **Quan hệ với [`EVALUATION_WITHOUT_LABELS.md`](EVALUATION_WITHOUT_LABELS.md) (28/07):** file đó
> thiết kế đánh giá **tuyệt đối** một hệ thống ("hệ hiện tại có hơn ngẫu nhiên không"). File này
> giải bài toán **so sánh hai hệ** ("thêm agent vào thì hơn ở đâu, hơn bao nhiêu, có ý nghĩa
> thống kê không"). Hai bài toán khác nhau về bản chất, và bài toán so sánh **dễ hơn** — §1.
> File này **tái dùng** chứ không thay thế: MR suite (§3), negative control (§4), Krippendorff α
> (§5) của file cũ trở thành *đầu vào* cho các phép đo Δ ở đây.
>
> **Đọc trước:** [`SYSTEM_DESIGN.md`](../SYSTEM_DESIGN.md) §1.1 (ràng buộc không-ground-truth) ·
> [`TEMPORAL_KG_DESIGN.md`](../TEMPORAL_KG_DESIGN.md) §4 (Q1–Q8, đã cài đặt trong `run.py quality`) ·
> [`CROSSCHECK_EXPANSION.md`](CROSSCHECK_EXPANSION.md) (chẩn đoán D1–D6 — chính là thứ agent
> được kỳ vọng sửa, nên cũng là nơi metric phải nhìn vào)

---

## 0. Tóm tắt cho người bận rộn

| Câu hỏi | Trả lời ngắn |
|---|---|
| Không nhãn thì so sánh A/B được không? | **Được, và dễ hơn đo tuyệt đối.** Bạn không cần biết đáp án đúng để biết B **khác** A theo hướng nào — §1. |
| Metric chính (primary endpoint) là gì? | **Δ tỉ lệ vi phạm metamorphic (paired, kiểm định McNemar)** — §5. Đây là thứ duy nhất có nhãn đúng/sai **máy sinh được**, nên nó là thứ gần "accuracy" nhất mà không cần một người gán nhãn nào. |
| Vì sao không được báo cáo nó một mình? | Vì **bẫy nới lỏng** (§2): agent nào cũng "cải thiện" được bằng cách dễ dãi hơn. Bắt buộc kèm **guard: Δ specificity trên negative control**. Một con số không có guard là con số không phòng thủ được. |
| Metric rẻ nhất chạy được ngay? | `run.py quality --label before/after` — **Q1–Q8 đã cài đặt sẵn, 0đ, offline**, và được thiết kế đúng cho mục đích before/after này. Áp thẳng cho agent ở step02/step05. |
| Chặn cứng cần biết trước | Muốn thống kê **paired** thì phải **ghép được item giữa 2 lần chạy**. Nếu agent ở step02/05 (rebuild đồ thị) thì `claim_id` đổi ⇒ ghép gãy. Cách vá: ghép bằng bộ ba provenance `(source_pdf, page, sentence_index)` — §6. |
| Cái gì tuyệt đối không được làm | Trộn **hard-failure rate** của agent (loop, timeout, tool call hỏng) vào metric chất lượng — §10. Đó là cách một agent tệ trông như một agent tốt. |
| Chi phí tối thiểu để có kết luận phòng thủ được | **~570 lệnh gọi LLM** cho mỗi arm ở step07 (§12, mục 1–3). Bằng ~16% một lần chạy step07 gốc. |

---

## 1. Nguyên lý: vì sao so sánh cặp thoát được ràng buộc không-nhãn

Đo tuyệt đối cần oracle: để nói *"hệ đúng 85%"* bạn phải biết đáp án đúng. Không có nhãn ⇒
không có câu đó. `EVALUATION_WITHOUT_LABELS.md` §1.2 đã chốt điều này và nó vẫn đúng.

Nhưng câu hỏi ở đây khác:

> Không phải *"B đúng bao nhiêu?"* mà là *"B khác A theo hướng nào?"*

Ba lý do khiến câu sau trả lời được mà câu trước thì không:

1. **Nhiễu chung bị triệt tiêu.** A và B chạy trên **cùng** corpus, cùng đồ thị, cùng prompt
   nền. Mọi thứ sai chung — extraction kém, news mỏng, tiếng Việt khó — xuất hiện ở cả hai vế
   và **trừ đi mất** khi lấy hiệu. Đây chính là lý do thiết kế paired mạnh hơn thiết kế
   độc lập: phương sai giữa các item (rất lớn ở đây) không đi vào sai số của Δ.
2. **Có những "nhãn" máy sinh được.** Bạn không biết claim nào là greenwashing, nhưng bạn
   biết chắc: *nếu phủ định claim thì verdict `supports` phải đổi*. Vi phạm quy tắc đó là
   **sai một cách khách quan**, không cần người phán. Nhãn đó tự động ⇒ mọi công cụ thống kê
   paired (McNemar, paired bootstrap) dùng được **bình thường**, không phải mẹo — §5.
3. **Ưu tiên tương đối rẻ hơn phán xét tuyệt đối.** Hỏi một judge *"cái nào tốt hơn"* dễ và
   ổn định hơn nhiều so với *"cái này đúng hay sai"*, và chỉ cần hỏi trên **tập bất đồng**
   (A ≠ B), thường là 5–20% số item ⇒ chi phí giảm một bậc — §7.

**Ranh giới vẫn còn nguyên:** so sánh cặp cho biết B **hơn** A, không cho biết B **đúng**.
Cả hai có thể cùng sai. Phải nói ra câu này khi bảo vệ — §13.

---

## 2. ⭐ Cạm bẫy trung tâm: bẫy nới lỏng (leniency trap) — và luật hai trục

Đây là nội dung quan trọng nhất của tài liệu. Nếu chỉ đọc một mục, đọc mục này.

**Vấn đề.** Hầu hết cách một agent "cải thiện" hệ này là **trả về nhiều hơn**: retrieval
multi-hop kéo thêm ứng viên, agent chịu khó tìm nên nhiều claim có bằng chứng hơn, tỉ lệ
`unverified_insufficient_evidence` (hiện 91,6%) tụt xuống. Nhìn qua thì đó là cải thiện lớn.

Nhưng **không có nhãn thì hai giả thuyết sau cho ra cùng một con số**:

- H₁ — agent tìm được bằng chứng **thật** mà token-overlap bỏ sót ⇒ cải thiện thật.
- H₀ — agent chỉ **dễ dãi hơn**, gán `supports/contradicts` cho những cặp lẽ ra `irrelevant`
  ⇒ không cải thiện gì, chỉ tăng dương tính giả.

Mọi metric coverage / recall / yield / "số claim được giải quyết" **đều không phân biệt được
H₀ với H₁**. Báo cáo chúng một mình là mời hội đồng bắt lỗi đúng chỗ.

**Luật hai trục — quy tắc bắt buộc của toàn bộ tài liệu này:**

> **Mọi metric đo *nhiều hơn* phải đi kèm một metric đo *có bịa không*, đo trên cùng một lần chạy.**
> Kết quả báo cáo dưới dạng một điểm trên mặt phẳng 2 trục, không bao giờ là một con số.

| Trục | Đo cái gì | Metric đại diện |
|---|---|---|
| **Trục X — Năng suất** | Hệ giải quyết được nhiều hơn bao nhiêu | Δ coverage (claim có ≥1 bằng chứng), Δ yield, Δ số cạnh advisory |
| **Trục Y — Kỷ luật** | Hệ có bịa thêm không | **Δ specificity trên negative control** (§6), Δ MR violation (§5), Δ citation validity (§4) |

Đọc kết quả:

```
        Δ Kỷ luật (Y)
             ▲
   ⚠ chặt hơn│ ✅ CẢI THIỆN THẬT
   nhưng hẹp │    (hiếm, nhưng là thứ cần chứng minh)
   ──────────┼──────────────────► Δ Năng suất (X)
   ❌ tệ hơn │ ⚠ BẪY NỚI LỎNG
   ở cả hai  │   (nhiều hơn nhưng bẩn hơn — KHÔNG được
             │    gọi là cải thiện nếu không định lượng đánh đổi)
```

Chỉ góc phần tư (+X, +Y) và (+X, ≈0 Y) mới được phát biểu là *"agent cải thiện hệ thống"*.
Góc (+X, −Y) vẫn báo cáo được, nhưng phải phát biểu là **đánh đổi**, kèm con số đánh đổi:
*"agent tăng coverage 8,4% → 21%, đổi lại specificity trên cặp ngẫu nhiên giảm từ 97% xuống 89%."*
Câu đó trung thực và vẫn là một đóng góp; câu *"agent cải thiện coverage 2,5 lần"* thì không.

---

## 3. Giao thức thí nghiệm — kiểm soát nhiễu trước khi đo

Sai ở mục này thì mọi con số phía sau vô nghĩa, dù thống kê có đẹp đến đâu.

### 3.1 Bất biến bắt buộc giữa hai arm

| Phải giữ y hệt | Vì sao |
|---|---|
| **Snapshot dữ liệu** — cùng revision ghim trong `data_version.json` | Đây đúng là mục đích file đó tồn tại (CLAUDE.md: *"a checkout recovers the data that went with that code, which is what makes the baseline vs after comparison reproducible"*). Ghi revision hash vào báo cáo. |
| **Model nền và `temperature=0`** | Đổi từ `gpt-4o-mini` sang model mạnh hơn *cùng lúc* với thêm agent ⇒ không tách được đóng góp. Nếu muốn nâng model, đó là arm thứ ba. |
| **Prompt của phần dùng chung** — `ADJUDICATE_SYSTEM` nguyên văn | `test/test_esg_kg_llm.py` đã ghim hình dạng request này. Sửa prompt là đo hệ khác (`EVALUATION_WITHOUT_LABELS.md` §9.4). |
| **Tập claim đầu vào** | Nếu agent làm giảm số claim đầu vào thì Δ coverage tính trên hai mẫu số khác nhau — vô nghĩa. |

### 3.2 ⭐ Thiết kế 3 arm — tách đóng góp của retrieval khỏi adjudication

Nếu agent thay **cả** retrieval **lẫn** adjudication (kịch bản step07 điển hình), một phép đo
2 arm cho bạn một con số Δ mà **không biết nó đến từ đâu**. Ba arm giải được, chi phí tăng 50%:

| Arm | Retrieval | Adjudication | Đọc được gì |
|---|---|---|---|
| **A** — baseline | token-overlap + indicator axis (hiện tại) | `Adjudicator` 1-shot | mốc |
| **B** — agent-retrieval, **judge đóng băng** | agent multi-hop | `Adjudicator` 1-shot, **y hệt arm A** | **B − A = đóng góp thuần của retrieval** |
| **C** — agent đầy đủ | agent multi-hop | agent adjudication | **C − B = đóng góp thuần của adjudication** |

Arm B là arm quan trọng nhất và hay bị bỏ qua nhất. Nó rẻ (dùng lại code cũ), và nó là cách
duy nhất trả lời được câu hội đồng chắc chắn hỏi: *"cải thiện là do agent thông minh hơn hay
chỉ do nó được đọc nhiều dữ liệu hơn?"*

### 3.3 Pre-registration — chốt metric TRƯỚC khi chạy agent

Ghi vào một file (vd. `docs/AGENT_AB_PREREG.md`), commit **trước** lần chạy đầu tiên của arm B/C:

1. Primary endpoint (§5) và guard (§6) — chọn đúng **một** primary.
2. Ngưỡng phát biểu thành công, viết ra bằng số, vd. *"Δ MR-violation ≤ −5 điểm phần trăm với
   p < 0,05 (McNemar), đồng thời Δ specificity ≥ −2 điểm phần trăm."*
3. Danh sách secondary endpoint và cách hiệu chỉnh đa so sánh (§9.3).

Đây không phải thủ tục hình thức. Không có nó, chạy 12 metric rồi báo cáo 3 cái đẹp nhất là
**p-hacking**, và với 12 metric ở mức α = 0,05 thì xác suất có ≥1 kết quả "có ý nghĩa" hoàn
toàn do ngẫu nhiên là **1 − 0,95¹² ≈ 46%**. Pre-registration là thứ rẻ nhất bạn có thể làm để
biến bộ số này từ "kể chuyện" thành "thí nghiệm".

---

## 4. Họ M0 — Metric xác định, 0 đồng, không LLM ⭐ làm trước tiên

Tất cả offline, chạy lại miễn phí bao nhiêu lần cũng được — đúng quy tắc `test/` của repo
(*"never verify by re-running a paid stage"*).

| ID | Metric | Cách đo | Áp cho agent ở |
|---|---|---|---|
| **M0.1** | **Δ Q1–Q8** | `run.py quality --label before` / `--label after` rồi diff hai JSON. **Đã cài đặt sẵn** | step02, step05 |
| **M0.2** | Δ tỉ lệ triple không hợp lệ | `unfixable_triples.json` / tổng triple, từ `build_validated` | step02 |
| **M0.3** | **Δ citation validity** | Mọi node/edge agent viện dẫn trong `rationale`/`via_path` phải **tồn tại** trong đồ thị **và** nằm trong tập evidence đã retrieve. Kiểm bằng set-membership | cả 4 |
| **M0.4** | Δ verdict consistency trên claim trùng lặp | `EVALUATION_WITHOUT_LABELS.md` §2.3, chạy cho cả 2 arm (mốc hiện tại: 1/23 mâu thuẫn) | step07, UI |
| **M0.5** | Δ p-value kiểm định hoán vị | `EVALUATION_WITHOUT_LABELS.md` §4.3, chạy cho cả 2 arm | step07 |
| **M0.6** | **Chi phí**: token / lệnh gọi / giây, chuẩn hóa theo *claim được giải quyết* | Đếm từ log | cả 4 |

**M0.3 đáng chú ý** — đây là metric mạnh bất thường so với chi phí của nó. Agent multi-step
là loại hệ **hay bịa tham chiếu nhất** (viện dẫn node không tồn tại, hoặc node có tồn tại
nhưng chưa từng nằm trong ngữ cảnh nó đọc). Phép kiểm là set-membership thuần túy: **xác định
100%, 0đ, không LLM, không cần nhãn** — nhưng nó bắt đúng chế độ hỏng nguy hiểm nhất của
tầng agent, vì một dẫn chứng bịa nhìn *thuyết phục hơn* một dẫn chứng thật.

**M0.6 không phải phụ.** Một agent luôn có thể mua chất lượng bằng số lệnh gọi. Báo cáo Δ chất
lượng mà không kèm Δ chi phí là báo cáo một nửa. Chuẩn hóa theo *claim được giải quyết*, không
theo *claim đầu vào* — nếu không, một agent bỏ qua 90% claim sẽ trông rất rẻ.

**M0.1 là món quà có sẵn.** `run.py quality` được thiết kế đúng cho tình huống này
(`TEMPORAL_KG_DESIGN.md` §4), và với agent ở step02/step05 thì Q2 (consistency), Q3
(conciseness — số entity T1 trùng), Q6 (provenance), Q7 (traversability) **chính là** metric
before/after cần tìm, không cần thiết kế gì thêm. Lưu ý dùng `--skip-slow` khi lặp nhanh, và
chạy bản đầy đủ cho con số cuối cùng.

---

## 5. ⭐ Họ M1 — PRIMARY ENDPOINT: Δ tỉ lệ vi phạm metamorphic + McNemar

### 5.1 Vì sao đây là metric chính

Đây là họ duy nhất tạo ra được **nhãn đúng/sai khách quan mà không cần người**. MR-2 (đảo dấu
số) nói: *evidence "giảm 42,3%" bị đổi thành "tăng 42,3%" thì verdict phải lật*. Hệ nào không
lật là **sai**, và kết luận đó không phụ thuộc ý kiến ai. Có nhãn ⇒ có mọi thứ:

- so sánh paired đúng nghĩa,
- **p-value thật** qua McNemar,
- effect size có đơn vị đọc được (điểm phần trăm vi phạm giảm đi).

Sáu MR đã định nghĩa sẵn ở `EVALUATION_WITHOUT_LABELS.md` §3.2 — **không định nghĩa lại**.
Việc ở đây là chạy chúng trên **cả hai arm, trên cùng tập input**, rồi so.

### 5.2 Công thức

Với mỗi MR, mỗi arm, mỗi item *i* trong tập đo `P` (|P| = 191 cặp có verdict, xem §3.5 file cũ):

```
v_A(i), v_B(i) ∈ {0, 1}      # 1 = vi phạm kỳ vọng của MR
```

Bảng 2×2 các cặp **bất đồng**:

```
              B đúng   B vi phạm
A đúng           n₀₀        b
A vi phạm         c        n₁₁
```

```
Δ_violation = mean(v_B) − mean(v_A)          # âm là tốt
p           = McNemar exact = 2 · min[ P(X ≤ min(b,c)) ], X ~ Binom(b+c, 0.5)
CI 95%      = paired bootstrap 10.000 lần trên Δ_violation
```

**Chỉ `b` và `c` mang thông tin** — các item hai hệ hành xử giống nhau bị loại khỏi kiểm định,
đó chính là chỗ thiết kế paired ăn điểm về power. Hệ quả thực dụng: **power phụ thuộc `b + c`,
không phụ thuộc 191**. Nếu hai hệ chỉ bất đồng ở 8 item thì không có thiết kế thống kê nào cứu
được — xem §9.4.

### 5.3 Ưu tiên MR nào

Kế thừa nguyên xi lập luận §3.3 của file cũ, cộng một tiêu chí riêng của bài toán A/B:

| MR | Ưu tiên | Lý do (thêm phần A/B) |
|---|---|---|
| **MR-2** đảo dấu số | ⭐⭐⭐ | 175/191 evidence là `KPIObservation` chứa số. Biến đổi thuần regex ⇒ **không nhập nhiễu LLM vào chính phép đo** — cực kỳ quan trọng khi đo Δ, vì nhiễu sinh dữ liệu sẽ xuất hiện ở cả hai arm và **thổi phồng `b + c` bằng nhiễu**, làm loãng power. |
| **MR-4** dịch thời gian | ⭐⭐⭐ | Kiểm chứng nguyên tắc P8 — đóng góp học thuật của đề tài. File cũ **dự báo MR-4 hỏng nặng ở baseline** (100% evidence `date_uncertain=True`). Nếu agent biết truy vấn trục thời gian, **đây là chỗ nó phải thắng đậm nhất** ⇒ MR có `b + c` lớn nhất ⇒ metric nhạy nhất. |
| **MR-3** đổi chủ thể | ⭐⭐ | Đo trực tiếp rủi ro của retrieval multi-hop: đi 2 hop qua công ty con rất dễ kéo về conduct của **pháp nhân khác**. Agent càng đi xa, MR-3 càng dễ hỏng — đúng thứ cần canh. |
| **MR-6** chèn nhiễu | ⭐⭐ | Agent đọc ngữ cảnh dài hơn baseline ⇒ nhạy nhiễu hơn về lý thuyết. Rẻ, thuần nối chuỗi. |
| MR-1, MR-5 | ⭐ | Cần template phủ định/paraphrase cẩn thận (§3.6 file cũ). Làm sau. |

### 5.4 Gộp MR — cẩn thận

Cám dỗ: gộp 6 MR thành một "MR-violation tổng" để có `b + c` lớn. **Chỉ gộp được khi các MR
kiểm cùng một giả thuyết.** MR-2/MR-4 (định lượng + thời gian) gộp được thành *"tính đúng đắn
suy luận"*. MR-5/MR-6 (INV — ổn định) là **thuộc tính khác**, gộp vào là trộn hai đại lượng.
Gộp thì gộp trước khi chạy, ghi trong pre-registration (§3.3), không gộp sau khi nhìn số.

---

## 6. ⭐ Họ M2 — GUARD bắt buộc: Δ specificity trên negative control

Đây là trục Y của §2. Không có nó thì primary endpoint không phòng thủ được.

### 6.1 M2.1 — Δ specificity trên cặp ngẫu nhiên

Lấy **cùng một** tập 191 cặp `(claim, conduct)` ngẫu nhiên mà retrieval **không** chọn
(`EVALUATION_WITHOUT_LABELS.md` §4.2), cho **cả hai arm** phán xử:

```
specificity(arm) = |{cặp ngẫu nhiên nhận verdict "irrelevant"}| / 191
Δ_specificity    = specificity(B) − specificity(A)        # ≥ 0 là tốt
lift(arm)        = P(verdict ≠ irrelevant | cặp retrieval chọn)
                 / P(verdict ≠ irrelevant | cặp ngẫu nhiên)
Δ_lift           = lift(B) − lift(A)
```

**Cách đọc, kết hợp với §5:**

| Δ coverage | Δ specificity | Kết luận |
|---|---|---|
| ↑ | ≈ 0 hoặc ↑ | ✅ Cải thiện thật — agent tìm ra bằng chứng baseline bỏ sót |
| ↑ | ↓ mạnh | ⚠ **Bẫy nới lỏng** — agent chỉ dễ dãi hơn. Báo cáo là đánh đổi, kèm số |
| ≈ 0 | ↑ | ⚠ Agent chặt hơn nhưng không tìm thêm được gì — cải thiện độ tin, không cải thiện độ phủ |
| ↓ | ↓ | ❌ Agent tệ hơn ở cả hai trục — dừng, không cần đo tiếp |

**`Δ_lift` là kill-test của chính agent**, đúng như `lift` là kill-test của cả đề tài trong
file cũ. Nếu agent làm `lift` **giảm**, nghĩa là tầng agent làm nhoè ranh giới giữa cặp có
liên quan và cặp ngẫu nhiên — nó đang phá, không đang xây, dù coverage có đẹp thế nào.

Chi phí: **191 lệnh gọi/arm**. Đây là 191 lệnh gọi đáng giá nhất trong toàn bộ tài liệu.

### 6.2 M2.2 — Đối chứng âm cấu trúc (0đ, không LLM)

Ghép claim của AAA với conduct node **của tổ chức khác** (đồ thị có 438 `Organization`), đếm
bao nhiêu cặp như vậy lọt vào candidate set. Kỳ vọng ≈ 0 cho **cả hai arm**.

Với agent multi-hop thì đây **không còn là kiểm tra hình thức** như ở baseline: routing k-hop
qua `owns`/`investsIn` **cố ý** kéo pháp nhân khác vào (đó là tính năng — sai phạm công ty con
là conduct của mẹ, `CROSSCHECK_EXPANSION.md` §3.2). Nên metric phải tách hai loại:

```
rò_rỉ_hợp_lệ   = cặp khác pháp nhân NHƯNG có via_path hợp lệ tới issuer   → tính năng
rò_rỉ_thật     = cặp khác pháp nhân KHÔNG có via_path nào tới issuer      → LỖI, phải ≈ 0
```

`rò_rỉ_thật` là metric an toàn riêng của agent, baseline không thể vi phạm vì nó không đi hop
nào. 0đ, xác định, và nó bắt đúng chế độ hỏng mà mọi metric chất lượng đầu ra sẽ bỏ lọt.

---

## 7. Họ M3 — Win-rate mù trên tập bất đồng

Khi không có nhãn và không có MR nào áp được (điển hình: **agent hỏi–đáp trên UI**, nơi đầu ra
là văn xuôi tự do), ưu tiên cặp là công cụ còn lại.

### 7.1 Chỉ chấm tập bất đồng — tiết kiệm một bậc chi phí

```
D = { item : output_A(item) ≠ output_B(item) }
```

Item hai hệ cho ra kết quả giống nhau **không mang thông tin so sánh** — chấm chúng là đốt tiền
để đo hoà. Với step07, `D` thường là 5–20% của 1.093 claim. Báo cáo `|D| / N` như một metric
độc lập (**"agent đổi bao nhiêu phần kết luận"**): nếu `|D|/N < 2%` thì agent gần như không làm
gì, và đó đã là kết luận — khỏi chấm.

### 7.2 Giao thức chống thiên lệch (bắt buộc, cả 4 điều)

| # | Yêu cầu | Vì sao |
|---|---|---|
| 1 | **Mù đôi** — judge chỉ thấy "Đáp án A" / "Đáp án B", không biết cái nào của hệ nào | Hiển nhiên nhưng hay quên khi tự viết harness |
| 2 | **Hoán vị vị trí** — chấm mỗi cặp **hai lần**, đảo chỗ; bất đồng giữa hai lần ⇒ tính **hoà (0,5)** | Judge thiên vị lựa chọn đầu **60–65%** bất kể chất lượng, đủ để lật 10–15 điểm win-rate ở các ca sát nút |
| 3 | **Judge ≠ model chạy agent** | LLM ưu ái đầu ra của chính nó (self-preference). Agent chạy `gpt-4o-mini` thì judge phải là model khác |
| 4 | **Báo cáo trần: judge self-agreement** | Chấm lại 30 cặp lần hai; nếu judge chỉ tự đồng ý 85% thì win-rate 55% **không phân biệt được với hoà** |

```
win_rate_B = (#thắng_B + 0,5 · #hoà) / |D|          # 0,5 = hoà, KHÔNG loại bỏ
CI 95%     = Wilson
```

Phát biểu chỉ khi CI **không chứa 0,5**. Và luôn kèm mẫu số: *"win-rate 62% (CI 54–70%) trên
147 item bất đồng — 13,4% tổng số claim"*, không bao giờ chỉ "62%".

### 7.3 Giới hạn phải nói ra

Win-rate đo **cái judge thích**, không đo **cái đúng**. Judge LLM thiên vị câu trả lời **dài
hơn, tự tin hơn, nhiều dẫn chứng hơn** — mà đó **đúng là** thứ agent multi-step tự nhiên sinh
ra. Vậy nên win-rate **có xu hướng thiên vị agent ngay từ đầu**. Vì lý do đó, ở tài liệu này
win-rate là **secondary**, không phải primary; §5 (MR) là primary vì nó không có lỗ hổng này.
Cách vá một phần: ghi thêm độ dài đầu ra mỗi arm và kiểm xem win-rate có tương quan với độ dài
không — nếu có, nói ra.

---

## 8. Họ M4 — Độ tin cậy và quỹ đạo (chỉ khi agent là multi-step)

Bạn chưa chốt agent là ReAct tự gọi tool hay prompt chain cố định. Bảng dưới đánh dấu rõ phần
nào chỉ áp dụng cho loại đầu.

| ID | Metric | Áp dụng | Ghi chú |
|---|---|---|---|
| **M4.1** | **Δ Krippendorff α** giữa 3 lần chạy lại cùng input | cả hai loại | Agent multi-step **kém ổn định hơn** LLM 1-shot ngay cả ở `temperature=0`, vì thứ tự tool call phân nhánh. Nếu α tụt mạnh thì mọi Δ ở §5–§7 phải đọc lại: một phần Δ chỉ là nhiễu chạy lại |
| **M4.2** | Δ position-bias flip rate | cả hai | Đảo thứ tự evidence trong prompt |
| **M4.3** | Số bước / lệnh gọi tool trên mỗi item (trung vị, p95) | **chỉ ReAct** | p95 quan trọng hơn trung vị — đuôi dài là chỗ đốt tiền |
| **M4.4** | **Redundant call rate** | **chỉ ReAct** | Tỉ lệ lệnh gọi tool không đóng góp gì cho kết luận. Ở đây kiểm được **xác định, không cần nhãn**: truy vấn lặp cùng tham số, hoặc kết quả không xuất hiện trong `rationale`/evidence cuối |
| **M4.5** | **Convergence / termination rate** | **chỉ ReAct** | % lần chạy tự kết thúc không cần chạm trần bước. Chạm trần = **hard failure** (§10), không phải "chất lượng thấp" |
| **M4.6** | Step efficiency | **chỉ ReAct** | (số bước tối thiểu cần) / (số bước thực). Ở đây có mẫu số tự nhiên miễn phí: đường đi ngắn nhất trong đồ thị từ claim tới evidence — Neo4j `shortestPath` tính được |

**M4.6 là chỗ đồ thị cho lợi thế đo lường mà hệ RAG văn bản thuần không có.** Với hệ text
thuần, "số bước tối thiểu" phải do người gán. Ở đây `shortestPath` trong Neo4j cho ra mẫu số
**xác định và miễn phí**. Nếu agent đi 6 hop tới một node mà `shortestPath` dài 2, đó là lãng
phí đo được, không cần nhãn, không cần LLM.

---

## 9. Thống kê — dùng test nào cho metric nào

### 9.1 Bảng tra

| Dạng metric | Test | Khoảng tin cậy |
|---|---|---|
| Nhị phân, paired (MR violation, citation validity) | **McNemar exact** trên cặp bất đồng | paired bootstrap |
| Tỉ lệ, không paired (specificity trên 2 mẫu ngẫu nhiên khác nhau) | z-test 2 tỉ lệ, hoặc Fisher nếu đếm nhỏ | Wilson |
| Win-rate (§7) | binomial test vs 0,5 | Wilson |
| Đếm/liên tục (số bước, token, coverage) | **paired bootstrap** trên Δ (10.000 lần) | percentile 95% |
| Đa hạng mục (verdict 3 lớp) | Bowker/Stuart–Maxwell (mở rộng McNemar) | bootstrap |

### 9.2 Effect size, đừng chỉ p-value

Với 1.093 claim, một Δ nhỏ vô nghĩa về thực tiễn vẫn có thể có p < 0,05. Luôn báo cáo **cả
hai**: *"Δ = −7,2 điểm phần trăm (CI −11,1…−3,4), p = 0,003"*. Con số trong ngoặc là thứ người
đọc dùng để quyết định, p-value chỉ nói "không phải ngẫu nhiên".

### 9.3 Hiệu chỉnh đa so sánh

Bộ này có ~12–15 metric. Áp **Holm–Bonferroni** trên nhóm secondary; **primary endpoint được
miễn** vì nó đã được chốt trước khi nhìn dữ liệu (§3.3). Đây chính xác là lý do pre-registration
đáng công: nó mua cho bạn quyền báo cáo primary ở mức α gốc.

### 9.4 ⚠ Cỡ mẫu và power — kiểm TRƯỚC khi tiêu tiền

Với McNemar, power phụ thuộc **số cặp bất đồng `b + c`**, không phụ thuộc `N`. Quy tắc thô: cần
`b + c ≳ 25` để phát hiện một lệch rõ (tỉ lệ khoảng 80/20 giữa hai hướng) ở power 80%.

**Việc phải làm, chi phí 0đ:** chạy §5 trên **20 item thử** trước. Nếu `b + c = 0` hoặc 1 — hai
hệ hầu như không khác nhau — thì **dừng ngay**, đừng chi 191 lệnh gọi để đo một hiệu ứng không
tồn tại. Kết luận *"agent không đổi kết luận trên 20/20 ca thử"* tự nó đã là một phát hiện, và
nó tốn 40 lệnh gọi.

---

## 10. ⚠ Hard failure — đo riêng, không bao giờ trộn vào chất lượng

Agent hỏng theo cách LLM 1-shot **không thể** hỏng: lặp vô hạn, chạm trần bước, tool call sai
cú pháp, timeout, trả JSON hỏng giữa chừng.

Nếu bạn để những ca này rơi ra khỏi mẫu số (kiểu *"tính trên các item agent chạy xong"*), bạn
đã **chọn mẫu theo kết quả** — và một agent hỏng 30% số ca khó sẽ trông **giỏi hơn** baseline,
vì đúng những ca nó bỏ là những ca khó nhất.

**Quy tắc:**

```
hard_failure_rate = |{item agent không cho ra kết quả dùng được}| / N       # báo cáo RIÊNG
```

Và mọi metric chất lượng báo cáo **hai bản**:

- **Bản khắt khe (chính)** — hard failure tính là *thua* / *vi phạm* / *không có bằng chứng*.
- **Bản có điều kiện (phụ)** — chỉ trên các item chạy xong, ghi rõ mẫu số.

Baseline theo định nghĩa có `hard_failure_rate ≈ 0`, nên đây là một cột **agent luôn thua**.
Đó là cái giá thật của việc thêm agent, và nó phải hiện lên trong báo cáo.

---

## 11. Áp vào từng điểm cắm — bạn chọn cả 4

Cùng một khung, nhưng metric chính đổi theo vị trí. Cột "primary" là thứ pre-register.

### 11.1 step02 — extraction (agent self-critique khi trích triple)

| | |
|---|---|
| **Primary** | **Δ Q2 (consistency) + Δ Q3 (conciseness)** từ `run.py quality` — **đã cài đặt, 0đ** |
| **Guard (trục Y)** | Δ tỉ lệ triple không hợp lệ (M0.2) + Δ số node/trang. Agent trích **nhiều** triple hơn rất dễ, trích **đúng** hơn mới khó — Q3 (entity T1 trùng lặp) bắt đúng chỗ đó |
| Secondary | Δ Q6 provenance, Δ Q7 traversability, MR-INV (paraphrase câu nguồn ⇒ tập triple phải gần như không đổi), M0.6 chi phí/trang |
| Ghép item | **Bắt buộc** dùng `(source_pdf, page, sentence_index)` — §11.5 |
| Ghi chú | Điểm cắm **rẻ nhất để đo** trong cả 4, vì toàn bộ hạ tầng đo đã có sẵn và offline. Nếu cần một kết quả A/B trong tuần này, làm ở đây. Đồng thời có tác dụng phụ đáng giá: đây là chỗ **issue #6** (rò rỉ tiếng Anh, ~52,7% tên bị dịch) đang chờ đo lại bằng một lần re-extraction |

### 11.2 step05 — entity resolution (Stage C)

| | |
|---|---|
| **Primary** | **Δ Q3 conciseness** (số entity T1 trùng trên mỗi tên chuẩn hóa) — chính là thứ stage này tồn tại để giảm |
| **Guard (trục Y)** | **Δ merge sai**, đo bằng đối chứng âm cấu trúc: ghép cặp entity thuộc **hai ticker khác nhau** ⇒ phải **không** merge. Không cần nhãn, sinh được tùy ý |
| Secondary | Win-rate mù (§7) trên tập cặp hai arm quyết định khác nhau; Δ `needs_review` còn lại; M0.6 |
| Ghép item | Theo **cặp entity** `(normalize_name(a), normalize_name(b))` — bền qua rebuild |
| Ghi chú | Bẫy nới lỏng ở đây đặc biệt nguy: gộp mạnh tay luôn làm Q3 đẹp lên. Guard **bắt buộc**, không phải tùy chọn |

### 11.3 step07 — crosscheck (retrieval + adjudication) ⭐ nơi metric giàu nhất

| | |
|---|---|
| **Primary** | **Δ MR-violation rate gộp MR-2 + MR-4, McNemar** (§5) |
| **Guard (trục Y)** | **Δ specificity + Δ lift** trên negative control (§6.1) — **không thương lượng** |
| Secondary | Δ coverage (claim có ≥1 bằng chứng, mốc 8,4%); win-rate mù trên tập bất đồng; M0.3 citation validity; M0.4/M0.5; M4.x nếu ReAct; M0.6 |
| Thiết kế | **Bắt buộc 3 arm** (§3.2) — đây là điểm cắm duy nhất trong 4 cái thay đổi cả hai tầng cùng lúc |
| Ghép item | `claim_id` — **an toàn ở đây** vì cả hai arm đọc **cùng** `resolved_graph.json`, không rebuild. ⚠ Tuyệt đối không ghép bằng `claim_node_index` |
| Ghi chú | MR-4 là chỗ kỳ vọng agent thắng đậm nhất (baseline dự báo hỏng nặng vì `date_uncertain` = 100%) ⇒ metric nhạy nhất và cũng là chỗ chứng minh nguyên tắc P8 |

### 11.4 Agent hỏi–đáp trên UI (tầng SSRL, steps 11–13 chưa có)

| | |
|---|---|
| **Primary** | **Δ groundedness/faithfulness** kiểu RAGAS: mỗi mệnh đề trong câu trả lời phải quy chiếu được về node/edge trong tập đã truy hồi |
| **Guard (trục Y)** | **M0.3 citation validity** (xác định, 0đ) + tỉ lệ trả lời cho **câu hỏi không trả lời được** (bơm câu hỏi về công ty/chỉ tiêu **không có** trong đồ thị ⇒ hệ **phải** từ chối). Đây là negative control của tầng QA, sinh được tùy ý, 0đ ngoài chi phí gọi |
| Secondary | Win-rate mù (§7) — ở đây win-rate là hợp lý nhất trong 4 điểm cắm vì đầu ra là văn xuôi; self-consistency 3 lần chạy (M4.1); M0.6 độ trễ (tầng UI thì độ trễ **là** chất lượng) |
| Ghép item | Theo **câu hỏi** — bạn tự soạn bộ câu hỏi, nên ghép là hiển nhiên |
| Ghi chú | Không có baseline tự nhiên (tầng này chưa tồn tại). Phải **tự dựng baseline**: retrieval 1-hop + 1 lần gọi LLM. Không có baseline thì không có A/B, chỉ có demo |

### 11.5 ⚠ Khóa ghép item — chặn cứng cần xử lý trước

Mọi thống kê paired ở §5, §9 **sụp đổ** nếu không ghép được item giữa hai lần chạy.

| Kịch bản | Có rebuild đồ thị? | Khóa ghép | Trạng thái |
|---|---|---|---|
| Agent ở **step07** hoặc **UI** | Không — cùng `resolved_graph.json` | `claim_id` | ✅ Chạy được **ngay hôm nay** |
| Agent ở **step02** hoặc **step05** | **Có** | `claim_id` **KHÔNG dùng được** | ⚠ Chặn |

Lý do chặn: `claim_id` chưa xác định giữa các lần chạy (**GitHub issue #2**, CLAUDE.md liệt kê
là tiền đề chưa xong của lần re-extraction đã lên lịch). Rebuild ⇒ id đổi ⇒ không ghép được.

**Cách vá, không cần chờ issue #2:** ghép bằng bộ ba provenance
**`(source_pdf, page, sentence_index)`**. CLAUDE.md bảo đảm bộ ba này **được giữ nguyên qua mọi
stage** (*"Sentence-level traceability is preserved through every stage"*) — nên nó là khóa ghép
bền vững hơn `claim_id` cho đúng mục đích này, và nó đã có sẵn. Với step05, ghép theo cặp tên
chuẩn hóa (§11.2).

Hệ quả thực dụng về thứ tự làm việc: **step07/UI đo được ngay; step02/step05 phải cài khóa ghép
provenance trước khi chạy arm B.** Nếu chỉ đủ thời gian cho một điểm cắm, chọn theo bảng này chứ
đừng chọn theo cái nào thú vị nhất.

---

## 12. Thứ tự thực thi và chi phí

Ước tính cho step07 (điểm cắm tốn kém nhất), **mỗi arm**. Một lần chạy step07 gốc ≈ 3.461 lệnh gọi.

| # | Việc | Chi phí LLM/arm | Ra được gì |
|---|---|---|---|
| 0 | §9.4 power check trên 20 item | **~40** | **Đi tiếp hay dừng** — làm trước mọi thứ |
| 1 | §4 toàn bộ họ M0 + §6.2 rò rỉ cấu trúc | **0** | Q1–Q8, citation validity, chi phí, p-value hoán vị |
| 2 | §6.1 negative control (guard) | **191** | **Trục Y — không có nó thì không phát biểu được gì** |
| 3 | §5 MR-2 + MR-4 (primary) | **382** | **Primary endpoint + p-value McNemar** |
| 4 | §7 win-rate trên tập bất đồng (×2 vì hoán vị vị trí) | **2 · \|D\|** ≈ 300 | Ưu tiên mù |
| 5 | §5 MR-3 + MR-6 | 382 | Định danh chủ thể, kháng nhiễu |
| 6 | §8 M4.1 test–retest ×3 | 573 | Δ Krippendorff α |

**Mục 0–3 = ~613 lệnh gọi/arm ≈ 18% một lần chạy step07.** Với 2 arm là ~1.230; với 3 arm
(§3.2) là ~1.840. Đây là toàn bộ chi phí để có một kết luận A/B phòng thủ được.

Nếu chỉ đủ cho một việc: **mục 2** (guard) — vì không có nó, mọi con số khác đều không phát
biểu được. Nếu đủ cho hai: **0 → 2**. Nếu đủ cho ba: **0 → 2 → 3**.

Ghi chú kỹ thuật: mục 1 phải viết như test offline theo quy ước repo (plain `assert`, chạy từ
repo root, không LLM/DB/mạng). Mục 2–6 gọi LLM nên **không** thuộc bộ test miễn phí — đặt sau
biến môi trường như `RUN_LLM_INTEGRATION_TESTS=1`, cùng khuôn với
`test/test_esg_kg_integration_llm.py`.

---

## 13. Giới hạn trung thực

1. **Không metric nào ở đây là accuracy.** Cả hai hệ có thể cùng sai một cách hệ thống, và mọi
   phép đo Δ sẽ im lặng về điều đó. Đây là trần cứng của đánh giá không nhãn.
2. **§7 win-rate thiên vị agent theo cấu trúc** — judge thích câu dài, tự tin, nhiều dẫn chứng,
   đúng thứ agent multi-step sinh ra. Vì thế nó là secondary, không phải primary.
3. **§5 phụ thuộc chất lượng của phép biến đổi.** MR-2/3/4/6 thuần regex nên sạch; MR-1/MR-5
   cần template, và template tồi sẽ đội `b + c` bằng nhiễu, làm loãng power theo hướng **bất
   lợi cho agent** — thiên lệch an toàn, nhưng phải nói ra.
4. **Power có thể không đủ.** Nếu agent chỉ đổi kết luận ở <2% số item, không thiết kế thống kê
   nào cứu được. §9.4 tồn tại để phát hiện điều đó **trước** khi tiêu tiền, không phải sau.
5. **Không metric nào ở đây cứu được vấn đề gốc**: phía conduct chỉ chiếm 2% đồ thị và chưa có
   một `Controversy`/`Penalty` nào từ nguồn độc lập. Một agent giỏi tìm kiếm trên một kho bằng
   chứng mỏng vẫn bị chặn trần bởi kho đó. **Kỳ vọng hợp lý: agent cải thiện *độ tin* và *khả
   năng giải thích* (via_path, dẫn chứng kiểm được) rõ hơn là cải thiện *độ phủ*.** Nên
   pre-register theo kỳ vọng đó, đừng đặt primary endpoint vào coverage.
6. **Toàn bộ §5, §6.1, §7 dừng nếu mất OpenAI** — hiện là provider duy nhất (Gemini 403 vĩnh
   viễn). Họ M0 (§4) và §6.2 vẫn chạy được, và đó là lý do nên làm chúng trước.

---

## 14. Tham chiếu

**Học thuật**

- Ribeiro et al. (2020), *Beyond Accuracy: Behavioral Testing of NLP Models with CheckList*, ACL
  — [aclanthology.org/2020.acl-main.442.pdf](https://aclanthology.org/2020.acl-main.442.pdf) — khung MFT/INV/DIR của §5
- *A Systematic Study of Position Bias in LLM-as-a-Judge* —
  [aclanthology.org/2025.ijcnlp-long.18.pdf](https://aclanthology.org/2025.ijcnlp-long.18.pdf) — cơ sở cho giao thức hoán vị vị trí §7.2
- *Beyond the Surface: Measuring Self-Preference in LLM Judgments* —
  [arxiv.org/pdf/2506.02592](https://arxiv.org/pdf/2506.02592) — vì sao judge phải khác model chạy agent (§7.2 điều 3)
- *Redundant or Necessary? A Benchmark for Detecting Redundant Steps in Agent Trajectories* —
  [arxiv.org/html/2605.29893](https://arxiv.org/html/2605.29893) — định nghĩa redundant-call rate (M4.4)
- *RAGAS: Automated Evaluation of RAG* —
  [arxiv.org/html/2309.15217v1](https://arxiv.org/html/2309.15217v1) — faithfulness reference-free (§11.4)
- *Detecting Greenwashing: A NLP Literature Survey* —
  [arxiv.org/pdf/2502.07541](https://arxiv.org/pdf/2502.07541) — xác nhận lĩnh vực chưa có benchmark/giao thức đánh giá
- *LLM Agent Evaluation Metrics: Tool Calling, Task Completion, Trace-Based Evals* —
  [confident-ai.com/blog/llm-agent-evaluation-complete-guide](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide) — nhóm metric quỹ đạo §8
- *Comparing NLP Models with Confidence: The Paired Bootstrap Test* —
  [medium.com/ai-enthusiast](https://medium.com/ai-enthusiast/comparing-nlp-models-with-confidence-the-paired-bootstrap-test-explained-c9a88532ea3d) — §9.1

**Trong repo**

- [`EVALUATION_WITHOUT_LABELS.md`](EVALUATION_WITHOUT_LABELS.md) — MR suite (§3), negative control (§4),
  Krippendorff α (§5), **§8 metric đã chết — đừng đề xuất lại**, §9 cạm bẫy đo trên đồ thị này
- [`TEMPORAL_KG_DESIGN.md`](../TEMPORAL_KG_DESIGN.md) §3 P8, §4 Q1–Q8 — nền của M0.1
- [`CROSSCHECK_EXPANSION.md`](CROSSCHECK_EXPANSION.md) §3 — thiết kế retrieval multi-hop mà agent
  ở step07 sẽ hiện thực, và D1–D6 là danh sách thứ metric phải nhìn vào
- `CLAUDE.md` — quy tắc TDD (test offline, plain assert), `data_version.json` (ghim snapshot, §3.1),
  bảo đảm traceability `(source_pdf, page, sentence_index)` (§11.5)
