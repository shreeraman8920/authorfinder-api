# Deploy AuthorFinder API to Fly.io

Fly.io supports Docker containers, so Playwright/Chromium works perfectly.

## Prerequisites

1. Install flyctl:
```bash
curl -L https://fly.io/install.sh | sh
```

2. Sign up for Fly.io:
```bash
fly auth signup
# or if you have an account:
fly auth login
```

## Deploy

### Step 1: Launch the app

```bash
cd "E:\Author Extraction App"
fly launch
```

When prompted:
- **App Name**: `authorfinder-api` (or press Enter for default)
- **Region**: Choose closest to your users
- **Override config**: No (use the fly.toml we created)

### Step 2: Deploy

```bash
fly deploy
```

This will:
1. Build the Docker image (includes Playwright + Chromium)
2. Deploy to Fly.io
3. Your API will be live at: `https://authorfinder-api.fly.dev`

### Step 3: Test

```bash
# Health check
curl https://authorfinder-api.fly.dev/health

# Extract author
curl -X POST https://authorfinder-api.fly.dev/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://endpoints.news/merck-brings-welireg-keytruda-combo-to-treat-kidney-cancer/"}'
```

## Useful Commands

```bash
# Check status
fly status

# View logs
fly logs

# Scale to zero (stop when not in use)
fly scale count 0

# Scale back up
fly scale count 1

# Restart
fly machines restart

# Update environment variables
fly secrets set MY_KEY=value

# Delete the app
fly apps destroy authorfinder-api
```

## Free Tier Limits

- **3 shared-cpu-1x VMs** (256MB RAM each)
- **160GB bandwidth/month**
- **3 persistent volumes** (if needed)
- Machines auto-stop after inactivity (cold start ~30s)

## Cost

Fly.io free tier includes:
- 3 shared VMs with 256MB RAM
- Enough for moderate API usage

For heavier usage, paid plans start at $5/month.

## Environment Variables

To set custom configuration:

```bash
fly secrets set AUTHORFINDER_API_KEY=your-secret-key
fly secrets set AUTHORFINDER_MAX_CONCURRENT=5
fly secrets set AUTHORFINDER_TIMEOUT=20
fly secrets set AUTHORFINDER_DELAY=1.5
```

## Architecture

```
User Request
     |
     v
Fly.io Load Balancer (HTTPS)
     |
     v
Docker Container (Python + Playwright + Chromium)
     |
     v
AuthorFinder API (FastAPI)
     |
     v
Article Website
```

## Troubleshooting

### Build fails
- Check Docker is installed and running
- Try `fly deploy --verbose` for more output

### Playwright fails
- The Dockerfile includes all Chromium dependencies
- Check logs: `fly logs`

### Cold starts are slow
- First request after inactivity takes ~30s
- This is normal for Fly.io free tier
- Consider setting `min_machines_running = 1` for always-on (costs money)

### Out of memory
- Upgrade to 2GB: `fly scale memory 2g`
- Or upgrade VM: `fly scale count 1 --vm shared-cpu-2x`

## Update the Frontend

After deploying the API, update the frontend `app.js`:

```javascript
const API_BASE = 'https://authorfinder-api.fly.dev';
```
