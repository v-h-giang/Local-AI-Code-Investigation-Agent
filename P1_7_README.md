# P1.7 — Context-budget-aware Evidence Selection

## Mục lục

- [Mục tiêu và giả thuyết](#mục-tiêu-và-giả-thuyết)
- [Các chế độ A/B](#các-chế-độ-ab)
- [Áp dụng lên branch](#áp-dụng-lên-branch)
- [Kiểm thử và benchmark](#kiểm-thử-và-benchmark)
- [Cách đọc kết quả](#cách-đọc-kết-quả)
- [Giới hạn](#giới-hạn)

## Mục tiêu và giả thuyết

P1.6 đạt 10/99 gold spans có `source_refs` cho cả baseline, +1 và +2 cửa sổ, trong ngân sách 3.000 ký tự/case. Hai phương án cũ dành trước 500 ký tự cho mỗi cửa sổ Dense và có trường hợp mất bằng chứng gốc.

P1.7 thử chọn các đoạn source từ Hybrid và Dense dưới **một ngân sách dùng chung**, dựa trên mức khớp câu hỏi, thông tin mới, cấu trúc code và chi phí ký tự của đoạn trích. Đây là một phương án thực nghiệm, chưa có kết quả A/B.

## Các chế độ A/B

| Mode | Nguồn cửa sổ | Phân bổ |
|---|---|---|
| `baseline` | Hybrid top 8 | `acquire_evidence` đang dùng |
| `fixed_1` | Hybrid + 1 Dense | Dành trước 500 ký tự |
| `fixed_2` | Hybrid + 2 Dense | Dành trước 1.000 ký tự |
| `adaptive_0` | Hybrid top 8 | Chọn theo utility / chi phí |
| `adaptive_1` | Hybrid + 1 Dense | Một ngân sách toàn cục |
| `adaptive_2` | Hybrid + 2 Dense | Một ngân sách toàn cục |

Tất cả mode có **3.000 ký tự JSON**, tối đa 6 excerpt. Không có thay đổi nào đối với `semantic_agent.py`, `evidence_acquisition.py` hay default agent runtime.

## Áp dụng lên branch

Tải `P1_7.patch` về thư mục repository. Trong PowerShell, tại root repository:

```powershell
# Đọc trạng thái trước khi áp dụng, tránh ghi đè thay đổi chưa commit.
git status --short
git switch feature/qwen3-embedding-retrieval
git apply --check .\P1_7.patch
git apply .\P1_7.patch
```

Nếu patch không nằm tại root repository, dùng đường dẫn thực tế của file patch. `git apply --check` cần chạy thành công trước khi `git apply`. **Không** chạy patch trên `main`.

## Kiểm thử và benchmark

```powershell
py -3 -m unittest `
  benchmark.tests.test_context_budget_selector `
  benchmark.tests.test_context_budget_ablation `
  benchmark.tests.test_evidence_window_ablation -v

py -3 benchmark/context_budget_ablation.py `
  --from-report "benchmark/results/_diagnostics/multiwindow_full_ablation_v2.json" `
  --max-chars 3000 `
  --fixed-window-chars 500 `
  --limit 6 `
  --p16-report "benchmark/results/_diagnostics/evidence_window_ablation.json" `
  --out "benchmark/results/_diagnostics/context_budget_p17_ablation.json"
```

Lệnh chỉ cần source checkout đã pin và JSON P1.5; không cần chạy lại Ollama. Nếu tests PASS và bạn đồng ý đưa thay đổi lên branch:

```powershell
git add context_budget_selector.py benchmark/context_budget_ablation.py `
  benchmark/tests/test_context_budget_selector.py `
  benchmark/tests/test_context_budget_ablation.py `
  P1_7_README.md
git commit -m "P1.7 add offline shared-budget evidence selection ablation"
git push origin feature/qwen3-embedding-retrieval
```

Git push là thao tác riêng trên máy của bạn; gói này không tự push hoặc sửa main.

## Cách đọc kết quả

`summary.p16_control_verification` xác nhận ba chế độ đối chứng khớp P1.6 đã lưu. Nếu có sai khác, chương trình dừng thay vì so sánh hai phép đo không đồng nhất.

`summary.modes` chứa số gold spans có thể dùng làm `source_refs`, số case tăng/mất bằng chứng so với baseline, số dòng code hiển thị và tổng ký tự đã sử dụng. Đánh giá **mức tăng ròng và số case suy giảm**, không chỉ số lần chọn Dense.

Tiêu chí sàng lọc trước khi thử agent thật: `adaptive_1` hoặc `adaptive_2` tăng gold spans có source_refs; không gây suy giảm đáng kể theo case; giữ đúng ngân sách và tính toàn vẹn line refs. Mọi giá trị đo trên 20 case chỉ có ý nghĩa thăm dò vì đã sử dụng lặp lại nhiều lần.

## Giới hạn

- `source_refs` là nguồn có mặt trong excerpt, không phải citation của câu trả lời cuối cùng.
- Chi phí là ký tự JSON, không phải số token mô hình.
- Điểm relevance đơn giản dựa vào token và cấu trúc, không khẳng định hiểu chính xác semantic code.
- Kết quả chưa được xác nhận trên môi trường Windows của bạn.
