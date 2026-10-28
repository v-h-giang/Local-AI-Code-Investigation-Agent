# Local AI Code Investigation Agent

**v4.17 · Phân tích codebase bằng AI cục bộ · Python + Ollama · Windows / VS Code · Chỉ đọc source**

**Ngôn ngữ:** [English](README.md) · Tiếng Việt

## Mì ăn liền — một lệnh chính

Mở PowerShell tại thư mục chứa `agent.py`, sau đó thay hai đường dẫn cho phù hợp:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --out "D:\AgentOutput\architecture"
```

**Lệnh này làm gì?** Quét source → tạo sơ đồ kiến trúc FE/BE/DB → sinh tối đa **20 câu hỏi có bằng chứng source** → dùng Qwen local xếp hạng → điều tra **Top 5** → xuất HTML/SVG/Draw.io theo từng câu → tổng hợp báo cáo toàn hệ thống. Mọi file trung gian, checkpoint và log nằm trong `middle-files/`.

**Mặc định xuất HTML** để mở ngay trên trình duyệt (`system_knowledge_report.html`). Python đưa nội dung vào template HTML có sẵn nên **không phát sinh thêm token Ollama để làm giao diện**. Muốn lấy Markdown, thêm `--report-format md`; muốn cả hai, chọn `--report-format both`. Draw.io sẽ tách điểm neo đầu/đuôi mũi tên trên từng box, chỉ dùng chung khi các vị trí còn trống đã hết.

```powershell
# Xuất cả HTML lẫn Markdown
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top max --report-format both --out "D:\AgentOutput\architecture"
```

**Muốn chạy toàn bộ câu hỏi đã sinh (tối đa 20):**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top max --out "D:\AgentOutput\architecture"
```

`max` nghĩa là chạy **tất cả câu hỏi hợp lệ thực sự được sinh**, không nhất thiết đủ 20. Giới hạn mặc định là 160 lượt gọi Ollama cho Top 5 và 370 cho `max`; đây là hạn mức trên, không phải số lượt bắt buộc sử dụng. Chạy toàn bộ trên project lớn có thể mất nhiều thời gian.

**Nên mở file nào trước?** `system_knowledge_report.html` (báo cáo tổng thể), `suggested_investigations.html` (câu hỏi), `investigations/index.html` (mục lục điều tra), `system_knowledge.drawio` (sơ đồ có thể chỉnh sửa).

### Năm lệnh thường dùng nhất

Tất cả các lệnh dưới đây chạy từ thư mục chứa `agent.py`.

**1. Chỉ quét kiến trúc và sinh câu hỏi, không gọi Qwen:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

**2. Điều tra một câu hỏi bằng Qwen local (mặc định):**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Nếu sửa saveOrder thì ảnh hưởng những màn hình nào?" --out "D:\AgentOutput\architecture"
```

**3. Tự điều tra Top 10:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 10 --out "D:\AgentOutput\architecture"
```

**4. Điều tra Top 5 nhưng bỏ bước tổng hợp cuối:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --non-synthesize --out "D:\AgentOutput\architecture"
```

**5. Chỉ tổng hợp lại các báo cáo đã có:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" synthesize --out "D:\AgentOutput\architecture"
```

> **Cài đặt lần đầu:** Cần [Python 3.11+](https://www.python.org/downloads/windows/) và [Ollama trên Windows](https://ollama.com/download/windows), sau đó chạy `ollama pull qwen3:8b`. Không cần Node.js hoặc cloud AI. Lệnh `architecture` không kèm cờ AI vẫn chạy không cần Qwen.

## Cài đặt trên Windows

```powershell
# Tải source agent
git clone https://github.com/v-h-giang/Local-AI-Code-Investigation-Agent.git
cd Local-AI-Code-Investigation-Agent
py -3 --version

# Chỉ cần khi sử dụng chức năng AI
ollama pull qwen3:8b
ollama list

# Kiểm tra kết nối và thử sinh phản hồi
py -3 agent.py --project ".\sample_project" doctor --probe
```

Nếu Ollama chưa hoạt động, mở ứng dụng Ollama. `doctor --probe` thực sự gọi model; `doctor` không kèm `--probe` chỉ kiểm tra tình trạng kết nối. Có thể thử project mẫu mà không cần AI:

```powershell
py -3 agent.py --project ".\sample_project" architecture --out ".\output\sample-architecture"
```

Đã clone trước đó thì chạy `git pull origin main`. Tham số `--project` là **đường dẫn thư mục source trên máy**, không phải GitHub URL. Nên đặt thư mục `--out` bên ngoài source cần phân tích.

## Các chế độ hoạt động

| Lệnh | Chức năng | Cần Ollama? |
|---|---|---|
| `architecture` | Quét kiến trúc, Draw.io, module, index và tối đa 20 câu hỏi | Không |
| `architecture --auto-investigate-top` | Toàn bộ workflow: xếp hạng, Top 5, sơ đồ, tổng hợp | Có |
| `architecture --auto-investigate-top N` | Workflow đầy đủ cho Top N (`1`–`20`) | Có |
| `architecture --auto-investigate-top max` | Workflow cho tất cả câu hỏi được sinh (tối đa 20) | Có |
| `architecture --ai-suggestions` | Qwen chấm điểm/phản biện câu hỏi, chưa tự điều tra | Có |
| `architecture --ai-summary` | Qwen tóm tắt từng module | Có |
| `investigate "câu hỏi"` | Điều tra nhiều bước và xuất báo cáo dễ đọc | Có, mặc định |
| `investigate "câu hỏi" --non-ai` | Chỉ truy xuất bằng chứng dạng lexical | Không |
| `synthesize` | Tổng hợp phân cấp từ các tài liệu đã tạo | Có |

20 câu hỏi được phân thành **Business Flows** và **Technical Architecture**. Nếu source không đủ bằng chứng, agent sinh ít hơn 20 câu thay vì tự tạo nội dung không tồn tại. Khi bật AI ranking, Qwen chỉ xếp hạng các ứng viên đã được Python tìm thấy từ source.

### Muốn bỏ bước nào thì dùng `--non-*`

| Cờ | Tác dụng |
|---|---|
| `--non-synthesize` | Bỏ tổng hợp tài liệu hệ thống cuối |
| `--non-ai-suggestions` | Bỏ Qwen xếp hạng, vẫn sinh câu hỏi có căn cứ từ source |
| `--non-review` | Bỏ các lượt phản biện bổ sung ở cả ba giai đoạn |
| `--non-investigation-review` | Bỏ vòng review bằng chứng trong investigation |
| `--non-synthesis-review` | Bỏ vòng review khi tổng hợp hệ thống |
| `--non-markdown` | Không xuất Markdown ở chế độ `md`; không tắt HTML trong chế độ HTML |
| `--non-diagram` | Không tạo Draw.io riêng cho từng investigation |
| `--non-update-drawio` | Không tạo bản sơ đồ kiến trúc có chú thích |

Riêng lệnh `investigate`, dùng `--non-ai` để tắt hoàn toàn Qwen. Lệnh `architecture` bình thường không tự bật AI khi không có cờ tương ứng.

### Tùy chỉnh thường dùng

```powershell
# Tăng số bước điều tra cho một câu hỏi (1–6)
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Truy vết luồng đặt hàng FE đến BE và SQL" --max-steps 6 --budget 1200 --out "D:\AgentOutput\architecture"

# Chạy workflow nhưng bỏ sơ đồ riêng từng câu
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 5 --non-diagram --out "D:\AgentOutput\architecture"
```

Tham số **chung** phải đặt **trước tên lệnh**: `--model` (mặc định `qwen3:8b`), `--host` (`http://127.0.0.1:11434`), `--num-ctx` (`2048`), `--timeout` (`240` giây). Tham số riêng như `--out`, `--budget`, `--max-steps`, `--max-llm-calls` đặt **sau tên lệnh**.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 architecture --auto-investigate-top max --out "D:\AgentOutput\architecture"
```

Một lần `investigate` mặc định có `--max-steps 4`, `--review-rounds 1` và `--max-llm-calls 80`. Xếp hạng câu hỏi mặc định 2 lượt và tổng hợp có 2 lượt review. Các lời gọi Qwen được xử lý tuần tự để phù hợp máy hạn chế RAM; workflow có checkpoint và tái sử dụng cache khi có thể.

## Kết quả được lưu ở đâu?

```text
D:\AgentOutput\architecture\
├── architecture.html
├── architecture.drawio
├── architecture.investigated.drawio
├── module_summary.html
├── stack_architecture.html
├── frontend_architecture.drawio
├── backend_architecture.drawio
├── fe_be_architecture.drawio
├── frontend_reference.drawio
├── backend_reference.drawio
├── suggested_investigations.html
├── system_knowledge_report.html
├── system_knowledge.drawio
├── system_knowledge.svg
├── investigations\
│   ├── index.html
│   ├── INV-001\
│   │   ├── result.html
│   │   ├── investigation.drawio
│   │   └── investigation.svg
│   └── ...
└── middle-files\
    ├── architecture.json
    ├── code_intelligence.sqlite
    ├── suggested_investigations.json
    ├── investigation_annotations.json
    ├── investigations\          # JSON / CSV chứng cứ / manifest
    ├── workflow\                # cấu hình / trạng thái / audit / cache
    ├── synthesis\               # claim / tóm tắt trung gian / checkpoint
    ├── report-sources\          # Markdown trung gian khi mặc định xuất HTML
    ├── drawio-baselines\        # chỉ có nếu chủ động ghi đè sơ đồ gốc
    └── .module_summary_cache\
```

Cây thư mục mang tính minh họa: **file chỉ xuất hiện khi giai đoạn tương ứng đã chạy và có kết quả**. Các sơ đồ FE/BE có thể có thêm bản `.investigated.drawio` nếu đã có sơ đồ kiến trúc phù hợp. HTML/SVG/Draw.io dành cho người đọc nằm ở thư mục ngoài; Markdown trung gian để chạy tổng hợp lại nằm trong `middle-files/report-sources/`, cùng các JSON/CSV/cache/checkpoint.

Mở `.drawio` bằng [diagrams.net](https://app.diagrams.net) hoặc extension tương thích của VS Code. Sơ đồ investigation chỉ thể hiện những quan hệ có bằng chứng tĩnh trong graph. Mặc định sơ đồ gốc được giữ nguyên; bản có chú thích mang hậu tố `.investigated.drawio`. Chỉ dùng `--overwrite-drawio` khi muốn ghi đè có chủ đích; backup được lưu ở `middle-files/drawio-baselines/`.

## Các lệnh điều tra chuyên sâu

Sau khi chạy `architecture` hoặc `intelligence` với cùng `--out`, có thể dùng:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" symbol OrderService --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" trace processOrder --depth 3 --direction out --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" impact saveOrder --depth 4 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" flows --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" clusters --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" history --file backend/OrderService.java --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" diff-impact --base HEAD~1 --head HEAD --out "D:\AgentOutput\architecture"
```

Còn có các lệnh `search`, `refs`, `read`, `index`, `ask`, `chat`, `report`, `overview`, `design`. `vectorize` và `semantic` là tùy chọn dùng **embedding model local** (ví dụ `nomic-embed-text`), không gửi dữ liệu lên cloud. Xem thêm [Code Intelligence](README_CODE_INTELLIGENCE.md).

## Agent hoạt động như thế nào?

```text
Source (Java / SQL / ActionScript / MXML / XML / cấu hình)
      |
      +--> Quét kiến trúc tĩnh --> module + Draw.io chỉnh sửa được
      |
      +--> SQLite symbol/search/dependency index cập nhật tăng dần
                                              |
                      Sinh câu hỏi từ source ---+
                                              |
                                   Qwen local xếp hạng + review
                                              |
                               Điều tra bằng tool qua nhiều vòng
                                              |
                        Kiểm tra chứng cứ + xuất báo cáo dễ đọc
                                              |
                                 Tổng hợp phân cấp cục bộ
                                              |
                         system_knowledge_report.html + Draw.io
```

Python quản lý index, duyệt graph, bằng chứng `file:line`, checkpoint và điều kiện dừng. Qwen thực hiện các tác vụ lập kế hoạch, xếp hạng, diễn giải và tổng hợp nhỏ, có giới hạn số bước/context. Thiết kế nhiều vòng giúp xử lý hệ thống lớn mà không cần đưa toàn bộ source vào một prompt.

**Giới hạn bằng chứng:** Phân tích symbol có thể dùng Tree-sitter nếu được cài, nếu không sẽ dùng lexical parser. Đây không phải Java/ActionScript LSP hoàn chỉnh. Các cạnh call graph, overload, DI, dynamic dispatch, `RemoteObject` và luồng FE → BE → SQL đều có thể chỉ là **quan hệ ứng viên từ phân tích tĩnh**, không phải runtime trace đã chứng minh. Có `file:line` không đồng nghĩa mọi diễn giải nghiệp vụ đều chắc chắn đúng.

**Bảo mật:** Các lời gọi AI hướng tới Ollama qua HTTP loopback. Agent không cấp cho Qwen quyền shell tùy ý, ghi source hoặc thực thi SQL. Dù chạy local, báo cáo và SQLite vẫn có thể chứa thông tin nhạy cảm từ source; không commit hoặc chia sẻ chúng nếu chưa kiểm tra. `git clone`/`git pull` chỉ phục vụ tải source của agent, không phải gửi source dự án cho AI.

## Xử lý sự cố

| Triệu chứng | Kiểm tra |
|---|---|
| Không kết nối được Ollama | Mở Ollama, chạy `ollama list`, `doctor --probe` |
| Chưa có model | `ollama pull qwen3:8b` hoặc chọn model đã tải bằng `--model` |
| Lâu sau bước FE/BE/DB | Xem log `[Suggestions]`, `[Intelligence]`, Qwen ranking; v4.16.1 đã tối ưu FTS và tái sử dụng graph |
| RAM thiếu / model quá chậm | Giữ `--num-ctx 2048`; thử Top 1 hoặc Top 5 trước `max` |
| Chưa có intelligence index | Chạy `architecture` hoặc `intelligence` với đúng `--out` |
| Source thay đổi nhưng index chưa cập nhật | Chạy lại index; nếu size/mtime vẫn giữ nguyên, xây lại chỉ mục tương ứng |
| Một số investigation thất bại | Xem `middle-files/investigations/manifest.json` và `workflow` logs |
| Thiếu bằng chứng quan hệ | Đánh dấu chưa xác minh và kiểm tra `symbol`, `trace`, `flows` |

Mã thoát thường gặp: `0` thành công, `1` lỗi đầu vào/Ollama/I/O, `2` workflow tự động thất bại một phần hoặc tác vụ dài chưa hoàn tất. Nên đọc báo lỗi thực tế thay vì chỉ nhìn mã thoát.

```powershell
# Chạy toàn bộ test
py -3 -m unittest discover -s tests -v

# Xem trợ giúp CLI
py -3 agent.py --help
py -3 agent.py --project ".\sample_project" architecture --help
```

## Tài liệu kỹ thuật theo phiên bản

Các tài liệu sau **giữ nguyên ngôn ngữ hiện tại**, không bị dịch hoặc thay thế trong lần chỉnh README này:

- [v4.17 — HTML reports and distributed Draw.io ports](README_V417.md)
- [v4.16 — Smart workflow defaults](README_V416.md)
- [v4.16.1 — Performance hotfix](README_V4161_PERFORMANCE.md)
- [v4.15 — Local multi-loop workflow](README_V415.md)
- [v4.14 — Markdown / SVG / Annotated Draw.io](README_V414.md)
- [v4.13 — Suggested Investigations](README_V413.md)
- [v4.12 — Iterative Qwen Investigation](README_V412.md)
- [v4.11 — CLI default AI behavior](README_V411.md)
- [Code Intelligence](README_CODE_INTELLIGENCE.md)
- [Architecture and Module Summary](README_ARCHITECTURE.md)
- [FE/BE/DB Stack Architecture](README_STACK_ARCHITECTURE.md)
- [v4.8 Draw.io Layout](README_V48.md)
- [v4 Legacy](README_V4.md)

**Bản hướng dẫn chính hiện tại: v4.17.** Khi tài liệu cũ mâu thuẫn với CLI hiện tại, ưu tiên `py -3 agent.py --help` và `--help` của lệnh tương ứng.
