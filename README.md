# Local Code Investigation Agent — Ollama (Windows / VS Code)

## Mục lục

- [1. Tính năng](#features)
- [2. Yêu cầu hệ thống](#requirements)
- [3. Cài đặt Windows](#install)
- [4. Sử dụng hằng ngày](#usage)
- [5. Xuất tài liệu thiết kế](#design)
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

**Quan trọng:** Ở bản v1 này, quan hệ trong Draw.io là **tham chiếu ký tự tĩnh**, không phải call graph hay runtime data flow đã được chứng minh. Agent có thể suy luận luồng nghiệp vụ bằng cách đọc nguồn, nhưng phải phân biệt bằng chứng và giả thuyết.

<a id="requirements"></a>
## 2. Yêu cầu hệ thống

- Windows 10/11, VS Code (tùy chọn, tiện dùng).
- Ollama cho Windows: <https://ollama.com/download/windows>
- Python 3.11+ (chỉ dùng standard library, không yêu cầu `pip install`).
- Nếu máy khoảng 15–16 GB RAM: model mặc định `qwen3:8b` Q4_K_M (~5.2 GB tải xuống), cân nhắc `qwen2.5-coder:7b` (~4.7 GB) nếu ưu tiên chuyên code. Dung lượng model **không phải tổng RAM lúc chạy**, còn KV cache và context.
- Bắt đầu với `num_ctx=8192` do máy RAM hạn chế, chỉnh trong `agent_core.py` nếu đủ tài nguyên.

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

`ask`, `chat`, `design` cần dịch vụ Ollama; `doctor` kiểm tra kết nối nhưng vẫn chạy được khi Ollama tắt. `search`, `refs`, `read`, `index`, `report` **không cần Ollama**.

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

Nếu cần Word/PDF, dùng công cụ biên tập Markdown để chuyển đổi khi tài liệu đã được kiểm tra. Bản v1 xuất bản nguồn thiết kế dưới Markdown + Draw.io, không hứa xuất DOCX/PDF trực tiếp.

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
- Chậm hoặc hết RAM: dùng `--model qwen3:4b` sau khi `ollama pull qwen3:4b`; giảm `num_ctx` ở `agent_core.py` từ 8192 xuống 4096.
- Kết quả chưa có dẫn chứng: yêu cầu AI dùng `search_code`, `read_file`, kiểm tra các file:line của câu trả lời.
- Sai encoding source Nhật: reader thử `UTF-8-SIG`, `CP932`, `UTF-16`, rồi thay thế ký tự khi cần; hãy kiểm tra file đầu vào.

## Tài liệu tham khảo chính thức

- Ollama tool calling: <https://docs.ollama.com/capabilities/tool-calling>
- Ollama chat API: <https://docs.ollama.com/api/chat>
- Model Qwen3 8B: <https://ollama.com/library/qwen3:8b>
- Model Qwen2.5 Coder: <https://ollama.com/library/qwen2.5-coder:7b>
- Draw.io: <https://www.diagrams.net/>
