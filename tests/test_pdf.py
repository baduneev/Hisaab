from datetime import date
from decimal import Decimal
from io import BytesIO
from pypdf import PdfReader
from api.models import Tenant, Contact, Document
from api.pdf import invoice_pdf


def test_bilingual_pdf_retains_latin_labels_and_invoice_number():
    tenant=Tenant(name="हिमालय ट्रेडिङ",address="काठमाडौं",pan="123456789")
    contact=Contact(name="पोखरा पसल",address="पोखरा",pan="987654321")
    doc=Document(kind="sale",date=date(2026,11,23),number="INV-2083/84-00001",total=Decimal("1000"),payload={"lines":[{"name":"चामल Rice", "quantity":"1", "unit":"बोरा", "unit_price":"1000", "net":"1000", "total":"1000"}]})
    content=PdfReader(BytesIO(invoice_pdf(tenant,doc,contact))).pages[0].extract_text()
    assert "Internal transaction record" in content
    assert "INV-2083/84-00001" in content
    assert "Product" in content
    assert "NPR" in content
