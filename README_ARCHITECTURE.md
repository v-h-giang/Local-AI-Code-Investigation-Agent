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
