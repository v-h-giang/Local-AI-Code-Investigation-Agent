# P1.12 — External-repository evidence evaluation (Click)

## Mục lục

- [Phạm vi và dữ liệu](#phạm-vi-và-dữ-liệu)
- [Quy tắc kiểm định](#quy-tắc-kiểm-định)
- [Chạy trên Windows PowerShell](#chạy-trên-windows-powershell)
- [Các file tạo ra](#các-file-tạo-ra)
- [Giải thích kết quả và giới hạn](#giải-thích-kết-quả-và-giới-hạn)

## Phạm vi và dữ liệu

Repository nguồn: [`pallets/click`](https://github.com/pallets/click), tại commit **`ac0e297ec2d7d78455a7d18ce306996e668c4a85`**. Bộ P1.12 gồm **13 câu hỏi do dự án tự biên soạn** và **24 gold spans** định vị trực tiếp từ mã nguồn tại commit này. Đây là benchmark bổ sung trên repository khác với 20 RepoContextBench Agent Framework case đã dùng để phát triển; **không phải benchmark chính thức hoặc phép kiểm định độc lập do bên thứ ba tổ chức**.

- `benchmark/datasets/p112_click_questions.jsonl`: chỉ chứa `id`, `suite`, `repo`, `commit`, `question`. Đây là **đầu vào duy nhất** của builder để sinh retrieval candidates.
- `benchmark/datasets/p112_click_labels.jsonl`: thêm `gold_spans` có `id/path/start_line/end_line`. Chỉ đưa vào validator và P1.11 ở giai đoạn đánh giá.
- `benchmark/heldout_window_builder.py`: sử dụng FTS5 file/line, Qwen3-Embedding và RRF đã có trong project, sinh top-8 Hybrid windows cùng tối đa bốn Dense alternate windows (ít nhất 8 dòng mới); định dạng tương thích P1.11.
- `benchmark/heldout_gold_validator.py`: đối chiếu gold spans với source checkout đúng commit, tạo liên kết GitHub để người đánh giá xác nhận tính liên quan ngữ nghĩa.

## Quy tắc kiểm định

1. Khóa source commit, `max_chars=3000`, `limit=6`, `adaptive_1`, `merge_balanced(max_block=1)` và `merge_anchored(max_block=1)` từ trước khi chạy. Không thay đổi mô hình, ranker, heuristic dựa trên điểm P1.12.
2. Sinh candidate windows **chỉ từ question-only manifest**, không đưa gold labels vào pipeline ranking. Builder chặn các trường thừa, bao gồm `gold_spans`, tại đầu vào câu hỏi.
3. Chạy trình xác minh gold spans độc lập; sự tồn tại của dòng là bằng chứng vị trí hợp lệ, **không tự chứng minh gold span có liên quan**. Review link nguồn trước khi xem điểm.
4. Chạy P1.11 và lưu báo cáo mới; không ghi đè kết quả. Nếu tiếp tục tinh chỉnh sau khi xem nhãn/điểm, phải dùng tập dữ liệu khác cho lần kiểm định tiếp theo.
5. Không tự suy đoán điểm từ 20 case cũ; xem riêng `gold_spans_any_line`, `gold_spans_complete`, `isolated_source_lines`, số case có gold, và sai khác paired với baseline.

## Chạy trên Windows PowerShell

Thực hiện tại thư mục gốc `Local-AI-Code-Investigation-Agent`:

```powershell
# 0. Cập nhật code P1.12
 git switch feature/qwen3-embedding-retrieval
 git pull origin feature/qwen3-embedding-retrieval
 py -3 -m unittest benchmark.tests.test_heldout_window_builder benchmark.tests.test_heldout_gold_validator benchmark.tests.test_heldout_evidence_eval -v

# 1. Repository độc lập ở đúng commit nguồn
$source = "benchmark/repositories/click_p112"
git clone https://github.com/pallets/click.git $source
git -C $source checkout --detach ac0e297ec2d7d78455a7d18ce306996e668c4a85

# 2. Lập chỉ mục Code Intelligence từ chính source
$ciRoot = "benchmark/results/_heldout/p112_click_intelligence"
py -3 agent.py --project $source intelligence --out $ciRoot
$ci = "$ciRoot/middle-files/code_intelligence.sqlite"

# 3. Lập vector index bằng Ollama chạy cục bộ; cần sẵn model qwen3-embedding:0.6b
$db = "benchmark/results/_heldout/p112_click_qwen3.sqlite"
py -3 semantic_retrieval.py index `
  --project $source --intelligence-index $ci --db $db `
  --model "qwen3-embedding:0.6b" --dimensions 1024

# 4. Sinh cửa sổ candidates — chỉ đọc question-only manifest
$rev = "ac0e297ec2d7d78455a7d18ce306996e668c4a85"
$windows = "benchmark/results/_diagnostics/p112_click_windows.json"
py -3 benchmark/heldout_window_builder.py `
  --questions-jsonl "benchmark/datasets/p112_click_questions.jsonl" `
  --checkout $source --repository "pallets/click" --commit $rev `
  --intelligence-index $ci --embed-db $db --out $windows

# 5. Đối chiếu vị trí các nhãn với code tại commit đã khóa
py -3 benchmark/heldout_gold_validator.py `
  --questions-jsonl "benchmark/datasets/p112_click_questions.jsonl" `
  --labels-jsonl "benchmark/datasets/p112_click_labels.jsonl" `
  --checkout $source --repository "pallets/click" --commit $rev `
  --out "benchmark/results/_diagnostics/p112_click_gold_validation.json"

# 6. P1.11: Đánh giá bốn chính sách đã khóa; không chạy lại nếu chỉ muốn phân tích report
py -3 benchmark/heldout_evidence_eval.py `
  --cases-jsonl "benchmark/datasets/p112_click_labels.jsonl" `
  --from-report $windows --checkout $source `
  --repository "pallets/click" --commit $rev `
  --out "benchmark/results/_diagnostics/p112_click_p11_evaluation.json"
```

Nếu `$source` đã tồn tại, thay `git clone` bằng `git -C $source fetch origin`, sau đó checkout đúng commit. **Không tự chỉnh sửa** source checkout. Nếu file output đã tồn tại, chọn tên mới thay vì xóa báo cáo đã tạo.

## Các file tạo ra

| File | Nội dung |
|---|---|
| `p112_click_windows.json` | Tọa độ top-8 Hybrid và Dense alternates; không chứa gold labels |
| `p112_click_gold_validation.json` | Kiểm chứng vị trí và link source cho 24 gold spans |
| `p112_click_p11_evaluation.json` | Bảng chấm điểm P1.11 trên 13 case mới; dùng để so sánh bốn chính sách |

Báo cáo sinh ra trong `benchmark/results` (thư mục gitignored). Không commit cache/index embeddings hoặc điểm đánh giá để tránh nhầm là kết quả có sẵn.

## Giải thích kết quả và giới hạn

- **Không so sánh trực tiếp** tỷ lệ `x/24` của Click với `12/99` của RepoContextBench như thể chúng có cùng phân phối nhiệm vụ; hai bộ khác repository, câu hỏi và độ dài gold spans.
- 13 câu hỏi được viết dựa trên mã Click, vì vậy có thể dễ hơn câu hỏi của người dùng thực tế hoặc bị thiên lệch về tên API. Reviewer độc lập nên rà soát nhãn; muốn kết quả mạnh hơn, phải bổ sung nhiều task độc lập khác.
- Gold-span overlap chỉ chứng minh một hoặc tất cả dòng được hiển thị, **không đo** correctness của câu trả lời, suy luận nhiều bước hoặc citation cuối cùng. Đây là một bước kiểm định evidence, chưa phải đánh giá agent end-to-end.
- Candidate builder dùng chính các hàm `search_file_candidates`, `search_relevant_sources`, `dense_search`, `_rrf` hiện hữu. Khác P1.5, input chưa được index/embedding ở đây, nên cần chạy bước 2–4 một lần trên Windows với Ollama.
- Đối chiếu nguồn và label được thực hiện trên commit đã khóa. Nếu một span cần chỉnh vì annotation sai sau khi xem điểm, công bố lỗi annotation và đánh giá lại trên một tập mới.
