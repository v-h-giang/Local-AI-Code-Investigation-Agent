# v4.5 — Frontend / Backend / Database Architecture

## Chạy

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

Hoặc vừa tóm tắt module với Qwen3:8B (mặc định `num_ctx=2048`):

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --ai-summary --out "D:\AgentOutput\architecture"
```

Lệnh giữ nguyên để không làm vỡ workflow cũ. Chức năng phân tích FE/BE/DB chạy offline và không gọi Ollama; nếu bật `--ai-summary` thì Qwen vẫn chỉ dùng cho Module Summary.

## Đầu ra

```text
output/architecture/
├── architecture.md
├── architecture.drawio
├── module_summary.md
├── stack_architecture.md           # Báo cáo FE / BE / DB / framework / object
├── frontend_architecture.drawio    # Roles và liên kết tĩnh thực tế ở FE
├── backend_architecture.drawio     # Roles và liên kết tĩnh thực tế ở BE
├── fe_be_architecture.drawio       # Các cạnh FE ↔ BE ↔ DB được source chứng minh
├── frontend_reference.drawio       # Reference pattern cho framework FE (nét đứt)
├── backend_reference.drawio        # Reference pattern cho framework BE (nét đứt)
└── middle-files/
    ├── architecture.json
    ├── module_summary.json
    ├── stack_architecture.json     # Dữ liệu phân loại / evidence / roles chi tiết
    ├── dependencies.csv
    ├── file_links.csv
    └── .module_summary_cache/
```

**Quan trọng:** Sơ đồ observed chỉ dùng liên kết tĩnh hiện có trong `architecture.json`; không vẽ một request FE→BE tưởng tượng. Sơ đồ reference thể hiện cấu trúc thường gặp của công nghệ được phát hiện và có nhãn **reference pattern**.

## Phân loại & bằng chứng

- FE: ActionScript / MXML, Apache Flex / Adobe AIR nhận dạng từ import, tags, dependency.
- BE: Java, Spring MVC/Core, Spring Boot, MyBatis, Hibernate/JPA, Struts, JSF và JDBC theo dependency, annotation, import, cấu hình XML.
- DB: chỉ gắn tên hệ quản trị từ driver hoặc JDBC URL có bằng chứng (PostgreSQL, MySQL, MariaDB, Oracle, SQL Server, SQLite, H2, DB2). SQL file không đủ để xác nhận hệ quản trị nào.
- Object/roles: View/Screen, Event/Controller, Model, Proxy ở FE; Controller, Service, Mapper/Repository, Entity/DTO, Configuration ở BE.
- Các vai trò object là nhận diện cú pháp/tên, chưa phải xác nhận ranh giới kiến trúc runtime.
- Root `pom.xml` khai báo dependency cho repo, **không khẳng định** tất cả module đều thực sự sử dụng framework.
- Không kết luận một loại object chắc chắn không tồn tại chỉ vì scanner không phát hiện.

Các reference thuộc công khai và dùng làm tiêu chuẩn đối chiếu, không phải nguồn chứng minh repo của người dùng:

- Apache Flex MXML: https://flex.apache.org/doc/flex/using/flx_mxml_mx.html
- Apache Flex custom components: https://flex.apache.org/doc/flex/using/flx_createcomps_intro_cci.html
- Spring stereotype annotations: https://github.com/spring-projects/spring-framework/wiki/Spring-Annotation-Programming-Model
- MyBatis mapper XML: https://mybatis.org/mybatis-3/sqlmap-xml.html
- Maven directory layout: https://maven.apache.org/guides/introduction/introduction-to-the-standard-directory-layout.html

## Giới hạn

Phân tích tĩnh không thay thế compiler/parser AST, runtime call graph, database inspection, servlet mapping hoặc giải quyết remote endpoint. Các scanner hiện bỏ qua binary, symlink, phần lớn thư mục build, file >1 MB và một số định dạng configuration. Với 8.000 file có thể chạy đáng kể nhưng không cần 2,4 triệu requests AI.

## v4.6 — Reference Draw.io chỉ hiển thị vai trò có object

Trước v4.6, file `frontend_reference.drawio` và `backend_reference.drawio` hiển thị
mọi vai trò theo lý thuyết, kể cả vai trò `0 objects`, nên dễ nhầm với source
thực sự có sẵn. Từ v4.6:

- Mỗi ô reference phải khớp được ít nhất một file trong source đã quét.
- Ô hiển thị **tổng object và một vài đường dẫn file** để đối chiếu.
- Vai trò tham khảo không khớp file **không xuất hiện trên sơ đồ**; xem bảng
  **Đối chiếu Reference với source** trong `stack_architecture.md` hoặc
  `middle-files/stack_architecture.json` (`reference_role_coverage`).
- Mũi tên tham khảo là nét đứt, chỉ nối các vai trò của **cùng framework**,
  không được hiểu là call graph runtime.
- Nếu không có bất kỳ object phù hợp, sơ đồ chỉ hiển thị thông báo "No matching
  source objects", không tạo các ô object giả.

Chạy lại `architecture` để sinh các file Draw.io mới. Không cần dùng `--ai-summary`
để chạy phần này, và không cần gọi Ollama.

**Giới hạn**: việc ghép object với reference dựa vào heuristic (tên file,
annotation và role phát hiện), không phải Java/AS3 AST đầy đủ. Một số object thực
có thể không được khớp; trạng thái “not_found” nghĩa là “không tìm thấy trong
source được quét”, không khẳng định module thiếu chức năng đó.

## v4.8 — Draw.io lanes, grouping and legibility

The generated diagrams use a deterministic, editable left-to-right layout:

- `fe_be_architecture.drawio`: explicit FE → BE → DB → Shared/Unknown lanes, each with a distinct fill/border color. A lane is a visual grouping, not proof that two roles communicate.
- `frontend_reference.drawio` / `backend_reference.drawio`: separate columns for each detected framework. Only reference roles backed by scanned source objects are drawn; any dashed edges are conceptual within the same framework.
- `frontend_architecture.drawio` / `backend_architecture.drawio`: order observed roles by the degree and neighborhood of confirmed static references, with generous spacing.
- Arrows have `endSize=24`, `strokeWidth=3`, larger labels and orthogonal routing. Reference arrows remain dashed.

Colors: FE amber, BE blue, DB green and shared/unknown neutral grey. Existing discovery and inference behavior is unchanged. The diagram tool may re-route orthogonal connectors when opened or edited; a static layout cannot guarantee zero crossings for dense graphs. The graph has no inferred runtime HTTP calls.
