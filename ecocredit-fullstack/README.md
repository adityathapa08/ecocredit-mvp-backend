# EcoCredit - Full-stack Hackathon MVP

EcoCredit is a campus circular marketplace for reusing useful items. Students can swap for Eco Points or sell for rupees with secure in-app wallet payment after acceptance.

## Included in V2

- Separate account creation and login
- Private profile dashboard for editing campus details, listings, and requests
- Search plus Books, Furniture, Electronics, and Clothing categories
- Required condition, photo, actual price, selling price, and 5% platform-fee notice
- Pending → accepted → delivered request flow, with a 7-day listing exchange window
- Anonymous in-app chat after acceptance; phone numbers, emails, and social-media/contact details are blocked
- Buyer rating after a delivered exchange
- Live anonymous chat that polls for new messages while the chat window is open (no manual refresh)
- Notification centre for requests, acceptance, messages, wallet activity, delivery, and ratings
- EcoCredit wallet with add-money ledger entries, purchase settlement after a 5% platform fee, wallet history, and UPI withdrawal requests
- QR-only pickup confirmation: the seller shows a one-time QR after payment is held; the buyer scans it to release escrow payment

## Wallet safety note

The wallet is deliberately a **demo simulation**: add-money and UPI withdrawal update the local SQLite ledger only. It does not collect money, connect to a bank, or send a real UPI transfer.

For a real deployment, integrate a regulated payment provider (for example Razorpay), verify webhooks before crediting wallets, keep funds in a compliant escrow/settlement flow, encrypt sensitive data, and use a production database. Do not treat the demo ledger as a real payment system.

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

Create an account with a college email and a password of at least 4 characters. This remains a hackathon demo: set a strong `SECRET_KEY`, use a production database, and add genuine college-email verification before public deployment.

## GitHub note

You can upload this project to GitHub. GitHub Pages cannot run Python/Flask, so it can host only the frontend. To host the complete app, deploy it to Render, Railway, or PythonAnywhere.
