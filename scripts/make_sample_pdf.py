"""Generate a fake Acme University FAQ PDF for testing the RAG pipeline."""
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
)

OUT_DIR = Path("data/pdfs")
OUT_PATH = OUT_DIR / "acme_university_faq.pdf"

FAQ = [
    ("About Acme University", [
        "Acme University is a fictional private university located in Kigali, Rwanda. "
        "It was founded in 1998 and currently enrolls about 4,500 undergraduate students "
        "and 800 graduate students across five faculties: Engineering, Business, "
        "Health Sciences, Arts & Humanities, and Computing & Information Systems."
    ]),
    ("Admissions", [
        "Q: When does the admissions cycle open?",
        "A: Applications for the September intake open on 1 February and close on 30 April. "
        "Applications for the January intake open on 1 August and close on 31 October.",
        "Q: What documents do I need to apply?",
        "A: You need (1) a completed application form, (2) your high school transcript or "
        "equivalent, (3) a copy of your national ID or passport, (4) two reference letters, "
        "and (5) the non-refundable application fee of 25,000 RWF.",
        "Q: Is there an entrance exam?",
        "A: Engineering, Computing, and Health Sciences applicants must sit the Acme "
        "Aptitude Test. Other faculties accept applicants based on transcripts alone.",
    ]),
    ("Tuition and Fees", [
        "Q: How much is tuition?",
        "A: Undergraduate tuition for the 2026 academic year is 1,800,000 RWF per year "
        "for Rwandan citizens and 2,400,000 RWF per year for international students. "
        "Graduate tuition varies by program; please contact the Finance Office.",
        "Q: Are there scholarships?",
        "A: Yes. Acme offers merit scholarships covering 25%, 50%, or 100% of tuition, "
        "based on entrance exam scores and high school GPA. The deadline to apply for "
        "scholarships is 15 May for the September intake.",
        "Q: How do I pay tuition?",
        "A: Tuition can be paid in two installments — half before the start of each "
        "semester. We accept bank transfer, MTN Mobile Money (code *182*8*1*345678#), "
        "and cash payments at the Finance Office on the ground floor of the Main Building.",
    ]),
    ("Campus and Facilities", [
        "Q: What are the library opening hours?",
        "A: The main library is open Monday to Friday from 7:30 AM to 10:00 PM, and "
        "Saturday from 9:00 AM to 6:00 PM. The library is closed on Sundays and public holidays.",
        "Q: Is there on-campus accommodation?",
        "A: Yes. Acme has three residence halls — Kigeri, Mutara, and Cyahafi — with "
        "a combined capacity of 1,200 students. Accommodation costs 600,000 RWF per "
        "academic year and includes utilities. Rooms are allocated on a first-come basis.",
        "Q: How do I get to campus?",
        "A: The campus is on KG 7 Avenue, in the Nyarugenge district. The closest bus "
        "stop is Nyabugogo, served by routes 302, 304, and 318. There is also free "
        "parking for students with a registered vehicle.",
    ]),
    ("Registration and Academics", [
        "Q: When is the add/drop deadline?",
        "A: The add/drop period runs for the first two weeks of each semester. After "
        "that, dropped courses appear on your transcript with a 'W' grade.",
        "Q: How do I request a transcript?",
        "A: Submit a transcript request through the student portal at portal.acme.ac.rw. "
        "Official transcripts cost 5,000 RWF and are usually ready within three business days.",
        "Q: What is the minimum GPA to stay enrolled?",
        "A: Undergraduate students must maintain a CGPA of at least 2.0 on a 4.0 scale. "
        "Falling below 2.0 for two consecutive semesters leads to academic probation.",
    ]),
    ("Contact and Support", [
        "Q: How do I contact the registrar?",
        "A: The Registrar's Office is on the second floor of the Main Building. "
        "Phone: +250 788 123 456. Email: registrar@acme.ac.rw. "
        "Office hours: Monday–Friday, 8:00 AM to 5:00 PM.",
        "Q: Who do I contact for IT issues?",
        "A: For student-portal logins, Wi-Fi access, or email problems, contact "
        "the IT Help Desk at helpdesk@acme.ac.rw or call +250 788 123 999.",
        "Q: Where do I report harassment or misconduct?",
        "A: Contact the Office of Student Affairs in confidence at "
        "studentaffairs@acme.ac.rw or visit room 204 of the Main Building.",
    ]),
]


def build():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT_PATH),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Title"], spaceAfter=14
    )
    heading_style = ParagraphStyle(
        "H", parent=styles["Heading2"], spaceBefore=12, spaceAfter=6
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"], spaceAfter=6, leading=14
    )

    flow = [Paragraph("Acme University — Frequently Asked Questions", title_style),
            Paragraph("2026 Edition", styles["Italic"]),
            Spacer(1, 12)]
    for section, items in FAQ:
        flow.append(Paragraph(section, heading_style))
        for item in items:
            flow.append(Paragraph(item, body_style))
        flow.append(Spacer(1, 6))
    doc.build(flow)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
