## Mục lục

- [Danh sách source](#danh-s-ch-source)
- [Tham chiếu phát hiện được](#tham-chi-u-ph-t-hi-n-c)
- [Giới hạn và cần xác minh](#gi-i-h-n-v-c-n-x-c-minh)

---

<a id="b-o-c-o-ph-n-t-ch-source-code-t-nh"></a>
# Báo cáo phân tích source code (tĩnh)

> Đây là kết quả dò tham chiếu dạng text, KHÔNG phải call graph runtime đã được xác minh.

- Project: `sample_project`
- Chủ đề lọc: `Order`
- Ngày xuất: 2026-10-19 02:10
- Phạm vi: 5 source files (giới hạn tối đa 35)

<a id="danh-s-ch-source"></a>
## Danh sách source

| Đường dẫn | Loại |
|---|---|
| `frontend/OrderScreen.mxml` | `.mxml` |
| `backend/OrderService.java` | `.java` |
| `backend/OrderMapper.xml` | `.xml` |
| `frontend/OrderActions.as` | `.as` |
| `db/schema.sql` | `.sql` |

<a id="tham-chi-u-ph-t-hi-n-c"></a>
## Tham chiếu phát hiện được

| Source | Target | Bằng chứng |
|---|---|---|
| `backend/OrderMapper.xml` | `TABLE:order_header` | SQL text reference (so khớp tên hoặc SQL) |
| `backend/OrderService.java` | `backend/OrderMapper.xml` | Name reference (so khớp tên hoặc SQL) |
| `db/schema.sql` | `TABLE:order_header` | SQL text reference (so khớp tên hoặc SQL) |

<a id="gi-i-h-n-v-c-n-x-c-minh"></a>
## Giới hạn và cần xác minh

- Quan hệ tên gọi và SQL text là dấu hiệu tham chiếu, không đủ để kết luận thứ tự gọi hàm hoặc hành vi runtime.
- SQL động, reflection, Dependency Injection, remoting AIR, mapper framework có thể không được phát hiện.
- Sơ đồ Draw.io tương ứng là **editable**, các mũi tên thể hiện tham chiếu tĩnh, không chứng minh data flow.
- Khi cần thiết kế chức năng chi tiết, dùng lệnh `design --topic ...` để AI điều tra và tạo bản thảo có dẫn chứng.
