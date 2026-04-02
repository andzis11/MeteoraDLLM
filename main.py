#!/usr/bin/env python3
"""
Meridian-Enhanced LP Bot - Main Entry Point
"""

import asyncio
import logging
from dotenv import load_dotenv
from config import BotConfig
from scheduler import BotScheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("🚀 Meridian LP Bot starting...")
    config = BotConfig.load()
    scheduler = BotScheduler(config)
    await scheduler.run()


if __name__ == "__main__":
    asyncio.run(main())
