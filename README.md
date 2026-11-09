# Discount Hunter – probe

Kiểm tra Lotte Mart / GO! / Bách Hóa Xanh có trả lời request httpx từ server nước ngoài không.

- GitHub Actions: tab **Actions** → workflow **probe** → **Run workflow** → xem log step "Run probe".
- Render: New → Blueprint → chọn repo này (đọc `render.yaml`) → mở URL → bấm **Chạy probe**.
- PC: `pip install httpx gradio` → `python app.py --cli`
