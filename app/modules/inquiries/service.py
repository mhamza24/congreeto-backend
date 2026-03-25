# app/modules/inquiries/service.py
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.inquiries.models import GeneralInquiry, DemoInquiry, InquiryStatus, AffiliationInquiry
from app.modules.inquiries.schemas import GeneralInquiryCreateRequest, DemoInquiryCreateRequest, AffiliationInquiryCreateRequest
from app.modules.inquiries.repository import (
    create_general_inquiry,
    get_general_inquiry,
    list_general_inquiries,
    update_general_inquiry_status,
    create_demo_inquiry,
    get_demo_inquiry,
    list_demo_inquiries,
    update_demo_inquiry_status,
    _persist_affiliation_inquiry
)
from app.modules.email.service import send_contact_inquiry_email, send_demo_inquiry_email, send_affiliation_inquiry_email
# -----------------------
# General Inquiry
# -----------------------


async def create_general(session: AsyncSession, data: GeneralInquiryCreateRequest) -> GeneralInquiry:
    inquiry = GeneralInquiry(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        company_name=data.company_name,
        subject=data.subject,
        message=data.message,
        status=InquiryStatus.submitted,
    )
    await send_contact_inquiry_email(
        contact={
            "first_name":   data.first_name,
            "last_name":    data.last_name,
            "email":        data.email,
            "company_name": data.company_name,
            "subject":      data.subject,
            "message":      data.message,
        },
        recipients=["muhammadhamzakhalid248@gmail.com",
                    "contact@getveloce.com"],
    )
    return await create_general_inquiry(session, inquiry)
    

async def get_general(session: AsyncSession, public_id: str) -> GeneralInquiry:
    return await get_general_inquiry(session, public_id)


async def list_general(session: AsyncSession, skip: int = 0, limit: int = 100) -> List[GeneralInquiry]:
    return await list_general_inquiries(session, skip=skip, limit=limit)


async def update_general_status(session: AsyncSession, public_id: str, status: InquiryStatus) -> GeneralInquiry:
    return await update_general_inquiry_status(session, public_id, status)


# -----------------------
# Demo Inquiry
# -----------------------

async def create_demo(session: AsyncSession, data: DemoInquiryCreateRequest) -> DemoInquiry:
    inquiry = DemoInquiry(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        company_name=data.company_name,
        company_website=data.company_website,
        property_sectors=data.property_sectors,
        states=data.states,
        message=data.message,
        status=InquiryStatus.submitted,
    )
    await send_demo_inquiry_email(
        demo={
            "first_name":        data.first_name,
            "last_name":         data.last_name,
            "email":             data.email,
            "company_name":      data.company_name,
            "company_website":   data.company_website,
            "property_sectors":  data.property_sectors,   # list[str]
            "states":            data.states,             # list[str]
            "message":           data.message,
        },
        recipients=["muhammadhamzakhalid248@gmail.com",
                    "contact@getveloce.com"],
    )
    
    return await create_demo_inquiry(session, inquiry)


async def get_demo(session: AsyncSession, public_id: str) -> DemoInquiry:
    return await get_demo_inquiry(session, public_id)


async def list_demo(session: AsyncSession, skip: int = 0, limit: int = 100) -> List[DemoInquiry]:
    return await list_demo_inquiries(session, skip=skip, limit=limit)


async def update_demo_status(session: AsyncSession, public_id: str, status: InquiryStatus) -> DemoInquiry:
    return await update_demo_inquiry_status(session, public_id, status)


# -----------------------
# Affiliation Inquiry
# -----------------------

async def create_affiliation(
    session: AsyncSession,
    data: AffiliationInquiryCreateRequest,
    visitor_ip_hash: Optional[str] = None,
    visitor_ua: Optional[str] = None,
    page_url: Optional[str] = None,
) -> AffiliationInquiry:

    inquiry = AffiliationInquiry(
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        category=data.category,
        abn=data.abn,
        acn=data.acn,
        legal_entity_name=data.legal_entity_name,
        gst_applicable=data.gst_applicable,
        company_type=data.company_type,
        status=InquiryStatus.submitted,
        visitor_ip_hash=visitor_ip_hash,
        visitor_ua=visitor_ua,
        page_url=page_url,
    )

    await send_affiliation_inquiry_email(
        inquiry={
            "first_name":        data.first_name,
            "last_name":         data.last_name,
            "email":             data.email,
            "phone":             data.phone,
            "category":          data.category,
            "abn":               data.abn,
            "acn":               data.acn,
            "legal_entity_name": data.legal_entity_name,
            "gst_applicable":    data.gst_applicable,
            "company_type":      data.company_type,
        },
        recipients=[
            "muhammadhamzakhalid248@gmail.com",
            "contact@getveloce.com","taha.salman@getveloce.com"
        ],
        
        
    )

    return await _persist_affiliation_inquiry(session, inquiry)
