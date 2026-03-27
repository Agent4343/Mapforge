"""SQLAlchemy database models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    tier = Column(String(20), default="free")  # free, maker, pro
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    stripe_connect_account_id = Column(String(255), nullable=True)
    stripe_payouts_enabled = Column(Boolean, default=False)
    etsy_access_token = Column(Text, nullable=True)
    etsy_refresh_token = Column(Text, nullable=True)
    etsy_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    etsy_shop_id = Column(String(255), nullable=True)
    etsy_shop_name = Column(String(255), nullable=True)
    generation_count_this_month = Column(Integer, default=0)
    month_reset_date = Column(DateTime(timezone=True), default=_utcnow)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    files = relationship("GeneratedFile", back_populates="owner")
    listings = relationship("MarketplaceListing", back_populates="seller")
    purchases = relationship("Purchase", back_populates="buyer")


class GeneratedFile(Base):
    __tablename__ = "generated_files"

    id = Column(String(16), primary_key=True, default=_uuid)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    osm_id = Column(Integer, nullable=False, index=True)
    osm_type = Column(String(20), nullable=False)
    product_type = Column(String(20), nullable=False, index=True)
    location_name = Column(String(255), nullable=False)
    display_text = Column(String(255), nullable=False)
    board_size = Column(String(20), nullable=False)
    board_width_mm = Column(Float, nullable=False)
    board_height_mm = Column(Float, nullable=False)
    style = Column(String(20), nullable=False)
    show_coordinates = Column(Boolean, default=True)
    font_size_mm = Column(Float, default=14.0)
    node_count = Column(Integer, default=0)
    path_count = Column(Integer, default=0)
    layer_count = Column(Integer, default=0)
    svg_storage_key = Column(String(512), nullable=False)
    dxf_storage_key = Column(String(512), nullable=True)
    thumbnail_key = Column(String(512), nullable=True)
    print_png_key = Column(String(512), nullable=True)
    province = Column(String(100), nullable=True, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    owner = relationship("User", back_populates="files")
    listing = relationship("MarketplaceListing", back_populates="file", uselist=False)


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"

    id = Column(String(16), primary_key=True, default=_uuid)
    file_id = Column(String(16), ForeignKey("generated_files.id"), unique=True, nullable=False)
    seller_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    price_cents = Column(Integer, nullable=False)  # in cents
    currency = Column(String(3), default="USD")
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)  # comma-separated
    is_active = Column(Boolean, default=True)
    view_count = Column(Integer, default=0)
    sale_count = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)
    rating_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    file = relationship("GeneratedFile", back_populates="listing")
    seller = relationship("User", back_populates="listings")
    purchases = relationship("Purchase", back_populates="listing")
    reviews = relationship("Review", back_populates="listing")


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(String(16), primary_key=True, default=_uuid)
    listing_id = Column(String(16), ForeignKey("marketplace_listings.id"), nullable=False, index=True)
    buyer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    price_cents = Column(Integer, nullable=False)
    platform_fee_cents = Column(Integer, nullable=False)
    seller_payout_cents = Column(Integer, nullable=False)
    stripe_payment_intent_id = Column(String(255), nullable=True)
    status = Column(String(20), default="completed")  # pending, completed, refunded
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("listing_id", "buyer_id", name="uq_purchase_listing_buyer"),
    )

    listing = relationship("MarketplaceListing", back_populates="purchases")
    buyer = relationship("User", back_populates="purchases")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(String(16), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class DesignCredit(Base):
    """A design credit purchased via Etsy.

    When a customer buys on Etsy, a credit is created with a unique token.
    The customer uses the token to access the design tool and download their files.

    Flow: Etsy purchase → webhook creates credit → customer redeems token →
          designs map → generates files → downloads (no second payment).
    """
    __tablename__ = "design_credits"

    id = Column(String(16), primary_key=True, default=_uuid)
    # Etsy order info
    etsy_receipt_id = Column(String(100), nullable=True, index=True)
    etsy_shop_id = Column(String(100), nullable=True)
    etsy_buyer_email = Column(String(255), nullable=True)
    seller_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    # Product purchased on Etsy
    product_type = Column(String(20), nullable=True)  # lake, city, province, etc.
    product_tier = Column(String(20), default="standard")  # standard, premium, deluxe
    etsy_listing_title = Column(String(500), nullable=True)
    price_cents = Column(Integer, nullable=True)
    # Redemption
    redeem_token = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(20), default="unused")  # unused, designing, generating, completed, expired
    # Design configuration (saved when customer finishes designing)
    design_config = Column(Text, nullable=True)
    location_name = Column(String(255), nullable=True)
    # Generated file
    file_id = Column(String(16), ForeignKey("generated_files.id"), nullable=True)
    # Download tracking
    download_count = Column(Integer, default=0)
    max_downloads = Column(Integer, default=5)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    file = relationship("GeneratedFile", foreign_keys=[file_id])
    seller = relationship("User", foreign_keys=[seller_id])


class AppSettings(Base):
    """Key-value store for application settings (Etsy API keys, etc.).

    Stored in the database so admin can configure via UI without redeploying.
    Falls back to environment variables if not set in DB.
    """
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id = Column(String(16), primary_key=True, default=_uuid)
    listing_id = Column(String(16), ForeignKey("marketplace_listings.id"), nullable=False, index=True)
    buyer_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    cnc_compatible = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("listing_id", "buyer_id", name="uq_review_listing_buyer"),
    )

    listing = relationship("MarketplaceListing", back_populates="reviews")
