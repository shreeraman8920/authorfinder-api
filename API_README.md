# AuthorFinder API

Extract journalist/author contact information from news article URLs.

## Deploy to Render (Free)

### Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/authorfinder-api.git
git push -u origin master
```

### Step 2: Deploy on Render

1. Go to [render.com](https://render.com) and sign up (free)
2. Click **New +** → **Web Service**
3. Connect your GitHub repository
4. Configure:
   - **Name**: `authorfinder-api`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt && python -m playwright install chromium`
   - **Start Command**: `uvicorn api:app --host 0.0.0.0 --port $PORT`
5. Click **Create Web Service**

### Step 3: Get Your API URL

Your API will be live at: `https://authorfinder-api.onrender.com`

## Deploy to Railway (Free)

1. Go to [railway.app](https://railway.app) and sign up
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your repository
4. Railway auto-detects Python — it will work
5. Your API URL: `https://authorfinder-api.up.railway.app`

## Deploy to Fly.io (Free)

1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. Run `fly auth signup` or `fly auth login`
3. In your project folder: `fly launch`
4. `fly deploy`

## API Usage

### Health Check
```bash
curl https://your-api-url.onrender.com/health
```

### Single URL
```bash
curl -X POST https://your-api-url.onrender.com/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.statnews.com/2026/06/13/who-director-general-in-drc-war-greater-concern-than-ebola/"}'
```

### Batch (up to 50 URLs)
```bash
curl -X POST https://your-api-url.onrender.com/crawl/batch \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://url1.com/article", "https://url2.com/article"]}'
```

### Python Client
```python
import requests

API = "https://your-api-url.onrender.com"

# Single URL
r = requests.post(f"{API}/crawl", json={"url": "https://example.com/article"})
print(r.json())

# Batch
r = requests.post(f"{API}/crawl/batch", json={
    "urls": ["https://url1.com", "https://url2.com"]
})
print(r.json())
```

### JavaScript Client
```javascript
const response = await fetch("https://your-api-url.onrender.com/crawl", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ url: "https://example.com/article" })
});
const data = await response.json();
console.log(data);
```

## Response Format

```json
{
  "article_url": "https://...",
  "author": {
    "name": "Nicole DeFeudis",
    "email": "nicole@endpointsnews.com",
    "linkedin": "https://linkedin.com/in/...",
    "twitter": "https://twitter.com/...",
    "job_title": "...",
    "bio": "...",
    "social_links": [...]
  },
  "status": "success",
  "elapsed_seconds": 10.81
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTHORFINDER_API_KEY` | (none) | API key for authentication |
| `AUTHORFINDER_MAX_CONCURRENT` | `5` | Max concurrent crawls |
| `AUTHORFINDER_TIMEOUT` | `20` | Request timeout (seconds) |
| `AUTHORFINDER_DELAY` | `1.5` | Delay between requests |

## Status Codes

| Status | Meaning |
|--------|---------|
| `success` | Author found and extracted |
| `no_author_found` | No author on page |
| `no_author_page` | Author found but no profile page |
| `blocked` | Site blocked the request |
| `paywall` | Content behind paywall |
| `error` | Fetch/extract failed |
