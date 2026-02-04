from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=5,          # safe default for small VPS
    max_overflow=10,      # allows burst webhook traffic
    pool_pre_ping=True,   # avoids stale connections
    pool_recycle=300,     # refresh connections every 5 mins
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
