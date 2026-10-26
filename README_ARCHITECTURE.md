# Architecture-first mode (v4.1)

## Mục lục

- [Chạy nhanh](#chạy-nhanh)
- [Đầu ra](#đầu-ra)
- [Quan hệ được tìm](#quan-hệ-được-tìm)
- [Giới hạn](#giới-hạn)

## Chạy nhanh

Không cần Ollama và không cần `index`.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

Lệnh chỉ quét source tĩnh một lần rồi sinh bản đồ tổng thể. Không gọi Qwen 2,4 triệu lần. Muốn điều tra chi tiết sau đó mới dùng `chat` hoặc `design`.

## Đầu ra

- `architecture.md`: thống kê hệ thống, module, thư viện, quan hệ file có mục lục.
- `architecture.drawio`: sơ đồ các module và mũi tên liên kết **dựa vào reference được phát hiện**, có thể chỉnh sửa bằng diagrams.net.
- `architecture.json`: toàn bộ kết quả thô để xử lý tiếp.
- `file_links.csv`: cạnh nguồn → đích, loại quan hệ, dòng mã, mức tin cậy.
- `dependencies.csv`: thư viện được khai báo từ Maven/Gradle/Ivy/Ant (giới hạn tùy manifest).

## Quan hệ được tìm

- Java, ActionScript import → class tương ứng trong repository.
- Biến/kiểu khai báo trong Java/ActionScript → class tương ứng khi tìm ra duy nhất một tên.
- MyBatis XML namespace → mapper interface/class Java.
- XML `class`/`type`/`resultType` → Java class khi tìm được.
- Maven `pom.xml`, Gradle `build.gradle`, `build.gradle.kts`, version catalog và Ivy.
- SQL table token sau FROM/JOIN/UPDATE/INTO/TABLE (heuristic).

Các cạnh `exact` khớp full qualified class name; `candidate-name-only` chỉ là ứng viên do trùng tên. Không được xem `import` như lời khẳng định đã có lời gọi runtime.

## Giới hạn

- File >1 MB, file binary, symlink và các thư mục build bị bỏ qua; không giới hạn 48 file hoặc 24 batch.
- MXML RemoteObject → Java service, Spring DI, XML mapping phức tạp, HTTP endpoint, SQL động, runtime reflection **chưa được truy vết đầy đủ**.
- Sơ đồ Draw.io giới hạn hiển thị 100 module lớn nhất để tránh vỡ bố cục; JSON/CSV vẫn lưu tất cả liên kết phát hiện.
- Không đọc/chạy SQL, không sửa source.
- Với monorepo nhiều phiên bản class trùng FQN, quan hệ mơ hồ được ghi vào `unresolved` trong JSON, không vẽ cạnh tùy tiện.

## Module Summary (v4.2)

Chạy lệnh `architecture` như cũ để xuất thêm `module_summary.md` và `module_summary.json`.
Bản mặc định **không dùng AI**, liệt kê comment/Javadoc/AS3/MXML và các khai báo đáng chú ý với đường dẫn và số dòng. Nó không tự khẳng định chức năng nghiệp vụ nếu source không đủ bằng chứng.

Muốn Qwen3:8B tóm tắt vai trò các module từ những bằng chứng đã trích:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --num-ctx 2048 architecture --ai-summary --out "D:\AgentOutput\architecture"
```

AI tối đa **một lời gọi cho mỗi module cấp 1** trong lần đầu, lưu checkpoint theo model/context/evidence tại `.module_summary_cache/`. Nếu lỗi Ollama, module đó vẫn có summary offline và được ghi lỗi vào JSON. Những lần sau dùng lại cache. Không phân tích hàng triệu chunk; tài liệu có mục lục và dẫn chứng `path:line`.

Giới hạn: chỉ chọn comment và khai báo tiêu biểu, không xem đây là phân tích đủ mọi luồng chức năng; comment có thể lỗi thời, trùng tên module không đảm bảo đúng ranh giới nghiệp vụ. Output có thể chứa trích đoạn source nội bộ, cần bảo quản như mã nguồn.

## v4.3 — Architecture Graph → Module Evidence → AI Summary

`architecture --ai-summary` nay **dùng trực tiếp `architecture.json`** để tổng hợp ngữ cảnh cho từng module. Luồng xử lý:

1. **Architecture Graph** — đọc `architecture.json` (gồm danh sách module, các cạnh file→file có loại quan hệ và mức tin cậy, dependency manifests, và heuristic bảng SQL). Nếu project và metadata `(path,size,mtime_ns)` của các source đủ điều kiện không đổi thì tái sử dụng graph thay vì phân tích lại tất cả nội dung source.
2. **Module Evidence** — lựa chọn tối đa 32 file/module, ưu tiên file được nhiều cạnh liên kết và một số loại file đại diện. Chỉ những file này được mở lại để lấy comment/Javadoc, khai báo class/method có `path:line`.
3. **AI Summary** — với `--ai-summary`, Ollama `qwen3:8b` đọc bằng chứng comment/khai báo, liên kết **outgoing/incoming/internal**, thư viện ở module hoặc root project và các bảng SQL liên quan. Giữ request ngắn cho `--num-ctx 2048`, sử dụng `.module_summary_cache/` để checkpoint từng module.

Lệnh chạy không đổi:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-summary --out "D:\AgentOutput\architecture"
```

**Giới hạn:** Lần nâng cấp v4.2→v4.3 sẽ phải tạo lại graph một lần do thay đổi định dạng và version. Sau đó chỉ kiểm tra metadata nếu source không đổi. Đây là kiểm tra nhanh theo mtime và size, không phải so sánh SHA256 từng file. Các thay đổi mtime/size không phản ánh đúng nội dung (hiếm gặp) có thể làm cache chưa được làm mới; trong trường hợp này xóa riêng `architecture.json` và chạy lại. Root Maven/Gradle dependencies được ghi `repository-declared, module use unverified` vì chúng không chứng minh module nào thực sự sử dụng thư viện. Import, mapper và bảng SQL là quan hệ tĩnh/heuristic, không chứng minh hành vi runtime. Không dùng `--no-resume`; cache module summary tự tái sử dụng khi prompt không đổi.

Xem `module_summary.json` trường `graph_context` để biết đầy đủ cạnh, thư viện và bảng SQL đã được cung cấp cho phần tổng hợp; `module_summary.md` hiển thị các bằng chứng quan trọng cùng trích dẫn `file:line`.

## v4.4 — Output layout

Final reports remain at the output root: `architecture.md`, `architecture.drawio`, and `module_summary.md`.

Intermediate files and resumable AI cache are organized in `middle-files/`:

```text
output/architecture/
├── architecture.md
├── architecture.drawio
├── module_summary.md
└── middle-files/
    ├── architecture.json
    ├── dependencies.csv
    ├── file_links.csv
    ├── module_summary.json
    └── .module_summary_cache/
```

The main Module Summary table no longer contains an AI method column. The JSON intermediate file retains its detailed provenance fields for diagnostics. Existing v4.3 intermediate files and AI checkpoints are migrated on the next execution; unchanged source retains architecture reuse and AI cache behavior.
