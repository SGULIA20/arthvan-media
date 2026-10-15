import json, subprocess, sys, urllib.request
LANG = sys.argv[1] if len(sys.argv) > 1 else "en"
COUNTRY = (sys.argv[4] if len(sys.argv) > 4 else "IN").upper()
COUNTRIES_TBL = {"IN": ("India", "INR", "₹"), "NG": ("Nigeria", "NGN", "₦"), "KE": ("Kenya", "KES", "KSh "), "GH": ("Ghana", "GHS", "GH₵"), "AE": ("United Arab Emirates", "AED", "AED "),
                 "GB": ("United Kingdom", "GBP", "£"), "US": ("United States", "USD", "$"), "AU": ("Australia", "AUD", "A$"), "NZ": ("New Zealand", "NZD", "NZ$"),
                 "DE": ("Germany", "EUR", "€"), "FR": ("France", "EUR", "€"), "ES": ("Spain", "EUR", "€"), "IT": ("Italy", "EUR", "€"), "PT": ("Portugal", "EUR", "€"),
                 "NL": ("Netherlands", "EUR", "€"), "FI": ("Finland", "EUR", "€")}
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
from playwright.sync_api import sync_playwright
BASE="http://localhost:8091"; LOCAL="http://localhost:9999/.netlify/functions/"
SESSION={"phone":"","sessionToken":"","name":"Ramesh","businessName":"Sharma General Store","businessType":"Retail / Shop","plan":"starter","founder":True,"isAdmin":False,"country":{"code":COUNTRY}}
PLAN={"plan":"trial","businessName":"Sharma General Store","phone":"9876543210","registeredAt":"2026-10-01T00:00:00Z","planExpiresAt":None,"planLabel":None,"aiIncluded":True,"planEndsAt":None,"actor":"owner","staffName":None,"staffId":None,"shop":None,"shops":1,"country":{"code":COUNTRY,"name":COUNTRIES_TBL[COUNTRY][0],"currency":COUNTRIES_TBL[COUNTRY][1],"symbol":COUNTRIES_TBL[COUNTRY][2]},"hasAccess":True,"trialDays":30,"trialDaysLeft":21}
SAMPLE_INVOICES = {"invoices": [
    {"id": "i3", "invoiceNumber": "INV-0003", "customerName": "Mehta Interiors", "customerPhone": None, "totalAmount": 8000, "subtotal": 8000, "gstRate": 0, "gstAmount": 0,
     "lineItems": [{"description": "Paint 20L", "quantity": 2, "unitPrice": 2400}, {"description": "Cement bags", "quantity": 8, "unitPrice": 400}], "createdAt": "2026-10-12T10:00:00Z", "pdfUrl": None},
    {"id": "i2", "invoiceNumber": "INV-0002", "customerName": "Ramesh Traders", "customerPhone": None, "totalAmount": 4200, "subtotal": 4200, "gstRate": 0, "gstAmount": 0,
     "lineItems": [{"description": "Sand (trolley)", "quantity": 1, "unitPrice": 3000}, {"description": "Cement bags", "quantity": 3, "unitPrice": 400}], "createdAt": "2026-10-04T10:00:00Z", "pdfUrl": None},
    {"id": "i1", "invoiceNumber": "INV-0001", "customerName": "Kavita Boutique", "customerPhone": None, "totalAmount": 1600, "subtotal": 1600, "gstRate": 0, "gstAmount": 0,
     "lineItems": [{"description": "Cement bags", "quantity": 4, "unitPrice": 400}], "createdAt": "2026-10-01T10:00:00Z", "pdfUrl": None}]}
SAMPLE_TICKETS = {"tickets": [
    {"id": "t2", "ticketNo": "SMB-2026-000002", "category": "score", "status": "open", "message": "I added many entries but my score looks the same.", "reply": None, "createdAt": "2026-10-14T09:00:00Z", "updatedAt": "2026-10-14T09:00:00Z"},
    {"id": "t1", "ticketNo": "SMB-2026-000001", "category": "entries", "status": "answered", "message": "A sale I wrote yesterday is missing from My Book.", "reply": "Thank you for telling us. We found it and put it back. Please check your book and write again if it is still missing.", "createdAt": "2026-10-13T09:00:00Z", "updatedAt": "2026-10-13T15:00:00Z"}]}
CONTACT_HISTORY = {"transactions": [
    {"id": "h4", "type": "payment_in", "amount": 5000, "entryDate": "2026-10-11", "paymentStatus": "paid", "note": "Part payment"},
    {"id": "h3", "type": "sale", "amount": 8000, "entryDate": "2026-10-09", "paymentStatus": "credit", "note": ""},
    {"id": "h2", "type": "sale", "amount": 4000, "entryDate": "2026-10-05", "paymentStatus": "paid", "note": ""},
    {"id": "h1", "type": "sale", "amount": 3000, "entryDate": "2026-10-02", "paymentStatus": "credit", "note": ""}],
    "statement": {"balance": 6000, "direction": "they_owe_you", "label": "Mehta Interiors owes you"}}
MOCKS = {"get-invoices": SAMPLE_INVOICES, "get-my-tickets": SAMPLE_TICKETS}
ROUTES=["dashboard","book","result","cash-reality","profit-loss","score-history","advisor","tasks"]
# the other verified, demo-able features (content/features.json): python3 capture_scoremybiz.py <lang> <outdir> more
MORE=["business-card","daily-update","cash-flow","payables","invoices","quotations","items","money-now","cash-book","registers","balance-sheet","year-end",
      "goals","game","notifications","plan","staff","calculator","personal-calculator","alerts","network","edit-profile","export-book","book-locks","book-changes","break-even",
      "business-simulator","decision-simulation","ledger-statement","reconcile","support"]
if len(sys.argv)>3 and sys.argv[3]=="more": ROUTES=MORE
elif len(sys.argv)>3 and sys.argv[3]!="core": ROUTES=sys.argv[3].split(",")        # e.g. daily-update,book
CLEAN_JS = r"""() => {   // remove the dev-build warning bubble and any "Founder test mode" notice, with the box that holds only that text
  const pat = /cannot contain a nest|Founder test mode|This is sample mode|Sample mode|सैंपल मोड|सैम्पल मोड|Unhandled|Warning:/i;
  const norm = s => (s || '').replace(/\s+/g, '');
  const hits = [...document.querySelectorAll('*')].filter(e => pat.test(e.innerText || '') && (e.innerText || '').length < 1500 && ![...e.children].some(c => pat.test(c.innerText || '')));
  hits.forEach(e => { let n = e; while (n.parentElement && n.parentElement !== document.body && norm(n.parentElement.innerText) === norm(n.innerText)) n = n.parentElement; n.remove(); });
}"""
def handle(route, req):
    fn=req.url.split("/functions/")[1].split("?")[0]
    if fn == "get-transactions" and b'"contactId"' in (req.post_data_buffer or b""):
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(CONTACT_HISTORY))
    if fn in MOCKS:
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(MOCKS[fn]))
    if fn=="check-plan":
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(PLAN))
    try:
        r=urllib.request.Request(LOCAL+fn, data=req.post_data_buffer or b"{}", method="POST", headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(r, timeout=60) as resp:
            body=resp.read(); status=resp.status
    except urllib.error.HTTPError as e:
        body=e.read(); status=e.code
    route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=body)
seen={}
with sync_playwright() as p:
    b=p.chromium.launch()
    ctx=b.new_context(viewport={"width":390,"height":844}, device_scale_factor=3, is_mobile=True, has_touch=True, locale="en-IN", timezone_id="Asia/Kolkata", geolocation={"latitude":28.61,"longitude":77.2}, permissions=["geolocation"])
    ctx.add_init_script("try{localStorage.setItem('smb_session', %s); localStorage.setItem('smb_country','%s'); localStorage.setItem('smb_country_ip','%s'); localStorage.setItem('smb_lang','%s'); localStorage.setItem('smb_user_name','Sharma Building Supplies');}catch(e){}" % (json.dumps(json.dumps(SESSION)), COUNTRY, COUNTRY, LANG))
    ctx.route("https://scoremybiz.com/.netlify/functions/**", lambda route, req: (seen.setdefault(req.url.split('/functions/')[1],0), handle(route, req)))
    pg=ctx.new_page()
    for r in ROUTES:
        name, route = r.split("@", 1) if "@" in r else (r, r)          # "name@route?query" saves route as name.png
        try:
            pg.goto(f"{BASE}/{route}", wait_until="networkidle", timeout=60000); pg.wait_for_timeout(4000)
            pg.evaluate(CLEAN_JS); pg.wait_for_timeout(400)
            pg.screenshot(path=f"{OUT}/{name}.png"); print(name,"ok")
        except Exception as e: print(name,"ERR",str(e)[:70])
    b.close()
print("functions called:", sorted(seen))
