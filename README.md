# Dutch Bookkeeping Tool

Free, self-hosted bookkeeping application built with Dash — designed for Dutch freelancers and small businesses (ZZP/BV).

## Features

- Income & expense tracking with Dutch BTW (VAT) rates (21%, 9%, 0%)
- Quarterly BTW filing summaries
- Profit & loss reports
- CSV bank statement import
- Excel/CSV export for your accountant
- Dashboard with interactive charts

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:8050 in your browser.

## Data

All data is stored locally in `data/bookkeeping.json`. Back up this file regularly.
