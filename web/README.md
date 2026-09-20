# AuthorFinder Web Interface

A professional, responsive web interface for the AuthorFinder API.

## Architecture

```
User Browser
     |
     v
AuthorFinder Web UI (this folder)
     |
     | HTTPS
     v
https://authorfinder-api.onrender.com
     |
     v
FastAPI + AuthorFinder
     |
     v
Playwright / Chromium
     |
     v
Article
```

## Local Development

### Quick Start

1. Open the `web/` folder in your terminal
2. Start a local server:

```bash
# Python
python -m http.server 3000

# Node.js
npx serve .

# PHP
php -S localhost:3000
```

3. Open http://localhost:3000 in your browser

### No Build Step Required

This is a static site — no compilation, bundling, or build tools needed. Just serve the files.

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /health` | GET | Check if API is online |
| `POST /crawl` | POST | Extract author from single URL |
| `POST /crawl/batch` | POST | Extract authors from multiple URLs |

## API URL

The frontend connects to:

```
https://authorfinder-api.onrender.com
```

This is configured in `app.js` as `API_BASE`.

## CORS

The backend API has CORS configured with:

```python
allow_origins=["*"]
```

This allows browser requests from any origin. No backend changes needed.

## Features

- Single URL author extraction
- Batch CSV upload (up to 50 URLs)
- Copy-to-clipboard for extracted values
- View raw JSON response
- API health status indicator
- Mobile-responsive design
- Accessible form controls
- Error handling for all failure modes

## Deploy to Render (Static Site)

### Option 1: From GitHub

1. Push this `web/` folder to a GitHub repository
2. Go to [render.com](https://render.com) → **New +** → **Static Site**
3. Connect your repository
4. Configure:
   - **Name**: `authorfinder-web`
   - **Build Command**: (leave empty)
   - **Publish Directory**: `web`
5. Click **Create Static Site**

### Option 2: Manual Upload

1. Zip the `web/` folder
2. Go to [render.com](https://render.com) → **New +** → **Static Site**
3. Upload the zip
4. Your site will be live at `https://your-site.onrender.com`

## Deploy to GitHub Pages

1. Push the `web/` folder contents to a `gh-pages` branch
2. Enable GitHub Pages in repository settings
3. Your site will be at `https://username.github.io/repo-name/`

## Deploy to Netlify

1. Go to [netlify.com](https://netlify.com)
2. Drag and drop the `web/` folder
3. Your site will be live immediately

## Limitations

- The frontend does not run any extraction logic — all processing happens via the API
- Batch processing is limited to 50 URLs by the API
- The API may take 10-30 seconds per URL (Playwright rendering)
- Free tier Render services spin down after inactivity — first request may be slow

## File Structure

```
web/
├── index.html    # Main HTML structure
├── style.css     # Responsive CSS styles
├── app.js        # API integration and UI logic
└── README.md     # This file
```

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome for Android)
