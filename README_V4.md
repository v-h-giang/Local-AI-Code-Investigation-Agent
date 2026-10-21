# Local Code Investigation Agent v4 — Full-repository, resumable

## Mục lục

- [1. Chạy một lệnh](#run)
- [2. Cách khôi phục khi hết pin](#resume)
- [3. Đầu ra và theo dõi](#output)
- [4. Phạm vi và hạn chế](#limits)
- [5. Kiểm thử](#tests)

<a id="run"></a>
## 1. Chạy một lệnh

Mở PowerShell tại thư mục `local_code_agent`:

```powershell
py -3 agent.py --project "D:\Work\LegacyProject" --model qwen3:8b --num-ctx 2048 design --out "D:\AgentOutput\overview"
```

- `index` tự động chạy nếu cần.
- Không yêu cầu `--topic` và **không còn mặc định 24 batch × 2 file**.
- Mọi file source đủ điều kiện được duyệt, bao gồm toàn bộ các đoạn của file dài.
- Ollama được gọi **tuần tự, từng đoạn ngắn** nhằm hạn chế tiêu thụ RAM.
- **Không** chạy song song hai lệnh `design` trên cùng output directory.
- `qwen3:8b` được giữ nguyên; context mặc định 2048.

<a id="resume"></a>
## 2. Khôi phục khi hết pin / mất điện / Ollama bị lỗi

Chạy lại **đúng lệnh trước đó**, giữ cùng `--project`, `--out`, `--model`, `--num-ctx`.

Mỗi chunk hoàn thành được ghi thành checkpoint riêng trong:

```text
D:\AgentOutput\overview\.investigation_cache\chunks\...
```

Checkpoint được ghi vào file tạm, `fsync`, rồi đổi tên nguyên tử để tránh file JSON bị ghi dang dở. Nếu mất điện **trong lúc Qwen đang trả lời**, chunk đang xử lý có thể phải làm lại; chunk trước đó đã lưu sẽ được bỏ qua. File thay đổi nội dung, model/context/prompt thay đổi sẽ được phân tích lại bằng checkpoint mới.

Đừng xóa `.investigation_cache`, đừng sử dụng `--no-resume` khi muốn tiếp tục.

Không cần giữ máy liên tục 24/7. Khi Windows tắt hoặc laptop hết pin, chạy lại lệnh để tiếp tục. **Agent không tự bật máy hay tự khởi chạy sau khi Windows boot**; muốn vậy cần thêm Windows Task Scheduler.

<a id="output"></a>
## 3. Đầu ra

```text
D:\AgentOutput\overview\
├── system_overview.md        # Khảo sát tĩnh toàn repo, mục lục
├── repository_files.csv      # Danh mục file quét
├── repository_overview.json  # Dữ liệu quét tĩnh
├── system_overview.drawio    # Sơ đồ module tĩnh chỉnh sửa được
├── architecture_design.md   # Mục lục liên kết từng báo cáo file
├── analysis_files\           # Báo cáo theo từng file source
├── analysis_manifest.json   # Số file/chunk hoàn tất, còn lại, lỗi
└── .investigation_cache\    # Checkpoint durable; không xóa
    └── chunks\
```

Ví dụ terminal:

```text
[AI 150/43217] frontend/MyScreen.mxml:125-156 (cached=29, completed=149)
[Progress] 43217/43217 chunks; 8000/8000 files. Status=complete
```

Số chunk thực tế được tính từ source, không cố định 43.217.

Khi lỗi giữa chừng, manifest ghi `"status": "incomplete"`, CLI trả về exit code **2**, nhưng checkpoint đã hoàn thành vẫn tồn tại. Khi chạy lại, agent sẽ tính lại và tiếp tục từ những chunk chưa có checkpoint hợp lệ. `analysis_manifest.json` có thể chưa kịp cập nhật khi mất điện đột ngột; checkpoint mới là dữ liệu phục hồi đáng tin cậy.

<a id="limits"></a>
## 4. Phạm vi và giới hạn

- Repository khoảng **8.000 file** nằm dưới giới hạn **25.000 source file hợp lệ** của bộ scanner hiện tại.
- Chỉ đọc extension được hỗ trợ; bỏ qua symlink, thư mục build/binary, và file **lớn hơn 1 MB**. Điều này có nghĩa “toàn repository” ở đây là **toàn bộ file đủ điều kiện được scanner nhận diện**, không phải mọi file bất kể loại/kích thước.
- Các file lớn dưới 1 MB được chia thành nhiều đoạn, không chỉ lấy vài dòng đầu.
- Mỗi chunk được Qwen phân tích riêng; chưa tự tổng hợp mối liên kết runtime giữa mọi file thành thiết kế logic hoàn chỉnh. Markdown là báo cáo điều tra có dẫn chứng, còn Draw.io hiện biểu diễn module tĩnh.
- Bản đầu có thể chạy lâu đối với 8.000 file và sinh rất nhiều checkpoint; dung lượng đĩa, tốc độ CPU/GPU, số dòng mỗi file và thời gian Ollama phản hồi quyết định tổng chi phí.
- Checkpoint, prompt và đầu ra có thể chứa dữ liệu source nội bộ; chỉ lưu trong ổ đĩa tin cậy, không chia sẻ nếu chưa kiểm tra.
- Khi file thay đổi, chỉ checkpoint của chunk không còn khớp mới bị vô hiệu hóa; các file không đổi được tái sử dụng.
- Đây là công cụ đọc source read-only, không tự sửa source, chạy chương trình hay SQL.

<a id="tests"></a>
## 5. Kiểm thử

```powershell
py -3 -m unittest discover -s tests -v
```

Kiểm thử mô phỏng Ollama lỗi sau 29 chunks, khởi động lại và tiếp tục hoàn tất, kiểm thử thay đổi file làm mất hiệu lực cache, và kiểm thử file dài nhiều chunk. **Chưa xác nhận chạy trên repository thật 8.000 file hoặc trên Ollama/Windows của bạn.**
