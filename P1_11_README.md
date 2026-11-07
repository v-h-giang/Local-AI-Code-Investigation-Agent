# P1.11 — Held-out Evidence Evaluation (frozen policies)

## Mục lục

- [Mục tiêu](#mục-tiêu)
- [Tại sao chưa có điểm held-out](#tại-sao-chưa-có-điểm-held-out)
- [Điều kiện đầu vào](#điều-kiện-đầu-vào)
- [Cách chạy PowerShell](#cách-chạy-powershell)
- [Các chỉ số](#các-chỉ-số)
- [Giới hạn và quy tắc đánh giá](#giới-hạn-và-quy-tắc-đánh-giá)

## Mục tiêu

Đánh giá *một lần* các chính sách đã phát triển trên tập case **chưa được dùng trong P1.1–P1.10**, bằng source checkout ở một commit cụ thể, không thay đổi default agent runtime.

Chính sách đóng băng: `baseline`, `adaptive_1`, `merge_balanced(max_block=1)` và `merge_anchored(max_block=1)`. Chung ngân sách **3.000 JSON chars/case**, tối đa **6 excerpts/case**. Dữ liệu nguồn được lấy bằng `Repo.read_file()` và bộ prefetch hiện có; không có yêu cầu tới Ollama sau khi đã lưu cửa sổ candidate.

## Tại sao chưa có điểm held-out

Bộ `benchmark/datasets/benchmark_30.jsonl` hiện chứa **20** RepoContextBench Agent Framework case có gold spans (đã được xem và tối ưu nhiều lần) và **10** StackRepoQA JDBI case **không có gold spans**. Việc chia lại 20 case thành train/test không tạo được tập kiểm định độc lập. P1.11 không xuất một điểm held-out giả từ bộ này.

Các tập ngoài có thể xem xét: RepoContextBench v2 Hard trên `facebook/sapling` khi có nhãn và các candidate window phù hợp; hoặc một bộ nhiệm vụ repository nội bộ mới có gán nhãn thủ công. Nguồn RepoContextBench: https://github.com/CodeAlive-AI/repo-context-bench . Không tự coi các câu hỏi StackRepoQA là có nhãn gold-span.

## Điều kiện đầu vào

1. **JSONL mới**: mỗi dòng có `id`, `suite`, `repo` (GitHub `owner/name`), `commit` (SHA đầy đủ), `question`, `gold_spans` không rỗng. Mỗi span có `id`, `path`, `start_line`, `end_line`. Không được trùng ID/câu hỏi chuẩn hóa với `benchmark_30.jsonl` hoặc các case đã sử dụng khác.
2. **Source-window report mới**: JSON có `suite`, `method.frozen_source_commit`, `cases[]` trùng ID/câu hỏi với JSONL. Mỗi case chứa `variants.hybrid.top8_diagnostics[]` (1–8 cửa sổ với `path`, `line_start`, `line_end`) và `multiwindow_diagnostics.alternates[]` (0–4 cửa sổ với `path`, `start_line`, `end_line`, `new_lines`). Dữ liệu phải được sinh **mà không dùng gold labels để xếp hạng**. Cách sinh candidate cho repository mới là bước upstream riêng; script này **không tự tạo embeddings/candidate windows**.
3. **Checkout thật**: root Git repo, sạch ở tracked files, `HEAD` trùng SHA, `origin` trỏ đúng GitHub `owner/name`. Code không thay đổi checkout.
4. **Các case đã xem bổ sung**: có thể khai báo nhiều `--additional-known-cases path.jsonl`; bộ 30 case mặc định luôn bị loại, không thể thay bằng tùy chọn CLI.

Ví dụ schema *minh họa*, **không phải case thật đã gán nhãn**:

```json
{"id":"new_001","suite":"external","repo":"owner/repo","commit":"0123456789abcdef0123456789abcdef01234567","question":"Where is retry implemented?","gold_spans":[{"id":"E1","path":"src/retry.py","start_line":10,"end_line":12}]}
```

## Cách chạy PowerShell

```powershell
# Tải branch mới
 git switch feature/qwen3-embedding-retrieval
 git pull origin feature/qwen3-embedding-retrieval

# Chạy unit tests (không cần dataset ngoài)
py -3 -m unittest benchmark.tests.test_heldout_evidence_eval -v

# Chỉ chạy khi đã chuẩn bị đúng hai input độc lập và checkout ở SHA cố định
py -3 benchmark/heldout_evidence_eval.py `
  --cases-jsonl "benchmark/datasets/new_heldout.jsonl" `
  --from-report "benchmark/results/_diagnostics/new_heldout_windows.json" `
  --checkout "benchmark/repositories/new_repository" `
  --repository "owner/repo" `
  --commit "0123456789abcdef0123456789abcdef01234567" `
  --out "benchmark/results/_diagnostics/p11_heldout_result.json"
```

Các đường dẫn `new_heldout...` và `owner/repo` ở trên chỉ là **placeholder**, không tồn tại trong repository hiện tại. Nếu case mới chưa có gold spans và candidate windows, không thể chạy benchmark P1.11 thực sự.

## Các chỉ số

- `gold_spans_any_line`: span được tính khi ít nhất một dòng nguồn trong khoảng gold xuất hiện với source ref thật (tương đương cách đo P1.7–P1.10).
- `gold_spans_complete`: chỉ tính khi *tất cả* các dòng trong span có source refs; chặt hơn nhưng có thể thấp khi span rất dài.
- `gross_gains_vs_baseline`, `gross_losses_vs_baseline`, `gross_losses_vs_adaptive_1`: phân tích paired theo case.
- `isolated_source_lines`: dòng không có hàng xóm liên tiếp (n-1 hoặc n+1) trong cùng file; là proxy về sự rời rạc của evidence, **không chứng minh tính đầy đủ ngữ nghĩa**.
- `input_sha256`: định danh file dữ liệu và source-window report. Kết quả đã ghi không được ghi đè bởi CLI.

## Giới hạn và quy tắc đánh giá

- Đầu vào có thể công khai và bị model biết trước; so khớp ID/câu hỏi chính xác không bảo đảm không bị contamination/ngữ nghĩa tương đương.
- `gold_spans_any_line` không phải chất lượng câu trả lời, citation validation hay task pass rate.
- Candidate window report phải có đúng case được đánh giá và không dùng gold để xếp hạng. Script dựng lại chỉ phần tọa độ cửa sổ trước khi gọi selectors; mọi field gold/đánh giá có trong report nguồn đều bị loại khỏi bản dữ liệu đưa vào selector.
- Điểm kiểm định chỉ đáng tin khi các chính sách và tham số đã được khóa **trước** khi xem gold labels của tập mới. Không điều chỉnh chính sách dựa theo kết quả held-out rồi báo lại trên chính tập đó như một kết quả độc lập.
- Không tích hợp vào production runtime và không tạo hoặc cập nhật benchmark result trong Git repository mặc định (đặt report ở thư mục gitignored `benchmark/results`).
