# Local AI Code Investigation Agent

**Phiên bản hiện tại: v4.13 · Python · Windows · Ollama cục bộ · Read-only đối với source**

Công cụ hỗ trợ **khảo sát kiến trúc và điều tra source code legacy** (Java, Adobe Flex/AIR, ActionScript, MXML, XML mapper, SQL). Agent kết hợp phân tích tĩnh, chỉ mục SQLite, graph quan hệ và **Qwen chạy qua Ollama trên máy của bạn** để tìm bằng chứng, truy vết các quan hệ ứng viên và trả lời câu hỏi bằng ngôn ngữ tự nhiên.

> **Phạm vi độ tin cậy:** Agent không thực thi ứng dụng, không kết nối vào database nghiệp vụ và **không tạo được runtime call graph đã xác minh**. Những quan hệ suy ra từ tên, import hoặc cấu hình phải được xem là *static/heuristic candidates*, không phải chứng minh hành vi thực tế.

## Mục lục

1. [Bắt đầu nhanh](#1-bắt-đầu-nhanh)
2. [Yêu cầu và cài đặt](#2-yêu-cầu-và-cài-đặt)
3. [Quy trình sử dụng khuyến nghị](#3-quy-trình-sử-dụng-khuyến-nghị)
4. [Danh sách lệnh](#4-danh-sách-lệnh)
5. [File đầu ra](#5-file-đầu-ra)
6. [Agent điều tra như thế nào?](#6-agent-điều-tra-như-thế-nào)
7. [Cấu hình, hiệu năng và lưu ý](#7-cấu-hình-hiệu-năng-và-lưu-ý)
8. [Xử lý sự cố và kiểm thử](#8-xử-lý-sự-cố-và-kiểm-thử)
9. [Tài liệu chuyên sâu](#9-tài-liệu-chuyên-sâu)

## 1. Bắt đầu nhanh

Mở **PowerShell** trong thư mục chứa `agent.py`. Thay `D:\Work\LegacyProject` bằng thư mục source thật và `D:\AgentOutput\architecture` bằng nơi bạn muốn lưu kết quả.

### A. Tạo bản đồ kiến trúc và danh sách câu hỏi (không gọi Qwen)

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

Lệnh này tự động:

- Quét cấu trúc module, dependency, framework, FE/BE/DB và quan hệ tham chiếu tĩnh.
- Tạo **Markdown + Draw.io** và bản tóm tắt từng module từ bằng chứng source.
- Tạo/cập nhật **Code Intelligence Index** (`SQLite`) dùng lại cho những lần điều tra sau.
- Sinh **tối đa 20 câu hỏi điều tra có dẫn chứng**, chia đúng hai nhóm **Business Flows** và **Technical Architecture**. Có thể ít hơn 20 nếu source không đủ dấu hiệu.

Mở file `D:\AgentOutput\architecture\suggested_investigations.md` để chọn chủ đề đáng điều tra.

### B. Tự điều tra 5 câu hỏi có ưu tiên cao nhất bằng Qwen

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --auto-investigate-top 5 --out "D:\AgentOutput\architecture"
```

`--auto-investigate-top N` nhận `1` đến `20`; **không có tùy chọn này thì không tự chạy điều tra bằng Qwen**. Mỗi câu hỏi được lưu riêng dưới `investigations/`; trạng thái và lỗi nằm trong `investigations/manifest.json`. Danh sách câu hỏi được xếp hạng bằng heuristic, **không phải do Qwen chấm điểm**.

### C. Hỏi một câu bất kỳ — Qwen được bật mặc định

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" investigate "Nếu sửa saveOrder thì những màn hình nào có thể bị ảnh hưởng?" --max-steps 4 --budget 1200 --out "D:\AgentOutput\architecture"
```

Qwen lập kế hoạch → Python gọi các công cụ điều tra read-only → Qwen lựa chọn bước tiếp theo → tổng hợp bằng chứng `file:line` nếu tìm được.

**Không dùng Qwen** (chỉ tìm evidence bằng Python/SQLite):

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" investigate "OrderService" --non-ai --out "D:\AgentOutput\architecture"
```

> `investigate --non-ai` là **lexical evidence retrieval**, không hiểu sâu mọi câu hỏi ngôn ngữ tự nhiên. Để dùng `investigate` hoặc các công cụ symbol/graph trên một output mới, chạy `architecture` hoặc `intelligence` trước với **cùng đường dẫn `--out`**.

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

**Khi cần phân tích sâu:** tăng `--max-steps` (tối đa 6), giữ `--budget` phù hợp context; hoặc dùng `--auto-investigate-top N` để xử lý nhiều câu hỏi đã xếp hạng.

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
| `architecture --auto-investigate-top N` | Tự chạy N câu hỏi đã chọn | Có |
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

Khi chạy `architecture --out "D:\AgentOutput\architecture"`:

```text
D:\AgentOutput\architecture\
├── architecture.md                    # Modules và quan hệ tĩnh
├── architecture.drawio                # Sơ đồ dependency module
├── module_summary.md                  # Tóm tắt module
├── stack_architecture.md              # Framework, FE/BE/DB và evidence
├── frontend_architecture.drawio
├── backend_architecture.drawio
├── fe_be_architecture.drawio
├── frontend_reference.drawio          # Reference roles khớp source
├── backend_reference.drawio
├── suggested_investigations.md        # Tối đa 20 câu hỏi, 2 nhóm
├── middle-files\
│   ├── architecture.json
│   ├── module_summary.json
│   ├── stack_architecture.json
│   ├── code_intelligence.sqlite
│   ├── suggested_investigations.json
│   └── .module_summary_cache\         # Khi dùng --ai-summary
└── investigations\                    # Chỉ khi dùng --auto-investigate-top
    ├── INV-001.json
    ├── INV-002.json
    └── manifest.json
```

Các file `.drawio` có thể mở bằng [diagrams.net](https://app.diagrams.net) → **File → Open From → Device**. Box FE/BE/DB được tô màu; các cạnh Reference dạng nét đứt biểu diễn gợi ý cấu trúc, **không phải lời gọi runtime đã được chứng minh**.

Ngoài ra, chỉ mục tìm kiếm FTS của các lệnh `index`/`chat`/`design` được quản lý riêng trong `%USERPROFILE%\.local_code_agent\index\` (khác với `middle-files\code_intelligence.sqlite`).

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
- **Suggestions:** bộ xếp hạng heuristic xác định những câu hỏi có dấu hiệu source. `--auto-investigate-top` mới dùng Qwen để đi sâu vào các câu đó.

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

**Hiệu năng:** Quét và lập chỉ mục là xử lý nội bộ; các câu hỏi Qwen có thể cần nhiều lượt sinh nội dung. Với project lớn, nên chạy `architecture` trước, đọc suggestions và bắt đầu `--auto-investigate-top 1` hoặc `2` để kiểm tra chất lượng. Không nên coi Top 20 là 20 kết luận đã được xác minh.

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
| Một auto investigation lỗi | Mở `investigations/manifest.json` và file `INV-xxx.json`; các câu còn lại vẫn có thể được chạy |
| File Draw.io có đường chéo hoặc chồng nhau | Dữ liệu graph lớn có thể vượt khả năng layout mặc định; sắp xếp lại trong diagrams.net |

Chạy bộ test từ thư mục chứa `agent.py`:

```powershell
py -3 -m unittest discover -s tests -v
```

**Mã thoát CLI:** `0` thường là thành công; `1` cho lỗi đầu vào/Ollama hoặc I/O được xử lý; `2` có thể biểu thị auto-investigation thất bại một phần hoặc tác vụ overview/design chưa hoàn tất. Luôn đọc JSON và thông báo lỗi thực tế thay vì dựa vào mã thoát đơn lẻ.

## 9. Tài liệu chuyên sâu

- [v4.13 — Suggested Investigations](README_V413.md): Top 20, hai nhóm câu hỏi và `--auto-investigate-top`.
- [v4.12 — Iterative Investigation](README_V412.md): Qwen chọn công cụ nhiều vòng, kiểm tra evidence.
- [Code Intelligence](README_CODE_INTELLIGENCE.md): symbol, trace, impact, flows, history và vector search.
- [Architecture & Module Summary](README_ARCHITECTURE.md): cách trích xuất graph và tóm tắt module.
- [FE/BE/DB Stack & Draw.io](README_STACK_ARCHITECTURE.md): framework, database và sơ đồ Reference.
- [Draw.io Layout v4.8](README_V48.md): lane, nhóm framework, màu và đường nối.
- [Legacy v4 / Full Repository Scan](README_V4.md): các workflow `design`, `overview` và checkpoint lịch sử.

> **README này là hướng dẫn sử dụng chính cho v4.13.** Các tài liệu theo phiên bản được giữ làm chi tiết kỹ thuật hoặc lịch sử thay đổi; khi ví dụ cũ xung đột với CLI hiện tại, ưu tiên `py -3 agent.py --help` và trợ giúp của từng lệnh.
