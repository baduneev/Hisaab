"""Generate a representative bilingual invoice using the actual PDF renderer."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.models import Tenant, Contact, Document
from api.pdf import invoice_pdf

tenant = Tenant(name="हिमालय ट्रेडिङ कम्पनी", address="टेकु, काठमाडौं, नेपाल", pan="123456789")
contact = Contact(name="पोखरा किराना पसल", address="नयाँ बजार, पोखरा", pan="987654321")
doc = Document(id="qa", kind="sale", date=date(2026,11,23), number="INV-2083/84-00001", total=Decimal("21500"), payload={"notes":"सामान प्राप्त भएपछि विवरण जाँच गर्नुहोस्। यो आन्तरिक परीक्षण अभिलेख हो।", "lines":[{"name":"बासमती चामल (२५ किलो)","quantity":"10","unit":"बोरा","unit_price":"2150","net":"21500","total":"21500"}]})
path = Path("artifacts/pdf/bilingual-invoice.pdf")
path.parent.mkdir(parents=True,exist_ok=True)
path.write_bytes(invoice_pdf(tenant,doc,contact))
print(path.resolve())
