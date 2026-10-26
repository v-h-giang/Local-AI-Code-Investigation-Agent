# v4.5 — Frontend / Backend / Database Architecture

## Chạy

Không cần Ollama để phân loại và vẽ sơ đồ:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" architecture --out "D:\AgentOutput\architecture"
```

Nếu muốn Qwen tóm tắt module, dùng cùng lệnh với `--ai-summary`; model mặc định vẫn là `qwen3:8b`, `num_ctx=2048`.

## Kết quả

Trong thư mục output:

- `architecture.md`, `architecture.drawio`: sơ đồ và bằng chứng liên kết module.
- `module_summary.md`: mô tả vai trò từng module từ comment, cấu trúc và các liên kết.
- `stack_architecture.md`: thống kê FE/BE/DB, framework, database và object roles.
- `frontend_architecture.drawio`, `backend_architecture.drawio`: object roles và các liên kết **tĩnh thực tế** tìm được từ source.
- `fe_be_architecture.drawio`: những quan hệ tĩnh giữa FE, BE và database.
- `frontend_reference.drawio`, `backend_reference.drawio`: mô hình tổ chức tham khảo theo framework đã nhận diện. Đường nét đứt **không chứng minh** tồn tại trong mã.
- `middle-files/stack_architecture.json`: chi tiết bằng chứng, cùng những JSON/CSV/cache từ các bước trước.

## Dấu hiệu và độ tin cậy

FE: MXML, ActionScript, Apache Flex, Adobe AIR. BE: Java, Spring MVC/Core, Spring Boot, MyBatis, Hibernate/JPA, Struts, JSF, JDBC. Database: PostgreSQL, MySQL, MariaDB, Oracle, SQL Server, SQLite, H2, DB2 khi thấy driver hoặc JDBC URL.

Nhận diện framework dùng khai báo thư viện và dấu hiệu cú pháp; không kết luận framework đang chạy ở runtime. Root `pom.xml` cũng không chứng minh từng module dùng tất cả thư viện. Phân loại object dựa trên tên file hoặc annotation, chưa phải call graph đã xác minh.

## Tài liệu framework tham khảo

- [Apache Flex](https://flex.apache.org/)
- [Adobe AIR](https://airsdk.harman.com/)
- [Spring Framework](https://docs.spring.io/spring-framework/reference/)
- [MyBatis](https://mybatis.org/mybatis-3/)
- [Hibernate](https://hibernate.org/orm/)
- [JDBC](https://docs.oracle.com/javase/tutorial/jdbc/basics/)

Các chuẩn kiến trúc tham khảo không thay thế bằng chứng từ source của repository.

## v4.6 — Reference nodes backed by source objects

`frontend_reference.drawio` and `backend_reference.drawio` now draw an expected role **only when one or more scanned files match that role**. Each displayed node includes the number of matching source objects and up to three source paths. Reference arrows are dashed conceptual patterns **within the same detected framework**, never verified runtime calls.

Roles without matching objects are not shown as `0 objects` nodes. Inspect the **Đối chiếu Reference với source** section of `stack_architecture.md` or `middle-files/stack_architecture.json` (`reference_role_coverage`) for the complete found/not_found inventory. A missing role means no file was matched by the current naming/annotation heuristics, not proof that the feature does not exist.

No additional Ollama calls are required for FE/BE reference diagrams. Run `architecture` again to regenerate them.
