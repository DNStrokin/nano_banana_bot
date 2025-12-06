from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, Text, DateTime, func, select, update
from config import config
from pricing import START_BONUS
import logging

DATABASE_URL = f"postgresql+asyncpg://{config.POSTGRES_USER}:{config.POSTGRES_PASSWORD}@{config.POSTGRES_HOST}/{config.POSTGRES_DB}"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(AsyncAttrs, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram User ID
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str] = mapped_column(Text)
    access_level: Mapped[str] = mapped_column(Text, default='pending') # pending, demo, basic, full, banned, admin
    
    # New Fields for Subscription System
    balance: Mapped[int] = mapped_column(BigInteger, default=START_BONUS) # Default Demo bonus
    tariff: Mapped[str] = mapped_column(Text, default='demo') # demo, basic, full
    tariff_expires_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

class Generation(Base):
    __tablename__ = 'generations'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    model: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    aspect_ratio: Mapped[str] = mapped_column(Text, default="1:1")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default='completed') # completed, failed, pending
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

async def init_db():
    async with engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)
        
        # Simple Migration: Check for new columns and add them if missing
        # This is valid for Postgres
        from sqlalchemy import text
        
        try:
            # Check for balance
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance BIGINT DEFAULT 500"))
            # Check for tariff
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tariff TEXT DEFAULT 'demo'"))
            # Check for tariff_expires_at
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tariff_expires_at TIMESTAMP"))
        except Exception as e:
            logging.error(f"Migration error (ignored if columns exist): {e}")

# --- DB Helpers ---

async def add_or_update_user(user_id: int, username: str, full_name: str):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            # New users get Demo tariff + start bonus NC
            user = User(
                id=user_id, 
                username=username, 
                full_name=full_name, 
                access_level='demo', # No more pending
                tariff='demo',
                balance=START_BONUS
            )
            session.add(user)
            await session.commit()
            return user, True # Created
        else:
            # Update info if changed
            if user.username != username or user.full_name != full_name:
                user.username = username
                user.full_name = full_name
                await session.commit()
            return user, False # Existing

async def get_user(user_id: int):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

async def update_user_access(user_id: int, new_level: str):
    async with async_session() as session:
        # Sync access_level and tariff. 
        # When manually setting access, we assume "Unlimited" duration (?)
        # Or should we respect existing duration? 
        # Usually /set_access is an override. Let's make it Unlimited.
        await session.execute(
            update(User).where(User.id == user_id).values(
                access_level=new_level,
                tariff=new_level,
                tariff_expires_at=None
            )
        )
        await session.commit()

# --- Subscription & Balance Helpers ---

async def get_user_balance(user_id: int) -> int:
    async with async_session() as session:
        result = await session.scalar(select(User.balance).where(User.id == user_id))
        return result if result is not None else 0

async def update_balance(user_id: int, delta: int) -> int:
    """Updates balance (positive to add, negative to spend). Returns new balance."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            user.balance += delta
            await session.commit()
            return user.balance
        return 0

async def set_user_tariff(user_id: int, tariff: str, days: int | None = 30):
    async with async_session() as session:
        if days is None:
            expires_at = None
        else:
            from datetime import datetime, timedelta
            expires_at = datetime.now() + timedelta(days=days)
        
        await session.execute(
            update(User).where(User.id == user_id).values(
                tariff=tariff,
                tariff_expires_at=expires_at
            )
        )
        await session.commit()

async def log_generation(user_id: int, model: str, prompt: str, ar: str, res: str, status: str = 'completed'):
    async with async_session() as session:
        gen = Generation(
            user_id=user_id, 
            model=model, 
            prompt=prompt, 
            aspect_ratio=ar, 
            resolution=res, 
            status=status
        )
        session.add(gen)
        await session.commit()
        return gen.id

async def update_generation_status(gen_id: int, status: str, tokens: int = 0):
    async with async_session() as session:
        gen = await session.get(Generation, gen_id)
        if gen:
            gen.status = status
            gen.tokens_used = tokens
            await session.commit()

async def get_stats():
    async with async_session() as session:
        users_count = await session.scalar(select(func.count(User.id)))
        gens_count = await session.scalar(select(func.count(Generation.id)))
        # Recent gens
        result = await session.execute(select(Generation).order_by(Generation.created_at.desc()).limit(5))
        recent_gens = result.scalars().all()
        return users_count, gens_count, recent_gens

async def get_all_users_stats():
    async with async_session() as session:
        # User ID, Name, Access, Tariff, Balance, Gens Count
        stmt = (
            select(
                User.id,
                User.full_name,
                User.access_level,
                User.tariff,
                User.balance,
                func.count(Generation.id).label("gens_count"),
                func.sum(Generation.tokens_used).label("total_tokens")
            )
            .outerjoin(Generation, User.id == Generation.user_id)
            .group_by(User.id)
            .order_by(func.count(Generation.id).desc())
        )
        result = await session.execute(stmt)
        return result.all()
