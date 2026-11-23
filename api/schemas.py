from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=0, le=Decimal("99999999999"), max_digits=18, decimal_places=2, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(gt=0, le=Decimal("999999999"), max_digits=16, decimal_places=4, allow_inf_nan=False)]
Role = Literal["Owner", "Accountant", "Sales", "Warehouse", "Viewer"]
Kind = Literal["sale", "quotation", "purchase_order", "goods_receipt", "purchase_bill", "sale_return", "purchase_return", "receipt", "payment", "expense", "journal", "opening_balance", "opening_stock", "stock_adjustment", "transfer"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Register(Input):
    company: str = Field(min_length=2, max_length=180)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128)


class Login(Input):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class UserIn(Input):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128)
    role: Role


class ContactIn(Input):
    name: str = Field(min_length=2, max_length=180)
    kind: Literal["customer", "supplier", "both"]
    pan: str = Field(default="", max_length=20, pattern=r"^(\d{9})?$")
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    address: str = Field(default="", max_length=300)
    credit_days: int = Field(default=30, ge=0, le=365)


class ProductIn(Input):
    name: str = Field(min_length=2, max_length=180)
    sku: str = Field(min_length=1, max_length=60)
    category: str = Field(default="General", min_length=1, max_length=80)
    unit: str = Field(default="piece", min_length=1, max_length=30)
    pack_unit: str = Field(default="pack", min_length=1, max_length=30)
    pack_size: Quantity = Decimal("1")
    sale_price: Money = Decimal("0")
    reorder_level: Annotated[Decimal, Field(ge=0, le=999999999, decimal_places=4)] = Decimal("0")


class WarehouseIn(Input):
    name: str = Field(min_length=2, max_length=120)
    branch: str = Field(default="Main branch", min_length=2, max_length=120)


class Item(Input):
    product_id: str
    quantity: Quantity
    unit_price: Money = Decimal("0")
    discount: Money = Decimal("0")
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal("0")
    unit: Literal["base", "pack"] = "base"


class Entry(Input):
    account: str
    debit: Money = Decimal("0")
    credit: Money = Decimal("0")
    contact_id: str | None = None


class AllocationIn(Input):
    document_id: str
    amount: Annotated[Decimal, Field(gt=0, le=99999999999, decimal_places=2)]


class DocumentIn(Input):
    kind: Kind
    date: date
    due_date: date | None = None
    contact_id: str | None = None
    warehouse_id: str | None = None
    destination_id: str | None = None
    reference_id: str | None = None
    tax_invoice: bool = False
    cash_sale: bool = False
    lines: list[Item] = Field(default_factory=list, max_length=200)
    entries: list[Entry] = Field(default_factory=list, max_length=200)
    allocations: list[AllocationIn] = Field(default_factory=list, max_length=200)
    amount: Money = Decimal("0")
    account: Literal["1000", "1010"] = "1000"
    expense_account: Literal["6000", "6100", "6200"] = "6000"
    adjustment: Literal["increase", "decrease"] = "increase"
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def unique_products(self):
        if len({x.product_id for x in self.lines}) != len(self.lines):
            raise ValueError("Use one line per product")
        if self.due_date and self.due_date < self.date:
            raise ValueError("Due date cannot precede the transaction date")
        return self


class DocumentOut(BaseModel):
    id: str
    kind: Kind
    date: str
    due_date: str | None
    contact_id: str | None
    contact_name: str | None
    warehouse_id: str | None
    reference_id: str | None
    number: str | None
    status: str
    total: str
    outstanding: str
    payload: dict
    version: int
    created_at: str
    posted_at: str | None


class CompanyIn(Input):
    name: str = Field(min_length=2, max_length=180)
    pan: str = Field(default="", pattern=r"^(\d{9})?$")
    address: str = Field(default="", max_length=300)
    vat_registered: bool = False


class ImportIn(Input):
    kind: Literal["products", "contacts", "opening_stock", "opening_balances"]
    csv: str = Field(max_length=2_000_000)


class BankImport(Input):
    csv: str = Field(max_length=2_000_000)
    account: Literal["1010"] = "1010"


class MatchIn(Input):
    document_id: str


class AskIn(Input):
    question: str = Field(min_length=3, max_length=500)
    language: Literal["en", "ne"] = "en"


class LockIn(Input):
    through: date


class AllocateIn(Input):
    allocations: list[AllocationIn] = Field(min_length=1, max_length=100)
