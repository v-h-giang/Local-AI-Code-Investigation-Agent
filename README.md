**v4.6:** FE/BE framework reference diagrams only show roles backed by scanned source objects; missing roles are listed in the report. See [architecture guide](README_STACK_ARCHITECTURE.md).

**v4.5 FE/BE/DB architecture:** [read documentation](README_STACK_ARCHITECTURE.md).

> **v4.4:** `architecture --ai-summary` now removes the AI method column from Markdown and stores JSON/CSV/checkpoints in `middle-files/`. Existing v4.3 intermediate files are migrated automatically.

> **v4.3:** Module Summary uses the cached architecture graph, including inter-module links, source comment evidence, declared dependencies and SQL references. Reuses architecture.json when source metadata is unchanged; see [README_ARCHITECTURE.md](README_ARCHITECTURE.md).

> **v4.2 Module Summary:** `architecture` now also generates `module_summary.md` / `module_summary.json` using source comments, declarations and file references. Add `--ai-summary` to use the installed `qwen3:8b` for a concise evidence-based summary per module, with resumable cache. See [architecture guide](README_ARCHITECTURE.md).

# Local AI Code Investigation Agent

**Current version: v4 — full repository scan, durable per-chunk checkpoints and restartable analysis.**

See [v4 usage and recovery instructions](README_V4.md).

**v4.1:** Fast architecture discovery without running Ollama or indexing: [Architecture-first guide](README_ARCHITECTURE.md).

Run: `py -3 agent.py --project "D:\\Work\\LegacyProject" architecture --out "D:\\AgentOutput\\architecture"`.

---

# Quick start: automatic indexing

You do **not** need to run `index` before `design` or `chat`. The agent checks source files and creates or refreshes the SQLite FTS5 index automatically on the first run and when source file size/mtime changes. Unchanged projects reuse the index. The `index` command remains available for manual forced rebuild. Indexing is a search cache and creates **no design document**.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 design --out "D:\AgentOutput\overview"
```

For chat:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 chat
```

The automatic index lives outside the project in `%USERPROFILE%\.local_code_agent\index\`. Design files are written to the `--out` folder. Indexing is metadata based and is not a full content hash; if source files are changed without their size or timestamps changing, run `index` to force refresh.

---

# Local Code Investigation Agent — Ollama (Windows / VS Code)

## Mục lục

- [1. Tính năng](#features)
- [2. Yêu cầu hệ thống](#requirements)
- [3. Cài đặt Windows](#install)
- [4. Sử dụng hằng ngày](#usage)
- [5. Xuất tài liệu thiết kế](#design)
- [5A. Khảo sát toàn bộ project tự động (không topic)](#automatic-overview)
- [6. Cơ chế điều tra](#methods)
- [7. Bảo mật và giới hạn](#security)
- [8. Test và xử lý lỗi](#tests)

<a id="features"></a>
## 1. Tính năng

Agent chạy trên **Ollama localhost**, hoạt động trong terminal VS Code, không cần backend web framework, Node.js hay API cloud:

- Java: tra class, method, reference, service, DAO, mapper (dò tĩnh).
- SQL: tìm table và SQL trong `.sql`, `.java`, `.xml` (gồm MyBatis/iBATIS).
- Adobe AIR: đọc ActionScript 3 (`.as`), MXML (`.mxml`), các event/callback/binding, dò điểm giao với backend qua tên được khai báo.
- Code investigation: `search`, `read` có line number, `refs`, `outline`, tìm kiếm SQLite FTS5 (từ khóa), agent tool-calling nhiều vòng.
- Tài liệu thiết kế: `design.md` chứa dẫn chứng `path:line`; `source_references.drawio` là **sơ đồ editable** trong diagrams.net; `source_inventory.md` là thống kê chạy được ngay cả khi Ollama chưa cài.
- Read-only: chỉ được đọc source; agent không có tool ghi/chạy shell/chạy SQL.

**Quan trọng:** Ở bản v2.1 này, quan hệ trong Draw.io là **tham chiếu ký tự tĩnh**, không phải call graph hay runtime data flow đã được chứng minh. Agent có thể suy luận luồng nghiệp vụ bằng cách đọc nguồn, nhưng phải phân biệt bằng chứng và giả thuyết.

<a id="requirements"></a>
## 2. Yêu cầu hệ thống

- Windows 10/11, VS Code (tùy chọn, tiện dùng).
- Ollama cho Windows: <https://ollama.com/download/windows>
- Python 3.11+ (chỉ dùng standard library, không yêu cầu `pip install`).
- Nếu máy khoảng 15–16 GB RAM: model mặc định `qwen3:8b` (kích thước tải xuống khoảng 5.2 GB); nếu chỉ còn khoảng 5 GB RAM trống, việc chạy model có thể thất bại hoặc phải dùng pagefile, cân nhắc `qwen2.5-coder:7b` (~4.7 GB) nếu ưu tiên chuyên code. Dung lượng model **không phải tổng RAM lúc chạy**, còn KV cache và context.
- Bắt đầu với `num_ctx=4096` do máy RAM hạn chế, chỉnh trong `agent_core.py` nếu đủ tài nguyên.

<a id="install"></a>
## 3. Cài đặt Windows

**Bước 1.** Cài Ollama cho Windows. Mở PowerShell và pull model:

```powershell
ollama pull qwen3:8b
ollama list
```

Nếu Ollama chưa tự chạy dịch vụ, khởi động ứng dụng Ollama. Trên những cài đặt phù hợp có thể chạy `ollama serve` trong terminal riêng (nếu port 11434 chưa bị chiếm).

**Bước 2.** Giải nén ZIP của project agent và mở thư mục bằng VS Code. Kiểm tra Python:

```powershell
py -3 --version
```

**Bước 3.** Kiểm tra bằng sample đi kèm (đứng trong thư mục `local_code_agent`):

```powershell
py -3 agent.py --project .\sample_project doctor
py -3 agent.py --project .\sample_project search "selectOrders"
py -3 agent.py --project .\sample_project index
py -3 agent.py --project .\sample_project ask "Truy vết chức năng loadOrders từ Adobe AIR đến SQL, chỉ kết luận nếu có bằng chứng."
```

`ask`, `chat`, `design`, `overview --ai` cần dịch vụ Ollama; `doctor` kiểm tra kết nối nhưng vẫn chạy được khi Ollama tắt. `search`, `refs`, `read`, `index`, `report`, `overview` (không `--ai`) **không cần Ollama**.

<a id="usage"></a>
## 4. Sử dụng hằng ngày

Thay `D:\Work\LegacyProject` bằng đường dẫn source thật (cần thư mục trên máy, không phải repo URL):

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" index
py -3 agent.py --project "D:\Work\LegacyProject" chat
```

Ví dụ câu hỏi khi `chat`:

> Từ button Search trong file MXML, lần theo event handler sang service Java, DAO và SQL. Liệt kê chính xác file:line. Nếu không có mối nối rõ ràng, báo là chưa xác minh.

> Khi sửa điều kiện WHERE cho order_header, những mapper và Java service nào có thể liên quan? Liệt kê bằng chứng và rủi ro.

> Phân tích logic validation của class OrderController và đề xuất test cases, không sửa source.

Lệnh chỉ dùng search/inspect (không cần LLM):

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" refs "getOrders"
py -3 agent.py --project "D:\Work\LegacyProject" search "order_header" --pattern "*.xml"
py -3 agent.py --project "D:\Work\LegacyProject" read "src/main/java/com/example/OrderService.java" --start 10 --end 95
```

`index` xây FTS5 từ khóa và nên chạy lại sau khi source thay đổi. Chỉ mục lưu ngoài repository trong thư mục người dùng `.local_code_agent/index`. **Lưu ý:** chỉ mục chứa các đoạn source dạng plaintext và phải được bảo vệ như source gốc.

<a id="design"></a>
## 5. Xuất tài liệu thiết kế

### 5.1. Không cần AI: thống kê source + Draw.io editable

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" report --topic "Order" --out ".\output\order"
```

Sinh:

- `output/order/source_inventory.md` — bảng file, tham chiếu tĩnh, hạn chế.
- `output/order/source_references.drawio` — sơ đồ thực thể file/source và bảng SQL, **chỉnh từng shape, mũi tên, text**.

### 5.2. Có AI: điều tra và tạo design document

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" design --topic "Order" --out ".\output\order"
```

Thêm `output/order/design.md` gồm mục lục clickable, phạm vi, luận giải, trace có `path:line`, test cases và chỗ chưa chứng minh. Lưu `investigation_log.json` ghi tên và tham số tool để audit (không chứa toàn bộ tool output).

**Sửa Draw.io:** mở <https://app.diagrams.net> → File → Open From → Device → chọn `.drawio` (hoặc extension VS Code diagrams.net).

Nếu cần Word/PDF, dùng công cụ biên tập Markdown để chuyển đổi khi tài liệu đã được kiểm tra. Bản v2.1 xuất bản nguồn thiết kế dưới Markdown + Draw.io, không hứa xuất DOCX/PDF trực tiếp.


<a id="automatic-overview"></a>
## 5A. Khảo sát toàn bộ project tự động — không cần biết topic

Đây là chế độ dành cho người chưa hiểu source. **Không cần đoán tên class, tên chức năng, từ khóa hoặc chọn file ban đầu.**

### Lựa chọn A — Khảo sát toàn project, không cần Ollama

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" overview --out ".\output\overview"
```

Agent tự đọc các file source được cho phép và sinh:

- `system_overview.md`: cấu trúc module, tỷ lệ file Java/AS3/MXML/SQL/XML, dấu hiệu entrypoint, danh sách tên method và mapper ID có thể điều tra, bảng SQL được nhắc đến; có mục lục liên kết.
- `system_overview.drawio`: sơ đồ module **chỉnh sửa được**, node dựa trên top-level source folders; không đoán các lời gọi runtime.
- `repository_files.csv`: liệt kê **toàn bộ file đã được quét**, không bị giới hạn 35 file như `report`.
- `repository_overview.json`: dữ liệu khảo sát và evidence `path:line` để sử dụng lại.

### Lựa chọn B — Khảo sát tự động và sinh bản thảo thiết kế bằng Ollama

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" design --out ".\output\overview"
```

**Không có `--topic`.** Agent trước tiên quét project, sau đó cho Ollama điều tra có chọn lọc những phần nổi bật dựa trên các evidence đã tìm, đồng thời sinh `architecture_design.md` và `investigation_log.json`. Có thể thay bằng `overview --ai --out ...`. Với dự án lớn, AI khảo sát tối đa 12 module đứng đầu theo số file trong lần tạo bản thảo này; inventory tĩnh vẫn chứa tất cả file được quét. Điều này **không** có nghĩa AI đọc kỹ mọi method.

### Lựa chọn C — Trong phiên chat

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" chat
```

Nhập `/overview` để lập báo cáo quét tĩnh; nhập `/design-all` để lập bản thảo tổng quan bằng AI. Báo cáo mặc định được lưu ở `output/overview`. Các lệnh này **không dùng nội dung chat trước đó làm dữ liệu đầu vào**; bản thảo AI sử dụng source và khảo sát tự động.

### Phạm vi và độ tin cậy

- `overview` quét tối đa **25.000 file** có extension được hỗ trợ, file không quá 1 MB, không ở thư mục đã loại trừ, không symlink. Báo cáo ghi rõ nếu chạm giới hạn.
- Nhóm module dựa theo **thư mục cấp 1**, không được coi là ranh giới module triển khai thực tế.
- Tín hiệu UI handlers / method / mapper IDs chỉ là thông tin **khai báo trong source**, không tự khẳng định được luồng Java ↔ Adobe AIR ↔ database.
- Sơ đồ tĩnh giới hạn 28 nhóm để dễ xem, ghi rõ số nhóm bị bỏ khỏi sơ đồ.
- Mô hình AI vẫn có thể sai; phải kiểm tra `path:line` trước khi coi là thiết kế chính thức.

<a id="methods"></a>
## 6. Cơ chế điều tra

```text
Project local (read-only)
  ├─ .java      → search exact + class/method outline
  ├─ .sql       → SQL refs / tables
  ├─ .xml       → mapper + query references
  ├─ .as/.mxml  → AS3 events + callbacks
  └─ khác       → config / property files
         ↓
  Python stdlib tools + SQLite FTS5
         ↓
  Ollama /api/chat, native tool calling
         ↓
  LLM đọc kết quả theo dòng → trace có trích dẫn
         ↓
  Markdown design + editable Draw.io
```

**FTS5 không phải vector embedding/RAG ngữ nghĩa.** Hệ thống cố ý dùng tra từ khóa + tool calling để kiểm soát chứng cứ. Cần nâng cấp với parser AST chuyên biệt, Java language server/call hierarchy, parser SQL, embedding khi dự án quá lớn hoặc nhiều dynamic dispatch.

<a id="security"></a>
## 7. Bảo mật và giới hạn

- Chỉ gửi dữ liệu đến loopback `127.0.0.1:11434`/`localhost` qua HTTP; không có web API/cloud connector.
- Agent chỉ expose những tool đọc source; không cho agent chỉnh sửa, xóa, thực thi source, kết nối cơ sở dữ liệu hoặc chạy SQL. Chỉ dùng model Ollama đã tải xuống local, không cấu hình model `:cloud`.
- Chặn path traversal và symlink ngoài project; bỏ qua `.git`, `target`, `build`, `node_modules`, binary, file >1 MB.
- **File code có thể chứa bí mật**. Model vẫn có thể đọc source và đưa nội dung vào log/Markdown; bạn cần loại bỏ secret khỏi project snapshot trước khi phân tích. Đừng đưa agent truy cập code chứa credential không được phép đọc.
- AI có thể suy diễn nhầm dù có file:line. Review tất cả bằng chứng; flow dùng reflection, CDI/Spring DI, Remoting Adobe AIR hoặc SQL động có thể bị bỏ sót.
- `source_inventory.md` và `source_references.drawio` là static reference graph, KHÔNG phải mô hình call graph chuẩn.
- Quy tắc nội bộ công ty có thể hạn chế xử lý source trong phần mềm AI ngay cả khi chạy local. Kiểm tra chính sách trước khi dùng source doanh nghiệp.

<a id="tests"></a>
## 8. Test và xử lý lỗi

```powershell
py -3 -m unittest discover -s tests -v
```

- `Ollama not reachable`: mở Ollama, kiểm tra `http://127.0.0.1:11434/api/tags`, tránh chạy 2 server cùng cổng.
- `model not found`: `ollama pull qwen3:8b`.
- Chậm hoặc hết RAM: thử `--num-ctx 2048` với `qwen3:8b`; nếu vẫn không đủ bộ nhớ, chỉ khi bạn chủ động chọn model nhẹ hơn mới dùng `ollama pull qwen3:4b` và `--model qwen3:4b`.
- Kết quả chưa có dẫn chứng: yêu cầu AI dùng `search_code`, `read_file`, kiểm tra các file:line của câu trả lời.
- Sai encoding source Nhật: reader thử `UTF-8-SIG`, `CP932`, `UTF-16`, rồi thay thế ký tự khi cần; hãy kiểm tra file đầu vào.

## Tài liệu tham khảo chính thức

- Ollama tool calling: <https://docs.ollama.com/capabilities/tool-calling>
- Ollama chat API: <https://docs.ollama.com/api/chat>
- Model Qwen3 8B: <https://ollama.com/library/qwen3:8b>
- Model Qwen2.5 Coder: <https://ollama.com/library/qwen2.5-coder:7b>
- Draw.io: <https://www.diagrams.net/>

<a id="diagnose-v21"></a>
## 9. Ollama diagnostics (v2.1) — 5 GB free RAM

The older v2 error `Cannot connect to local Ollama` could mask request timeouts and connection resets. v2.1 preserves the underlying error and defaults to a smaller 4096-token context (previously 8192).

**PowerShell from the directory containing `agent.py`:**

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
ollama run qwen3:8b "Reply OK"
py -3 agent.py --project ".\sample_project" --model qwen3:8b --num-ctx 2048 doctor --probe
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 design
```

In `doctor --probe`, the application **actually requests text generation** with context 1024 to distinguish an available HTTP server from a model that can be loaded. It does not check available RAM or guarantee that longer design requests will work.

How to interpret output:

- `Ollama not reachable`: endpoint/port/server issue. Check `ollama serve` if not already running.
- `HTTP 404` or a model-not-found message: check `ollama list`, `ollama pull qwen3:8b`, then use `--model qwen3:8b`.
- `HTTP 500`, `out of memory`, `model requires more memory`: model loading/memory failure; close memory-heavy applications, reduce model/context.
- `Timed out waiting for model generation`: model/server did not respond before `--timeout` seconds. Try `--timeout 600` only if the model can demonstrably load and remains responsive.
- `Connection closed during request`: Ollama process may have crashed or restarted; inspect the Ollama application log, Windows Event Viewer and memory availability. This is not by itself proof of OOM.

If Ollama is unavailable, **automatic static investigation still works**:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" overview --out ".\output\overview"
```

The offline mode generates `system_overview.md`, `.drawio`, `.csv`, and `.json`, but not the AI-written `architecture_design.md`.

**New global parameters:** `--num-ctx 2048` (lower context) and `--timeout 600` (longer response timeout). Global parameters must appear **before** the subcommand (`design`, `doctor`, `chat`).

---

## v3 — Phân tích toàn repository theo lô, dành cho RAM trống khoảng 5 GB

**Model mặc định giữ nguyên `qwen3:8b`.** CLI mặc định `--num-ctx 2048` (có thể tăng thủ công). Chỉ cần chỉ định đường dẫn project; không cần biết tên chức năng.

```powershell
ollama serve
# Trong cửa sổ PowerShell khác:
ollama list
py -3 agent.py --project "D:\Work\LegacyProject" index
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 design --out "D:\AgentOutput\overview"
```

### Các pha thực thi

1. **Quét tĩnh tất cả file đủ điều kiện** (tối đa 25.000 file, mỗi file tối đa 1 MB), ghi `repository_files.csv`, `repository_overview.json`, `system_overview.md`, `system_overview.drawio`. Quét tĩnh không yêu cầu Ollama.
2. **Ưu tiên các file có dấu hiệu entrypoint/handler/mapper**, chọn luân phiên từ các nhóm module để tránh chỉ đọc nhóm lớn nhất.
3. **Phân tích các đoạn source ngắn** (tối đa 2 file/lô, tối đa 1.350 ký tự bằng chứng mỗi file) bằng các request Ollama độc lập, không nạp toàn repo vào context.
4. **Lưu checkpoint** `.investigation_cache/batch_*.json` sau từng lô. Nếu model bị thiếu bộ nhớ/timeout, tài liệu và các phần đã hoàn thành vẫn được lưu. Chạy lại cùng lệnh sẽ dùng cache.
5. **Xuất** `architecture_design.md` (có mục lục), `analysis_manifest.json` (số file quét/AI phân tích/chưa phân tích), cùng danh mục và sơ đồ tĩnh.

Mặc định mỗi lượt phân tích tối đa **24 lô × 2 file = 48 file**. Đây là ngân sách AI, **không phải giới hạn quét tĩnh repository**. Có thể mở rộng:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 design --max-batches 120 --files-per-batch 1 --out "D:\AgentOutput\overview"
```

Các lô đã hoàn thành không cần chạy lại trừ khi model, context, nội dung bằng chứng hoặc prompt thay đổi. Muốn chạy lại chủ động thêm `--no-resume`.

Trong chat, `/overview` chỉ quét tĩnh; `/design-all` thực hiện quy trình AI theo lô mặc định.

**Giới hạn:** phương pháp này tạo bản khảo sát có dẫn chứng và các phân tích cục bộ, **chưa tự xác minh call graph runtime, chưa gộp tất cả chức năng thành một thiết kế chi tiết**, và không bảo đảm đoạn trích đại diện cho toàn bộ nội dung file. `analysis_manifest.json` thể hiện chính xác mức bao phủ. Với repository lớn, nên dùng `--max-batches` cao hơn và kiểm duyệt kết quả theo từng module. Output có thể chứa trích đoạn code nội bộ, vì vậy không công bố công khai.


## Hiển thị RAM trong terminal

Agent tự in `TotalRAM_GB`, `UsedRAM_GB`, `FreeRAM_GB` khi khởi động mọi lệnh (`chat`, `design`, `doctor`, ...). Không cần chạy PowerShell riêng hoặc cài thêm package. Trên Windows số liệu lấy từ `GlobalMemoryStatusEx`, gần với số liệu bộ nhớ vật lý của hệ điều hành và chỉ là ảnh chụp tại lúc bắt đầu; không phải bộ nhớ riêng của Ollama.
