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

## v4.2 — Module Summary

Sau khi xây bản đồ liên kết, lệnh `architecture` tự thu thập một mẫu comment/Javadoc/AS3/MXML và khai báo class/method theo module cấp một, rồi tạo:

- `module_summary.md`: vai trò tạm xác định và dẫn chứng `file:line`, có mục lục.
- `module_summary.json`: dữ liệu comment, khai báo và kết quả tóm tắt của từng module.
- `.module_summary_cache/`: cache kết quả AI khi dùng `--ai-summary`.

Không cần Ollama:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

Có Ollama và muốn thêm tóm tắt bằng Qwen3:8B:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 architecture --ai-summary --out "D:\AgentOutput\architecture"
```

AI dùng các trích dẫn đại diện để phác thảo vai trò module, **không** xác minh toàn bộ runtime flow và không đọc toàn bộ source qua LLM. Module hiện dựa trên thư mục cấp một; comment có thể đã lỗi thời. Cache tái sử dụng nếu prompt, model, context không đổi.

## v4.3 — Graph → Module Evidence → AI Summary

`architecture --ai-summary` sử dụng `architecture.json` đã tạo, thay vì quét lại mọi file source để tóm tắt module:

1. **Architecture Graph:** file links (incoming, outgoing, internal), Maven/Gradle/Ivy dependencies, bảng SQL.
2. **Module Evidence:** chọn tối đa 32 file tiêu biểu dựa trên số liên kết và tên file; lấy comment, Javadoc và khai báo có `path:line`.
3. **AI Summary:** Qwen3:8b phân tích bằng chứng đã rút gọn trong context 2048. Các liên kết import chỉ là quan hệ tĩnh, không chứng minh runtime call.

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 architecture --ai-summary --out "D:\AgentOutput\architecture"
```

Trong lần chạy lại, agent tái sử dụng `architecture.json` nếu đường dẫn project và **path/size/mtime** của các file không đổi. Khi source thay đổi, agent tạo lại graph. Lưu ý metadata không phải hash nội dung mật mã; nếu thay đổi file mà giữ nguyên size/mtime, cần xóa `architecture.json` để quét mới.

Kết quả `module_summary.md` và `module_summary.json` có thêm `graph_context`, liên kết module đi vào/đi ra, mức độ tin cậy, thư viện khai báo, SQL table và dẫn chứng. Thư viện khai báo tại root chỉ được ghi là *repository-declared, module use unverified*, không tự coi là dependency trực tiếp của từng module.

AI cache tại `.module_summary_cache` vẫn dùng hash của prompt/model/context. Khi đầu vào không đổi, lượt chạy sau không gọi lại AI cho module đã có kết quả.

**Giới hạn:** module vẫn dựa theo thư mục cấp 1; parsing mang tính heuristic, không xác minh runtime graph; chỉ đưa mẫu bằng chứng vào Qwen, không đọc toàn bộ source qua model.

## v4.4 — Clean output layout

The generated reports `architecture.md`, `architecture.drawio` and `module_summary.md` remain directly in the output folder. Machine-readable intermediates are now under `middle-files/`:

```text
output/architecture/
├── architecture.md
├── architecture.drawio
├── module_summary.md
└── middle-files/
    ├── architecture.json
    ├── module_summary.json
    ├── dependencies.csv
    ├── file_links.csv
    └── .module_summary_cache/
```

The main table of `module_summary.md` has only Module, File and Vai trò tạm xác định. Provenance and method metadata remain in `middle-files/module_summary.json`. Existing v4.3 JSON/CSV files and AI cache are migrated to `middle-files/` automatically without discarding valid checkpoints.
