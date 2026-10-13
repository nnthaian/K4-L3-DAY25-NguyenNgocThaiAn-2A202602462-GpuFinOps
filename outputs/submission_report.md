# NimbusAI GPU FinOps — Bài viết tổng kết

## 1. Baseline và Optimized

Trong bài lab, tôi phân tích telemetry GPU, catalog giá tháng 06/2026 và 2.400 request LLM của NimbusAI. Kết quả cho thấy chi phí GPU hàng tháng giảm từ **$27,133** xuống còn **$14,626**, tương đương tiết kiệm **$12,507 (46.1%)**.

Đối với inference, chi phí giảm từ **$6.488 xuống $1.126 trên mỗi 1M-token**, tương đương giảm **82.6%**. Kết quả này đạt được bằng cách kết hợp cascade routing, prompt caching và Batch API.

## 2. Phân tích các đòn bẩy tiết kiệm

Đòn bẩy đóng góp nhiều nhất là chiến lược purchasing, tiết kiệm khoảng **$10,040/tháng**. Các workload có thể gián đoạn được chuyển sang spot instance kèm checkpoint, còn workload có duty cycle cao được dùng reserved instance. Cách này phù hợp hơn so với chạy toàn bộ GPU bằng on-demand.

Inference optimization đóng góp khoảng **$1,212/tháng**. Cascade routing chuyển các request đơn giản sang model nhỏ hơn, prompt caching giảm giá phần input lặp lại, còn Batch API giảm chi phí cho các request không yêu cầu phản hồi real-time.

Ngoài ra, việc right-size các GPU sử dụng kém hiệu quả giúp tiết kiệm khoảng **$655/tháng**, và tắt các GPU idle giúp tiết kiệm thêm khoảng **$600/tháng**.

## 3. GPU-Util Lie

GPU `gpu-h100-4` có GPU-Util khoảng **98.2%**, nhưng MFU chỉ **0.194**. GPU `gpu-a10g-1` cũng có Util cao nhưng MFU chỉ **0.268**. Đây là ví dụ của “GPU-Util lie”: GPU đang bận theo góc nhìn clock/kernel nhưng không thực hiện đủ lượng phép tính hữu ích.

Nguyên nhân có thể là memory stall, kernel launch overhead hoặc pipeline phải chờ dữ liệu. Nếu chỉ nhìn GPU-Util, NimbusAI có thể tưởng rằng GPU đang được sử dụng hiệu quả và tiếp tục mua thêm GPU, dẫn tới trả tiền cho năng lực tính toán không được khai thác. Vì vậy cần theo dõi thêm MFU, MBU và `$ / 1M-token`.

Telemetry cũng cho thấy idle GPU gây lãng phí khoảng **$20/ngày**, tương đương **$600/tháng**.

## 4. Hai phần mở rộng đã thực hiện

### Right-sizing theo MBU

Extension đầu tiên bổ sung tính toán `$/GB-VRAM`, bandwidth thực tế và GPU thay thế cho workload memory-bound với mục tiêu MBU 60%. Một số cơ hội đo được là thay H100 bằng MI300X, tiết kiệm khoảng **$0.55/GPU-giờ**; thay H100 bằng A100, tiết kiệm khoảng **$0.71/GPU-giờ**; và thay A10G bằng L4, tiết kiệm khoảng **$0.20/GPU-giờ**.

Insight quan trọng là không nên chọn GPU chỉ dựa trên giá thuê theo giờ. GPU thay thế phải có đủ VRAM và bandwidth để workload không bị chậm hoặc lỗi do thiếu tài nguyên.

### Cache economics với `cache_is_worth_it()`

Extension thứ hai bổ sung hàm kiểm tra cache có thực sự đáng dùng hay không. Với read discount 90% và chi phí ghi cache chuẩn hóa là 1.0, cần ít nhất **1.11 lần đọc lại** để hòa vốn. M2 giả định mỗi cached prefix được đọc lại trung bình **2 lần**, nên cache được bật vì vượt điểm hòa vốn.

Điều này giúp tránh áp dụng prompt caching một cách máy móc cho các prefix chỉ được đọc một lần.

## 5. Khuyến nghị cho NimbusAI

Nếu là FinOps lead, tôi sẽ ưu tiên ba hành động sau:

1. Chuyển training và batch workload có thể gián đoạn sang spot instance kèm checkpoint; chỉ cam kết reserved khi duty cycle ổn định trên 55%.
2. Xây dựng dashboard theo dõi MFU, MBU, idle hours và `$ / 1M-token`, thay vì dùng GPU-Util làm chỉ số duy nhất.
3. Bắt buộc tagging theo team/project, duy trì tag coverage trên 80% trước khi chargeback, đồng thời áp dụng cache policy dựa trên số lần đọc lại thực tế.

Cuối cùng, mỗi query hiện tiêu thụ khoảng **0.24 Wh** và phát thải **0.091 gCO2e**. Region được đề xuất là **europe-north1** vì có kết hợp tốt giữa chi phí thấp và nguồn điện sạch. Các số liệu này là snapshot tháng 06/2026 và cần được cập nhật lại trước khi áp dụng vào hệ thống thực tế.
