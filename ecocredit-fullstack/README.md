# EcoCredit - Full-stack Hackathon MVP

EcoCredit helps verified campus students exchange useful items rather than buying new ones. This MVP includes login, item listings, swap requests, Eco Points, and an SQLite database.

## Technology

- Frontend: HTML, CSS, JavaScript
- Backend: Python Flask
- Database: SQLite

## Run it locally

1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run:

```powershell
python -m pip install -r requirements.txt
python app.py
```

4. Open `http://127.0.0.1:5000` in your browser.

Use any college email and a password of at least 4 characters. This is demo authentication; use real password verification and a strong `SECRET_KEY` before public deployment.

## GitHub note

You can upload this project to GitHub. GitHub Pages cannot run Python/Flask, so it can host only the frontend. To host the complete app, deploy it to Render, Railway, or PythonAnywhere.
