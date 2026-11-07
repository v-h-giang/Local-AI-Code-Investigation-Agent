# P1.9 — Incremental Evidence Merge (offline A/B)

## Mục lục

- [Bối cảnh](#bối-cảnh)
- [Cơ chế thử nghiệm](#cơ-chế-thử-nghiệm)
- [Kiểm thử](#kiểm-thử)
- [Chạy A/B](#chạy-ab)
- [Đọc kết quả](#đọc-kết-quả)
- [Giới hạn và điều kiện triển khai](#giới-hạn-và-điều-kiện-triển-khai)

## Bối cảnh

P1.7 `adaptive_1` đạt 12/99 gold spans có `source_refs`, gồm 4 spans mới và 2 spans baseline bị mất. P1.8 `guard_critical` giữ 10/99; `guard_query` giữ 11/99. Đối với case `0013`, baseline chứa `E3` và adaptive chứa `E2`; đối với case `0016`, baseline chứa `E2` và adaptive chứa `E1`. Chính sách P1.8 chọn **toàn bộ** một trong hai tập evidence.

## Cơ chế thử nghiệm

`incremental_evidence_merge.py` nhận hai tập excerpt Baseline và Adaptive 1 đã được đọc bằng các hàm hiện có. Nó đối chiếu dòng source `path:line`, loại trùng lặp, tách các nhóm dòng liền nhau và phân bổ ngân sách **3.000 ký tự JSON/case**, tối đa sáu excerpt. Nội dung và số dòng không bị viết lại.

- `merge_balanced`: xếp hạng toàn cục các nhóm dòng dựa trên query terms, cấu trúc source, độ mới và chi phí ký tự.
- `merge_anchored`: ưu tiên giữ ít nhất một nhóm dòng từ mỗi excerpt baseline khi ngân sách cho phép, rồi tiếp tục chọn các nhóm còn lại.

Không có chế độ nào dùng gold spans để lựa chọn source. Gold chỉ được xét ở giai đoạn tính metrics sau khi tất cả excerpt được cố định. Đây là code benchmark riêng, không kết nối vào agent runtime.

## Kiểm thử

Trong PowerShell, tại thư mục gốc của repository:

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval

py -3 -m unittest `
  benchmark.tests.test_incremental_evidence_merge `
  benchmark.tests.test_incremental_merge_ablation -v
```

## Chạy A/B

```powershell
py -3 benchmark/incremental_merge_ablation.py `
  --from-report "benchmark/results/_diagnostics/multiwindow_full_ablation_v2.json" `
  --p18-report "benchmark/results/_diagnostics/p18_reference_guard_ablation.json" `
  --max-chars 3000 `
  --limit 6 `
  --max-block 3 `
  --out "benchmark/results/_diagnostics/p19_incremental_merge_ablation.json"
```

Chương trình sử dụng pinned source checkout hiện có, không cần Ollama. `p18_control_verification` phải báo `controls_identical_to_p18: true`.

## Đọc kết quả

So sánh `summary.modes.baseline`, `adaptive_1`, `merge_balanced`, `merge_anchored`:

- `gold_spans_citable`: số gold spans giao với source_refs thực sự hiển thị.
- `gross_gains_vs_baseline`, `gross_losses_vs_baseline`: mức cải thiện và regression theo từng span.
- `gross_gains_vs_adaptive_1`, `gross_losses_vs_adaptive_1`: so sánh trực tiếp với ứng viên tốt nhất P1.7.
- `unbudgeted_union_ceiling`: tổng số gold spans trong hợp Baseline + Adaptive 1; chỉ là trần cơ hội khi bỏ qua context budget.
- `serialized_chars`, `displayed_source_lines`, `lost_baseline_source_lines`: chi phí, lượng evidence giữ lại.
- `cases[].changes`: ID từng gold span được/mất trong mỗi case, gồm `0013` và `0016`.

## Giới hạn và điều kiện triển khai

Kết quả là khả năng chứa source-line evidence trong prefetch, không đo khả năng trả lời đúng của agent. Gộp các dòng không liên tiếp trong một file có thể giảm ngữ cảnh đọc hiểu; cần đo thêm tính đầy đủ về cấu trúc code. Việc tối ưu trên cùng 20 case đã phân tích có nguy cơ overfitting; chỉ xem là exploratory. Giữ nguyên default runtime và `main`; chỉ triển khai vào agent sau khi có A/B trên case độc lập và đánh giá claim/citation correctness.
