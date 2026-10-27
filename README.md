# Local AI Code Investigation Agent — v4.16

**Chạy hoàn toàn local · Python + Ollama · Windows · Không cần cloud AI · Read-only đối với source**

## 🚀 MÌ ĂN LIỀN — 1 LỆNH CHÍNH

Mở **PowerShell trong thư mục chứa `agent.py`**, thay đường dẫn project và output cho phù hợp:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --out "D:\AgentOutput\architecture"
```

**Lệnh này làm tất cả:** quét kiến trúc → tạo Draw.io → sinh tối đa 20 câu hỏi có bằng chứng → Qwen local xếp hạng → tự điều tra **Top 5** → tạo Markdown/SVG/Draw.io theo từng câu hỏi → tổng hợp báo cáo hệ thống. Mặc định có checkpoint, giới hạn lượt gọi Qwen và lưu file trung gian trong `middle-files/`.

**Mở kết quả đầu tiên:** `D:\AgentOutput\architecture\system_knowledge_report.md` (tổng hợp), `suggested_investigations.md` (câu hỏi), `investigations\index.md` (các báo cáo điều tra) và `system_knowledge.drawio` (sơ đồ).

### 5 lệnh thường dùng nhất

**1. Chỉ xem kiến trúc và 20 câu hỏi — không chạy AI:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

**2. Điều tra một câu hỏi bất kỳ — dùng Qwen local mặc định:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Nếu sửa saveOrder thì ảnh hưởng màn hình nào?" --out "D:\AgentOutput\architecture"
```

**3. Tự điều tra Top 10 thay vì Top 5:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 10 --out "D:\AgentOutput\architecture"
```

**4. Tự điều tra nhưng không tổng hợp cuối:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top --non-synthesize --out "D:\AgentOutput\architecture"
```

**5. Chỉ tổng hợp lại các tài liệu đã có:**

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" synthesize --out "D:\AgentOutput\architecture"
```

> **Để chạy lệnh AI lần đầu:** cài [Ollama](https://ollama.com/download/windows), chạy `ollama pull qwen3:8b`. Kiểm tra với `py -3 agent.py --project ".\sample_project" doctor --probe`. Python 3.11+; không cần Node.js. Lệnh `architecture` không có `--auto-investigate-top` không gọi Qwen.

### Muốn bỏ bước nào? Dùng `--non-*`

| Cờ | Tác dụng |
|---|---|
| `--non-synthesize` | Bỏ tổng hợp cuối |
| `--non-ai-suggestions` | Bỏ Qwen xếp hạng câu hỏi; vẫn sinh ứng viên dựa trên source |
| `--non-review` | Bỏ các vòng phản biện bổ sung |
| `--non-investigation-review` | Bỏ vòng review điều tra |
| `--non-synthesis-review` | Bỏ vòng review báo cáo tổng hợp |
| `--non-markdown` | Không tạo Markdown từng investigation |
| `--non-diagram` | Không vẽ sơ đồ điều tra riêng |
| `--non-update-drawio` | Không tạo Draw.io kiến trúc có chú thích |

Mặc định `--auto-investigate-top` **không cần nhập số = Top 5**. Có thể chỉ định 1–20. Nếu chỉ gọi `investigate`, dùng `--non-ai` để tìm evidence mà không gọi Qwen. Các lệnh cần dùng chung `--out` để đọc đúng index và kết quả đã tạo.

### Đọc output ở đâu?

```text
D:\AgentOutput\architecture\
├── architecture.md / architecture.drawio
├── suggested_investigations.md
├── investigations\index.md
├── investigations\INV-001\result.md
├── investigations\INV-001\investigation.drawio / investigation.svg
├── system_knowledge_report.md
├── system_knowledge.drawio / system_knowledge.svg
└── middle-files\           # JSON, SQLite, CSV, cache, checkpoint, logs
```

**Độ tin cậy:** quan hệ call/FE→BE→SQL suy ra từ phân tích tĩnh hoặc heuristic **không phải chứng minh runtime**. Kết luận không đủ bằng chứng phải được đánh dấu chưa xác minh. Dự án source không được gửi tới cloud AI.

---

## Mục lục hướng dẫn đầy đủ

- [Cài đặt Windows](#2-yêu-cầu-và-cài-đặt)
- [Workflow chi tiết](#3-quy-trình-sử-dụng-khuyến-nghị)
- [Danh sách toàn bộ lệnh](#4-danh-sách-lệnh)
- [File đầu ra](#5-file-đầu-ra)
- [Cơ chế điều tra](#6-agent-điều-tra-như-thế-nào)
- [Cấu hình và giới hạn](#7-cấu-hình-hiệu-năng-và-lưu-ý)
- [Xử lý lỗi và test](#8-xử-lý-sự-cố-và-kiểm-thử)
- [Tài liệu kỹ thuật](#9-tài-liệu-chuyên-sâu)

## 2. Yêu cầu và cài đặt

- **Windows 10/11**, PowerShell; VS Code tùy chọn.
- **Python 3.11+**. Đường chạy mặc định dùng **Python standard library**, không yêu cầu Node.js, Docker hay dịch vụ cloud.
- **Ollama cho Windows** và model `qwen3:8b` khi dùng AI. Các tác vụ quét/graph cơ bản vẫn chạy được khi chưa bật Ollama.
- RAM còn trống phải đủ cho model và KV cache; `num_ctx=2048` là thiết lập mặc định nhằm giảm áp lực bộ nhớ, không bảo đảm chạy được trên mọi máy.

### Lấy source và kiểm tra Python

```powershell
git clone https://github.com/v-h-giang/Local-AI-Code-Investigation-Agent.git
cd Local-AI-Code-Investigation-Agent
py -3 --version
```

Nếu đã clone trước đó, dùng `git pull origin main` trong thư mục repository.

### Cài Ollama khi cần điều tra bằng AI

1. Tải Ollama từ <https://ollama.com/download/windows> và chạy ứng dụng.
2. Cài model:

```powershell
ollama pull qwen3:8b
ollama list
```

3. Kiểm tra agent và khả năng sinh nội dung:

```powershell
py -3 agent.py --project ".\sample_project" doctor
py -3 agent.py --project ".\sample_project" doctor --probe
```

`doctor` kiểm tra trạng thái kết nối; `--probe` thực sự gọi model để tạo một phản hồi ngắn. Nếu service chưa chạy, hãy khởi động Ollama. Không chạy hai server cùng chiếm port `11434`.

### Thử với sample repository

```powershell
py -3 agent.py --project ".\sample_project" architecture --out ".\output\demo-architecture"
py -3 agent.py --project ".\sample_project" investigate "Tìm nơi xử lý đơn hàng và SQL liên quan" --out ".\output\demo-architecture"
```

Lệnh thứ hai cần Ollama; lệnh đầu tiên không cần, trừ khi bật `--ai-summary` hoặc `--auto-investigate-top`.

## 3. Quy trình sử dụng khuyến nghị

**Lần đầu:** `architecture` → đọc `architecture.md`, `module_summary.md`, `suggested_investigations.md` → chọn câu hỏi → chạy `investigate`.

**Khi cần phân tích sâu:** tăng `--max-steps` (tối đa 6), giữ `--budget` phù hợp context; hoặc dùng `--auto-investigate-top` để tự xếp hạng, điều tra Top 5 và tổng hợp toàn hệ thống. Nhập `N` sau cờ nếu muốn xử lý số lượng khác.

**Khi source thay đổi:** chạy lại `architecture` hoặc `intelligence` để cập nhật chỉ mục. Index tăng dần dựa trên đường dẫn/kích thước/mtime; nếu nội dung thay đổi nhưng metadata vẫn giữ nguyên, có thể cần xóa index tương ứng và xây lại.

**Tách riêng 2 dạng AI trong `architecture`:**

```powershell
# Qwen tóm tắt từng module (không tự điều tra câu hỏi)
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-summary --out "D:\AgentOutput\architecture"

# Kết hợp tóm tắt module và tự điều tra Top 3
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-summary --auto-investigate-top 3 --out "D:\AgentOutput\architecture"
```

## 4. Danh sách lệnh

Các tùy chọn **chung** như `--project`, `--model`, `--host`, `--num-ctx`, `--timeout` được đặt **trước tên lệnh**. Các tùy chọn riêng như `--out`, `--budget`, `--max-steps` đặt **sau tên lệnh**.

### Nhóm kiến trúc và điều tra

| Lệnh | Tác dụng | Qwen |
|---|---|---|
| `architecture` | Quét kiến trúc, Draw.io, module summary, index và Top 20 suggestions | Không, trừ khi có flag AI |
| `architecture --ai-summary` | Tóm tắt module với Qwen | Có |
| `architecture --auto-investigate-top [N]` | Xếp hạng, tự điều tra Top 5 (hoặc N), tự tổng hợp hệ thống | Có |
| `intelligence` | Tạo/cập nhật SQLite index cho symbol, references, graph, SQL | Không |
| `investigate "câu hỏi"` | Agent điều tra nhiều vòng có Qwen | **Có (mặc định)** |
| `investigate "câu hỏi" --non-ai` | Chỉ tìm evidence bằng từ khóa/index | Không |
| `symbol NAME` | Tra khai báo và tham chiếu ứng viên | Không |
| `trace NAME` | Duyệt caller/callee ứng viên; `--direction in/out` | Không |
| `impact NAME` | Duyệt phụ thuộc ngược, khoanh vùng ảnh hưởng có thể xảy ra | Không |
| `flows` | Liệt kê dấu hiệu FE/BE/SQL và liên kết heuristic | Không |
| `clusters` | Nhóm thành phần có liên kết trong static graph | Không |
| `history` / `diff-impact` | Đọc lịch sử Git / tác động từ Git diff cục bộ | Không |

Ví dụ các lệnh chuyên biệt (yêu cầu đã chạy `intelligence` hoặc `architecture` với cùng `--out`):

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" symbol OrderService --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" trace processOrder --depth 3 --direction out --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" impact saveOrder --depth 4 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" flows --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" history --file backend/OrderService.java --limit 10 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" diff-impact --base HEAD~1 --head HEAD --out "D:\AgentOutput\architecture"
```

`history` và `diff-impact` cần source là một Git working tree có lịch sử/ref tương ứng. Những lệnh kỹ thuật này **không thay thế AI**: chúng trả dữ liệu phân tích tĩnh để bạn hoặc `investigate` xem xét.

### Các lệnh bổ sung

| Lệnh | Ghi chú |
|---|---|
| `search QUERY` / `refs NAME` / `read PATH` | Tìm text/reference, đọc dòng source không cần AI |
| `index` | Buộc xây lại SQLite FTS search index cho các chức năng tìm kiếm truyền thống |
| `ask "câu hỏi"` / `chat` | Chế độ hỏi đáp/terminal tương tác dùng Ollama |
| `overview` | Khảo sát toàn repo không AI; `overview --ai` bật AI |
| `report --topic ...` | Xuất inventory và Draw.io tham chiếu tĩnh |
| `design --topic "..."` | Tạo thiết kế theo chủ đề với Ollama |
| `design` (không `--topic`) | Khảo sát toàn repo và viết báo cáo AI có resume/checkpoint |
| `vectorize` / `semantic` | Embedding và vector similarity *tùy chọn*, dùng model Ollama embedding riêng |
| `doctor --probe` | Kiểm tra Ollama bằng yêu cầu sinh văn bản |

Để thử embedding cục bộ (không mặc định):

```powershell
ollama pull nomic-embed-text
py -3 agent.py --project "D:\Work\LegacyProject" vectorize --embedding-model nomic-embed-text --max-symbols 200 --out "D:\AgentOutput\architecture"
py -3 agent.py --project "D:\Work\LegacyProject" semantic "find order validation" --embedding-model nomic-embed-text --out "D:\AgentOutput\architecture"
```

## 5. File đầu ra

Các báo cáo dành cho người đọc ở cấp đầu ra chính; toàn bộ **JSON, CSV, cache, checkpoint, registry** được lưu trong `middle-files/`.

```text
D:\AgentOutput\architecture\
├── architecture.md
├── architecture.drawio                    # Gốc: không bị ghi đè theo mặc định
├── architecture.investigated.drawio       # Bản có highlight tích lũy
├── module_summary.md
├── stack_architecture.md
├── frontend_architecture.drawio
├── frontend_architecture.investigated.drawio
├── backend_architecture.drawio
├── backend_architecture.investigated.drawio
├── fe_be_architecture.drawio
├── fe_be_architecture.investigated.drawio
├── frontend_reference.drawio
├── frontend_reference.investigated.drawio
├── backend_reference.drawio
├── backend_reference.investigated.drawio
├── suggested_investigations.md
├── system_knowledge_report.md              # Tổng hợp sau auto-investigate-top
├── system_knowledge.drawio
├── system_knowledge.svg
├── investigations\
│   ├── index.md                          # Tự sinh khi dùng --auto-investigate-top
│   ├── INV-001\
│   │   ├── result.md                     # Kết luận + file:line + bước điều tra
│   │   ├── investigation.drawio          # Sơ đồ chỉ có evidence thật
│   │   └── investigation.svg             # Preview bên trong result.md
│   └── INV-Q-<hash>\                     # Câu hỏi chạy bằng investigate trực tiếp
│       ├── result.md
│       ├── investigation.drawio
│       └── investigation.svg
└── middle-files\
    ├── architecture.json
    ├── stack_architecture.json
    ├── module_summary.json
    ├── code_intelligence.sqlite
    ├── suggested_investigations.json
    ├── investigation_annotations.json    # Các highlight tích lũy
    ├── investigations\
    │   ├── INV-001.json                  # Kết quả máy đọc
    │   ├── INV-001.evidence.csv
    │   └── manifest.json
    ├── drawio-baselines\                  # Chỉ khi dùng --overwrite-drawio
    ├── workflow\                           # state, config, LLM-call audit, cache
    ├── synthesis\                          # claim ledger, checkpoints, review logs
    └── .module_summary_cache\
```

File `.investigated.drawio` chỉ được tạo khi bản `.drawio` gốc tương ứng đã tồn tại. Nếu chỉ chạy `intelligence` mà chưa chạy `architecture`, bạn vẫn có thể xuất sơ đồ riêng cho câu hỏi, nhưng chưa thể chú thích sơ đồ kiến trúc chưa có.

**Ý nghĩa màu sắc:** Box theo tầng FE/BE/DB; viền xanh là node liên quan đến bằng chứng; đầu mũi tên xanh chỉ xuất hiện nếu có **cạnh tĩnh đúng giữa các file được dẫn chứng**. Nét đứt trong Reference tiếp tục biểu thị cấu trúc tham khảo, không phải runtime call. Sơ đồ không tự nối FE → BE → SQL nếu thiếu bằng chứng quan hệ.

**Các tùy chọn giảm bớt của `investigate` và `architecture --auto-investigate-top [N]`:**

| Cờ | Tác dụng |
|---|---|
| `--non-markdown` (`--no-markdown`) | Không tạo Markdown cho từng investigation (không ảnh hưởng `architecture.md`) |
| `--non-diagram` (`--no-diagram`) | Không sinh `investigation.drawio` riêng |
| `--non-update-drawio` (`--no-update-drawio`) | Không cập nhật bản `.investigated.drawio` |
| `--diagram-type auto\|flow\|impact\|symbol` | Chọn hướng bố trí sơ đồ; không thay đổi các liên kết từ source |
| `--overwrite-drawio` | Ghi đè `.drawio` gốc **chỉ khi chủ động yêu cầu**, backup ở `middle-files/drawio-baselines/` |

Riêng `architecture --auto-investigate-top [N]`, có thêm `--non-synthesize`, `--non-ai-suggestions`, `--non-review`, `--non-investigation-review` và `--non-synthesis-review`. Xem [README_V416.md](README_V416.md).

Mở Draw.io tại [diagrams.net](https://app.diagrams.net) → File → Open From → Device. Các file `.drawio` vẫn có thể chỉnh sửa từng node.

Chỉ mục SQLite phục vụ `index`, `chat`, `design` còn được quản lý riêng ở `%USERPROFILE%\.local_code_agent\index\`, khác với `middle-files\code_intelligence.sqlite`.

## 6. Agent điều tra như thế nào?

```text
Source files
   │
   ├── Static scanner → Architecture graph / Draw.io
   └── Symbol + reference extraction → SQLite FTS5 / relations / SQL hints
                                      │
Question → Qwen investigation plan ───┤
                                      ▼
                         Read-only tools + evidence
                           symbol / trace / impact
                           flows / search / history
                                      │
                         Qwen chọn bước tiếp theo
                           (tối đa --max-steps)
                                      │
                                      ▼
                          Qwen tóm tắt kết quả
                           kèm evidence file:line
```

- **Symbol extraction:** có adapter Tree-sitter *nếu đã cài grammar tương ứng*; mặc định có lexical parser dự phòng, không phải Java LSP đầy đủ.
- **References / caller–callee:** phần lớn là các quan hệ **ứng viên** được ghép từ cú pháp/tên, chưa giải quyết đầy đủ overload, dependency injection, dynamic dispatch hoặc reflection.
- **FE → BE → SQL:** có thể tìm dấu hiệu `RemoteObject`, Java class và mapper SQL, nhưng không chứng minh được endpoint mapping hay đường thực thi runtime.
- **Retrieval:** SQLite FTS5/BM25, symbol và graph chọn một tập evidence có giới hạn; `--non-ai` chỉ trả retrieval, không suy luận nghiệp vụ.
- **AI investigation:** Qwen được phép gọi các công cụ điều tra trong allowlist theo nhiều bước (mặc định 4, tối đa 6). Kết luận thiếu bằng chứng phải được ghi là chưa xác minh. Việc có `file:line` không tự động bảo đảm kết luận AI chính xác.
- **Suggestions:** bộ xếp hạng heuristic xác định những câu hỏi có dấu hiệu source. `--auto-investigate-top` tự dùng Qwen để xếp hạng và điều tra Top 5, sau đó tổng hợp hệ thống.

## 7. Cấu hình, hiệu năng và lưu ý

| Tùy chọn chung | Mặc định | Ý nghĩa |
|---|---|---|
| `--model` | `qwen3:8b` | Model AI chạy cục bộ |
| `--host` | `http://127.0.0.1:11434` | Chỉ chấp nhận HTTP loopback |
| `--num-ctx` | `2048` | Context cho Ollama |
| `--timeout` | `240` | Timeout HTTP, giây |
| `investigate --budget` | `1200` | Giới hạn evidence cung cấp cho agent |
| `investigate --max-steps` | `4` | Tối đa 1–6 bước điều tra |

Ví dụ đổi cấu hình:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 --timeout 240 investigate "Giải thích logic lưu đơn hàng" --max-steps 4 --out "D:\AgentOutput\architecture"
```

**Hiệu năng:** Quét và lập chỉ mục là xử lý nội bộ; các câu hỏi Qwen có thể cần nhiều lượt sinh nội dung. Với project lớn, mặc định Top 5 sẽ chạy nhiều lượt Ollama tuần tự; có thể thử `--auto-investigate-top 1` để kiểm tra chất lượng trước. Không nên coi Top 20 là 20 kết luận đã được xác minh.

**Bảo mật:** Công cụ đọc source và ghi index/báo cáo bên ngoài source; Qwen không được cung cấp công cụ thực thi shell tùy ý, sửa source hay chạy SQL. Code, log, output và SQLite vẫn có thể chứa thông tin nhạy cảm — tránh commit hoặc chia sẻ các file được sinh từ dự án nội bộ. Ollama được ràng buộc kết nối HTTP localhost.

## 8. Xử lý sự cố và kiểm thử

| Triệu chứng | Kiểm tra / cách xử lý |
|---|---|
| `Ollama not reachable` | Mở Ollama; chạy `ollama list`, sau đó `doctor --probe` |
| Model không tồn tại | `ollama pull qwen3:8b`; kiểm tra đúng `--model` |
| Hết RAM / trả lời chậm | Giữ `--num-ctx 2048`, giảm `--max-steps`, thử 1 auto investigation |
| `Code intelligence index absent` | Chạy `architecture` hoặc `intelligence` với **đúng `--out`** |
| Source đã thay đổi nhưng index chưa nhận | Chạy lại `intelligence`/`architecture`; nếu timestamp/size không đổi, cân nhắc xây lại riêng index |
| Không tìm thấy evidence | Kiểm tra tên class, mapper/config bị bỏ qua; mở kết quả `symbol`, `flows`, `search` để đối chiếu |
| Một auto investigation lỗi | Mở `middle-files/investigations/manifest.json` và `middle-files/investigations/INV-xxx.json`; các câu còn lại vẫn có thể được chạy |
| File Draw.io có đường chéo hoặc chồng nhau | Dữ liệu graph lớn có thể vượt khả năng layout mặc định; sắp xếp lại trong diagrams.net |

Chạy bộ test từ thư mục chứa `agent.py`:

```powershell
py -3 -m unittest discover -s tests -v
```

**Mã thoát CLI:** `0` thường là thành công; `1` cho lỗi đầu vào/Ollama hoặc I/O được xử lý; `2` có thể biểu thị auto-investigation thất bại một phần hoặc tác vụ overview/design chưa hoàn tất. Luôn đọc JSON và thông báo lỗi thực tế thay vì dựa vào mã thoát đơn lẻ.

## 9. Tài liệu chuyên sâu

- [v4.14 — Investigation Reports & Annotated Draw.io](README_V414.md): Markdown, sơ đồ chứng cứ, cập nhật kiến trúc và `middle-files/`.
- [v4.16 — One-switch automatic workflow](README_V416.md): mặc định tốt nhất cho `--auto-investigate-top`, các tùy chọn `--non-*`.
- [v4.15 — Local multi-loop workflow](README_V415.md): thiết kế nhiều vòng với Qwen local.
- [v4.13 — Suggested Investigations](README_V413.md): Top 20, hai nhóm câu hỏi và `--auto-investigate-top`.
- [v4.12 — Iterative Investigation](README_V412.md): Qwen chọn công cụ nhiều vòng, kiểm tra evidence.
- [Code Intelligence](README_CODE_INTELLIGENCE.md): symbol, trace, impact, flows, history và vector search.
- [Architecture & Module Summary](README_ARCHITECTURE.md): cách trích xuất graph và tóm tắt module.
- [FE/BE/DB Stack & Draw.io](README_STACK_ARCHITECTURE.md): framework, database và sơ đồ Reference.
- [Draw.io Layout v4.8](README_V48.md): lane, nhóm framework, màu và đường nối.
- [Legacy v4 / Full Repository Scan](README_V4.md): các workflow `design`, `overview` và checkpoint lịch sử.

> **README này là hướng dẫn sử dụng chính cho v4.14.** Các tài liệu theo phiên bản được giữ làm chi tiết kỹ thuật hoặc lịch sử thay đổi; khi ví dụ cũ xung đột với CLI hiện tại, ưu tiên `py -3 agent.py --help` và trợ giúp của từng lệnh.
