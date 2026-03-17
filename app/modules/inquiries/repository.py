# app/modules/inquiries/repository.py
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from app.modules.inquiries.models import GeneralInquiry, DemoInquiry, InquiryStatus


# -----------------------
# General Inquiry Repos
# -----------------------

async def create_general_inquiry(session: AsyncSession, inquiry: GeneralInquiry) -> GeneralInquiry:
    session.add(inquiry)
    await session.commit()
    await session.refresh(inquiry)
    return inquiry


async def get_general_inquiry(session: AsyncSession, public_id: str) -> Optional[GeneralInquiry]:
    result = await session.execute(
        select(GeneralInquiry).where(GeneralInquiry.public_id == public_id)
    )
    return result.scalar_one_or_none()


async def list_general_inquiries(session: AsyncSession, skip: int = 0, limit: int = 100) -> List[GeneralInquiry]:
    result = await session.execute(
        select(GeneralInquiry).offset(skip).limit(limit)
    )
    return result.scalars().all()


async def update_general_inquiry_status(session: AsyncSession, public_id: str, status: InquiryStatus) -> Optional[GeneralInquiry]:
    await session.execute(
        update(GeneralInquiry)
        .where(GeneralInquiry.public_id == public_id)
        .values(status=status)
    )
    await session.commit()
    return await get_general_inquiry(session, public_id)


# -----------------------
# Demo Inquiry Repos
# -----------------------

async def create_demo_inquiry(session: AsyncSession, inquiry: DemoInquiry) -> DemoInquiry:
    session.add(inquiry)
    await session.commit()
    await session.refresh(inquiry)
    return inquiry


async def get_demo_inquiry(session: AsyncSession, public_id: str) -> Optional[DemoInquiry]:
    result = await session.execute(
        select(DemoInquiry).where(DemoInquiry.public_id == public_id)
    )
    return result.scalar_one_or_none()


async def list_demo_inquiries(session: AsyncSession, skip: int = 0, limit: int = 100) -> List[DemoInquiry]:
    result = await session.execute(
        select(DemoInquiry).offset(skip).limit(limit)
    )
    return result.scalars().all()


async def update_demo_inquiry_status(session: AsyncSession, public_id: str, status: InquiryStatus) -> Optional[DemoInquiry]:
    await session.execute(
        update(DemoInquiry)
        .where(DemoInquiry.public_id == public_id)
        .values(status=status)
    )
    await session.commit()
    return await get_demo_inquiry(session, public_id)