import argparse
import sys
from pathlib import Path

from pypdf import PdfReader

from src.rag.store import embed, get_collection


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def chunk_text(text: str, target_size: int = 400, max_size: int = 800) -> list[str]:
    """Pack non-empty lines into chunks of ~target_size chars, capped at max_size.

    Keeps line-level units intact so Q/A pairs and section headings don't get
    split mid-sentence by a fixed-width window.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for ln in lines:
        if current and current_len + len(ln) + 1 > max_size:
            chunks.append("\n".join(current))
            current, current_len = [ln], len(ln)
            continue
        current.append(ln)
        current_len += len(ln) + 1
        if current_len >= target_size:
            chunks.append("\n".join(current))
            current, current_len = [], 0
    if current:
        chunks.append("\n".join(current))
    return chunks


def ingest_pdf(pdf_path: Path) -> int:
    print(f"Reading {pdf_path.name}...")
    text = extract_text(pdf_path)
    if not text.strip():
        print(
            "No text extracted. This might be a scanned/image-only PDF — "
            "those need OCR, which isn't wired up yet."
        )
        return 0

    chunks = chunk_text(text)
    print(f"Split into {len(chunks)} chunks. Computing embeddings...")

    embeddings = embed(chunks)

    source = pdf_path.name
    ids = [f"{source}__{i}" for i in range(len(chunks))]
    metadatas = [{"source": source, "chunk": i} for i in range(len(chunks))]

    collection = get_collection()
    collection.delete(where={"source": source})
    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    print(f"Ingested {len(chunks)} chunks from '{source}'.")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a PDF into the FAQ vector store."
    )
    parser.add_argument("pdf_path", type=Path, help="Path to a PDF file")
    args = parser.parse_args()

    if not args.pdf_path.exists():
        print(f"File not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)
    if args.pdf_path.suffix.lower() != ".pdf":
        print(f"Not a .pdf file: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    ingest_pdf(args.pdf_path)


if __name__ == "__main__":
    main()
