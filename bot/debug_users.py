import asyncio
from database import async_session, Generation, get_all_users_stats
from sqlalchemy import select, update

async def debug_run():
    async with async_session() as session:
        # 1. Fix pending
        print("Fixing pending statuses...")
        await session.execute(
            update(Generation)
            .where(Generation.status == 'pending')
            .values(status='completed')
        )
        await session.commit()
        print("Fixed pending.")

        # 2. Test Users Stats
        print("Testing get_all_users_stats...")
        try:
            stats = await get_all_users_stats()
            print(f"Got {len(stats)} users.")
            for s in stats:
                print(f"User: {s.id}, Name: {s.full_name}, Lvl: {s.access_level}, Gens: {s.gens_count}, Tok: {s.total_tokens}")
        except Exception as e:
            print(f"Error getting stats: {e}")

if __name__ == "__main__":
    asyncio.run(debug_run())
