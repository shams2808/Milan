# 🚀 Milan — Production Deployment Guide

Milan is engineered with **zero external pip dependencies** and runs entirely on the **Python 3.10+ standard library**.

Because Milan performs heavy in-memory financial matching (10,000+ invoices in seconds) and generates multi-sheet Excel workbooks, deploying as a **persistent container or VPS** is the recommended architecture.

---

## 🌟 Recommended Deployment Options

### Option 1: Render / Railway / Fly.io (Fastest 1-Click Cloud Deployment)
These platforms run persistent Docker containers, handle automatic HTTPS/SSL certificates, and respect the `$PORT` environment variable out of the box.

1. **Push your code to GitHub**:
   ```bash
   git push origin master
   ```
2. **Deploy on Render / Railway**:
   - Create a new **Web Service** pointing to your repository.
   - Environment: **Docker** (Render / Railway will automatically detect `Dockerfile`).
   - Done! Your live app will be accessible at your public URL (e.g. `https://milan-gst.onrender.com`).

---

### Option 2: Linux VPS / Cloud VM (DigitalOcean, AWS, GCP, Linode, Hetzner)
Run Milan as a persistent background daemon with automatic restart on server reboot.

1. **Clone repository on the server**:
   ```bash
   git clone <your-repo-url> /opt/milan
   cd /opt/milan
   ```

2. **Create a Systemd Service** (`/etc/systemd/system/milan.service`):
   ```ini
   [Unit]
   Description=Milan GST Reconciliation Platform
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/opt/milan
   ExecStart=/usr/bin/python3 -m milan.web --host 127.0.0.1 --port 8000
   Restart=always
   RestartSec=3
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```

3. **Enable and start the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now milan
   ```

4. **Nginx Reverse Proxy with SSL (Certbot)**:
   ```nginx
   server {
       server_name milan.yourdomain.com;
       client_max_body_size 64M;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
   Install free SSL with Let\'s Encrypt:
   ```bash
   sudo certbot --nginx -d milan.yourdomain.com
   ```

---

### Option 3: Local CA Office Network (LAN / VPN)
For Chartered Accountant firms that want **100% data residency** inside the office with zero data leaving the building:

1. On a dedicated office machine or server:
   ```bash
   python -m milan.web --host 0.0.0.0 --port 8000
   ```
2. Find the local IP of that machine (e.g., `192.168.1.50`).
3. Every partner, CA, and article clerk in the office can open:
   `http://192.168.1.50:8000`
   All matching happens 100% locally with zero cloud telemetry.

---

## 🔒 Security & Privacy Guarantees
- **Zero Cloud Telemetry**: Milan never makes external API requests or transmits client financial records to third parties.
- **Automated Session Eviction**: Uploaded sessions are automatically purged after 2 hours or when exceeding capacity, preventing disk bloat.
- **Security Headers**: Standard `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and strict referrer policy enabled.
