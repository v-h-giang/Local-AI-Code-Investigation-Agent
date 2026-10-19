## Mục lục

- [Phạm vi và mức độ bao phủ](#ph-m-vi-v-m-c-bao-ph)
- [Các module / thư mục nguồn](#c-c-module-th-m-c-ngu-n)
- [Điểm khởi đầu và dấu hiệu xử lý được phát hiện](#i-m-kh-i-u-v-d-u-hi-u-x-l-c-ph-t-hi-n)
- [Bảng SQL được nhắc đến](#b-ng-sql-c-nh-c-n)
- [Danh sách chức năng / method có thể điều tra](#danh-s-ch-ch-c-n-ng-method-c-th-i-u-tra)
- [Hướng điều tra tiếp theo](#h-ng-i-u-tra-ti-p-theo)
- [Giới hạn và độ tin cậy](#gi-i-h-n-v-tin-c-y)

---

<a id="kh-o-s-t-t-ng-quan-h-th-ng-t-source-code"></a>
# Khảo sát tổng quan hệ thống từ source code

> Tài liệu sinh tự động từ quét mã nguồn tĩnh. Không xác nhận hành vi runtime, không thay thế thiết kế gốc.

<a id="ph-m-vi-v-m-c-bao-ph"></a>
## Phạm vi và mức độ bao phủ

- Repository: `sample_project`
- Số file đã quét: **5**
- Số nhóm thư mục cấp cao: **3**
- Các loại mã: ActionScript: 1, Java: 1, MXML: 1, SQL: 1, XML: 1
- Không quét thư mục bị loại trừ, binary, symlink và file lớn hơn 1 MB.
- Đã chạm giới hạn quét: **Không**
- Số lỗi đọc file: 0

<a id="c-c-module-th-m-c-ngu-n"></a>
## Các module / thư mục nguồn

| Nhóm nguồn | Số file | Công nghệ | Source minh họa |
|---|---:|---|---|
| `backend` | 2 | Java (1), XML (1) | `backend/OrderMapper.xml`, `backend/OrderService.java` |
| `frontend` | 2 | ActionScript (1), MXML (1) | `frontend/OrderActions.as`, `frontend/OrderScreen.mxml` |
| `db` | 1 | SQL (1) | `db/schema.sql` |

<a id="i-m-kh-i-u-v-d-u-hi-u-x-l-c-ph-t-hi-n"></a>
## Điểm khởi đầu và dấu hiệu xử lý được phát hiện

Các dòng sau là **dấu hiệu từ cú pháp** (pattern matches), chưa kết luận là entrypoint đang chạy.

| Dấu hiệu | Vị trí | Câu lệnh minh họa |
|---|---|---|
| SQL mapper statement | `backend/OrderMapper.xml:3` | `<select id="selectOrders" resultType="Order">` |
| SQL DML or schema | `db/schema.sql:1` | `CREATE TABLE order_header (` |
| AIR UI event binding | `frontend/OrderScreen.mxml:13` | `<mx:Button id="refreshButton" label="Refresh" click="loadOrders()"/>` |

<a id="b-ng-sql-c-nh-c-n"></a>
## Bảng SQL được nhắc đến

| Bảng (dò theo câu lệnh SQL) | Số lần xuất hiện |
|---|---:|
| `order_header` | 2 |

<a id="danh-s-ch-ch-c-n-ng-method-c-th-i-u-tra"></a>
## Danh sách chức năng / method có thể điều tra

Các tên dưới đây được trích xuất từ cú pháp source, **chưa gộp thành chức năng nghiệp vụ**.

| Nguồn phát hiện | Tên được khai báo | Vị trí |
|---|---|---|
| SQL mapper id | `selectOrders` | `backend/OrderMapper.xml:3` |
| Java method | `getOrders` | `backend/OrderService.java:4` |
| AS3 function | `getOrders` | `frontend/OrderActions.as:3` |
| AIR handler | `loadOrders` | `frontend/OrderScreen.mxml:13` |

<a id="h-ng-i-u-tra-ti-p-theo"></a>
## Hướng điều tra tiếp theo

1. Mở `system_overview.drawio` để xem tất cả nhóm module **trong giới hạn sơ đồ**; không có mũi tên runtime suy đoán.
2. Dùng `repository_files.csv` để duyệt toàn bộ các đường dẫn source đã quét.
3. Chọn một module hoặc entrypoint trong báo cáo rồi dùng `chat` để truy vết UI → Java → mapper → SQL có `path:line`.
4. Để tạo bản thảo diễn giải AI tự động, dùng `design` **không có `--topic`** hoặc `overview --ai`.

<a id="gi-i-h-n-v-tin-c-y"></a>
## Giới hạn và độ tin cậy

- Nhóm module được chia theo thư mục cấp cao; đây là quy ước cấu trúc, **không phải** kiến trúc thành phần được xác minh.
- Pattern entrypoint và tên bảng chỉ là tín hiệu tĩnh; không chứng minh remote call, luồng thực thi, quan hệ khóa ngoại hoặc tác động nghiệp vụ.
- Không đọc file nhị phân, bytecode, configuration bị loại trừ, SQL generated runtime hoặc nội dung từ database.
- Các extension chưa hỗ trợ, file >1 MB, thư mục build bị loại trừ và giới hạn 25.000 file làm giảm phạm vi.
- Nội dung từ source có thể không đáng tin cậy hoặc chứa thông tin nhạy cảm: kiểm tra và bảo quản output như source.
