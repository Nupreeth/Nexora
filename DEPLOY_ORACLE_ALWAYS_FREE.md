# Deploy Nexora on Oracle Cloud Always Free (No Monthly Cost)

As of **March 3, 2026**, this is the best no-monthly-cost path for keeping the app publicly available without free-tier sleep behavior common on PaaS free plans.

## Why this option
- Oracle Cloud has **Always Free** compute resources (subject to limits/capacity).
- You can run a normal VM with persistent disk, so Flask + SQLite uploads can persist.
- No recurring paid plan is required if you stay within Always Free limits.

## Important constraints
- You still need account verification during signup (credit card verification is usually required).
- Always Free capacity can be unavailable in some regions temporarily.
- Free accounts should remain active with periodic usage.

## 1) Create Oracle VM
1. Sign up for Oracle Cloud Free Tier.
2. Choose a home region where Always Free compute has capacity.
3. Create an Always Free Ubuntu VM.
4. Open ingress ports:
   - `22` (SSH)
   - `80` (HTTP)
   - `443` (HTTPS)

## 2) SSH and install runtime
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
```

## 3) Clone repo and install app
```bash
git clone <YOUR_GITHUB_REPO_URL> /opt/rfpilot-ai
cd /opt/rfpilot-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4) App environment
```bash
cp .env.example .env
```
Edit `.env` and set:
- `SECRET_KEY=<long-random-secret>`
- keep `DATABASE_URL=sqlite:///app.db` (or switch to managed Postgres later)

## 5) Systemd service (Gunicorn)
Create `/etc/systemd/system/rfpilot.service`:

```ini
[Unit]
Description=Nexora Flask App
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/opt/rfpilot-ai
Environment="PATH=/opt/rfpilot-ai/.venv/bin"
ExecStart=/opt/rfpilot-ai/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rfpilot
sudo systemctl start rfpilot
sudo systemctl status rfpilot
```

## 6) Nginx reverse proxy
Create `/etc/nginx/sites-available/rfpilot`:

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and reload:
```bash
sudo ln -sf /etc/nginx/sites-available/rfpilot /etc/nginx/sites-enabled/rfpilot
sudo nginx -t
sudo systemctl restart nginx
```

Now open `http://<YOUR_VM_PUBLIC_IP>`

## 7) HTTPS (recommended)
If you attach a domain, use Certbot:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

## 8) Update workflow
```bash
cd /opt/rfpilot-ai
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart rfpilot
```

## Submission note
Use this VM URL as your live link after deployment, and GitHub repo URL for code.
