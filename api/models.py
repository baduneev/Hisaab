from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, CheckConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(180))
    pan: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    vat_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_stock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sequences: Mapped[dict] = mapped_column(JSON, default=dict)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="Owner")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    branch: Mapped[str] = mapped_column(String(120), default="Main branch")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(12))
    pan: Mapped[str] = mapped_column(String(20), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    credit_days: Mapped[int] = mapped_column(Integer, default=30)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    sku: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(80), default="General")
    unit: Mapped[str] = mapped_column(String(30), default="piece")
    pack_unit: Mapped[str] = mapped_column(String(30), default="pack")
    pack_size: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=1)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)
    warehouse_id: Mapped[str | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    number: Mapped[str | None] = mapped_column(String(70), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="draft")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    total: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Stock(Base):
    __tablename__ = "stock"
    __table_args__ = (UniqueConstraint("tenant_id", "product_id", "warehouse_id"), CheckConstraint("quantity >= 0"), CheckConstraint("value >= 0"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"))
    date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    value: Mapped[Decimal] = mapped_column(Numeric(20, 2))


class Journal(Base):
    __tablename__ = "journals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), unique=True)
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(300))


class LedgerLine(Base):
    __tablename__ = "ledger_lines"
    __table_args__ = (CheckConstraint("debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0)"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    journal_id: Mapped[str] = mapped_column(ForeignKey("journals.id"))
    account: Mapped[str] = mapped_column(String(10), index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"), nullable=True)


class Allocation(Base):
    __tablename__ = "allocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    allocated_on: Mapped[date] = mapped_column(Date)


class Idempotency(Base):
    __tablename__ = "idempotency"
    __table_args__ = (UniqueConstraint("tenant_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(160))
    result_id: Mapped[str] = mapped_column(String(36))


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(80))
    record_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    rows: Mapped[list] = mapped_column(JSON)
    errors: Mapped[list] = mapped_column(JSON)
    committed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BankRow(Base):
    __tablename__ = "bank_rows"
    __table_args__ = (UniqueConstraint("tenant_id", "fingerprint"), UniqueConstraint("tenant_id", "document_id"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    account: Mapped[str] = mapped_column(String(10))
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    fingerprint: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("tenant_id", "date"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    requests: Mapped[int] = mapped_column(Integer, default=0)


def database(url):
    engine = create_engine(url, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}))
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)
