from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, Text, DateTime, func, select, update
from config import config
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
        # Warning: create_all does NOT update existing tables. 
        # For development we will drop all because user gave permission to "recreate".
        # await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

# --- DB Helpers ---

async def add_or_update_user(user_id: int, username: str, full_name: str):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(id=user_id, username=username, full_name=full_name, access_level='pending')
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
        await session.execute(
            update(User).where(User.id == user_id).values(access_level=new_level)
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
        # User ID, Name, Access, Gens Count, Tokens Sum
        stmt = (
            select(
                User.id,
                User.full_name,
                User.access_level,
                func.count(Generation.id).label("gens_count"),
                func.sum(Generation.tokens_used).label("total_tokens")
            )
            .outerjoin(Generation, User.id == Generation.user_id)
            .group_by(User.id)
            .order_by(func.count(Generation.id).desc())
        )
        result = await session.execute(stmt)
        return result.all()
