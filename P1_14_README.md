# P1.14 — Contiguous Source Evidence Packing (offline)

## Mục lục

- [Mục tiêu](#mục-tiêu)
- [Thuật toán](#thuật-toán)
- [Chạy trên PowerShell](#chạy-trên-powershell)
- [Cách đọc báo cáo](#cách-đọc-báo-cáo)
- [Giới hạn](#giới-hạn)

## Mục tiêu

Báo cáo P1.13 cho Click xác định 21/24 gold spans có ít nhất một dòng nằm trong toàn bộ candidate windows, trong khi `merge_anchored_1` chỉ giữ 5/24 và 0/24 complete spans. P1.14 thử giữ **các đoạn source liên tục** thay vì chọn từng dòng và đánh giá riêng prefetch coverage, complete-span và độ rời rạc.

Không thay code runtime, không đổi Qwen3 embeddings, không sửa candidate windows và không đọc gold labels để xếp hạng. Click là bộ câu hỏi **đã quan sát**; kết quả P1.14 trên Click chỉ dùng để phát triển, không phải held-out mới.

## Thuật toán

- Input: top-8 Hybrid windows và tối đa 1 Dense alternate từ `p112_click_windows.json`, cùng câu hỏi không có gold.
- Đọc source qua `Repo.read_file(path, start, end)` tại commit đã khóa; từ chối các dòng không liên tục, xung đột hoặc không có provenance.
- Từ mỗi source window lấy các ứng viên đoạn **liên tục 8 hoặc 12 dòng** theo anchor khớp từ khóa và cấu trúc khai báo/điều khiển; đây là các kích thước cố định cho thử nghiệm, chưa tune theo nhãn Click.
- Chọn greedy theo query-term novelty, structural signals, vị trí candidate và chi phí JSON, tối đa 6 excerpts, **3.000 ký tự JSON/case**. Không trùng lặp `source_refs`, không lược bỏ dòng trong một excerpt.
- Đánh giá `gold_spans_any_line`, `gold_spans_complete`, source-line fragmentation và gains/losses so với Baseline/Anchored đã có.
- So sánh với P1.11 saved controls, kiểm tra SHA của labels/windows, checkout Git đúng repository và pinned SHA. Báo cáo mới không ghi đè.

Đây là heuristic, không phải parser bảo đảm giữ đủ block/scope hay complete function. Các dòng liền nhau là một proxy về ngữ cảnh, không chứng minh đáp án chính xác.

## Chạy trên PowerShell

Thực hiện trong thư mục gốc project sau khi P1.12 hoàn thành:

```powershell
# Update experimental branch
git switch feature/qwen3-embedding-retrieval
git pull origin feature/qwen3-embedding-retrieval

# Unit tests; no Ollama
py -3 -m unittest `
  benchmark.tests.test_structure_aware_evidence `
  benchmark.tests.test_structure_packing_ablation -v

# Reuse Click pinned checkout and P1.11 reports; no new embedding
py -3 benchmark/structure_packing_ablation.py `
  --labels-jsonl "benchmark/datasets/p112_click_labels.jsonl" `
  --from-report "benchmark/results/_diagnostics/p112_click_windows.json" `
  --evaluation "benchmark/results/_diagnostics/p112_click_p11_evaluation.json" `
  --checkout "benchmark/repositories/click_p112" `
  --repository "pallets/click" `
  --commit "ac0e297ec2d7d78455a7d18ce306996e668c4a85" `
  --out "benchmark/results/_diagnostics/p114_structure_packing_ablation.json"
```

Nếu output tồn tại, đổi sang một tên output khác thay vì xóa kết quả cũ. CLI sẽ kiểm tra hash của input và refuse overwrite.

## Cách đọc báo cáo

- `summary.controls`: nguyên trạng kết quả P1.11 cho bốn chính sách đã khóa.
- `summary.structure_contiguous_8_12`: kết quả mới; quan sát `gold_spans_any_line`, `gold_spans_complete`, `gross_gains_vs_baseline`, `gross_losses_vs_baseline`, `gross_gains_vs_anchored_1`, `gross_losses_vs_anchored_1`, `isolated_source_lines`.
- `cases[].structure.selected_windows`: path, số dòng bắt đầu/kết thúc đã hiển thị (không chứa gold labels).
- `controls_identical_to_saved_p11=true`: đối chứng của cùng bộ 13 case được lấy nguyên trạng từ report có hash được xác minh.

## Giới hạn

- Các câu hỏi Click được tự biên soạn có thể có bias với tên API và đã được phân tích. Mọi cải thiện trên Click vẫn cần được xác nhận ở bộ task độc lập mới.
- Không nên nâng ngân sách hoặc sửa tham số `(8,12)` sau khi xem P1.14 rồi công bố lại là held-out trên Click.
- `complete-span` khó đạt với gold spans dài đến 23 dòng trong ngân sách 3.000 ký tự; không nên cho rằng full coverage bằng 0 tự động là bug.
- Output hiện là **retrieval evidence**, không phải độ chính xác câu trả lời/citation do LLM tạo ra.
