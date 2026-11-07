# P1.8 — Reference-aware evidence guard (offline)

## Mục lục

- [Bối cảnh và giả thuyết](#bối-cảnh-và-giả-thuyết)
- [Các chế độ thử nghiệm](#các-chế-độ-thử-nghiệm)
- [Chạy trên Windows PowerShell](#chạy-trên-windows-powershell)
- [Tiêu chí quyết định](#tiêu-chí-quyết-định)
- [Giới hạn](#giới-hạn)

## Bối cảnh và giả thuyết

P1.7 (20 case, 99 gold spans) đạt baseline 10/99, `adaptive_0` 11/99,
`adaptive_1` 12/99. Phân tích case cho thấy `adaptive_1` làm mất hai gold
spans so với baseline: `0013/E3` và `0016/E2`. Cả hai đã mất khi chạy
`adaptive_0`, chưa có Dense. `adaptive_1` tăng thêm các spans mới nhưng
`0011/E1` của `adaptive_0` không được giữ. Mục tiêu P1.8 là kiểm tra một
cơ chế bảo vệ source lines được lựa chọn từ baseline khi chúng liên quan
rõ đến câu hỏi, **không dùng gold labels trong thuật toán**.

## Các chế độ thử nghiệm

- `baseline`: `acquire_evidence` mặc định, read-only trên pinned source.
- `adaptive_1`: nguyên trạng selector P1.7 với một Dense alternate.
- `guard_critical`: quay về baseline khi adaptive làm mất ít nhất một
  source line trong baseline chứa từ khóa câu hỏi và cấu trúc code, hoặc
  có ít nhất hai từ khóa câu hỏi.
- `guard_query`: trong trường hợp trên, chỉ quay về baseline nếu adaptive
  không tăng số từ khóa truy vấn khác nhau được bao phủ.

Mỗi chế độ dùng cùng giới hạn 3.000 ký tự JSON/case; guard chỉ chọn một
trong hai tập excerpt đã được tạo, không ghép hoặc sửa source lines.

## Chạy trên Windows PowerShell

```powershell
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval

py -3 -m unittest `
  benchmark.tests.test_reference_guard `
  benchmark.tests.test_reference_guard_ablation `
  benchmark.tests.test_context_budget_ablation -v

py -3 benchmark/reference_guard_ablation.py `
  --from-report "benchmark/results/_diagnostics/multiwindow_full_ablation_v2.json" `
  --p17-report "benchmark/results/_diagnostics/context_budget_p17_ablation.json" `
  --max-chars 3000 `
  --limit 6 `
  --out "benchmark/results/_diagnostics/p18_reference_guard_ablation.json"
```

Chỉ cần gửi `summary`. Trường `p17_control_verification` phải có
`controls_identical_to_p17: true`.

## Tiêu chí quyết định

Đối chiếu số gold spans có source refs, tổng gains/losses, case bị mất
evidence, số case guard quay về baseline, mức sử dụng context. Không chọn
một guard chỉ vì nó cải thiện trên 20 case đã được dùng để chẩn đoán;
cần validation độc lập và agent runtime A/B nếu phát hiện lợi ích.

## Giới hạn

Giữ nguyên `semantic_agent.py`, `evidence_acquisition.py`, và tất cả
mặc định runtime. Thí nghiệm đọc actual source từ pinned checkout,
không tạo câu trả lời LLM. Kết quả chỉ đo prefetch source refs, không đo
độ đúng claim hoặc đáp án cuối cùng.
