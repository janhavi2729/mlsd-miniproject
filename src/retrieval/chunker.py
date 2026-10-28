"""Corpus parser and clause-boundary chunker (Requirement L1, D2)."""

import os
import re
from typing import Any, Dict, List


class DocumentChunk:
    def __init__(
        self,
        chunk_id: str,
        document_name: str,
        clause_id: str,
        regulator: str,
        title: str,
        text: str,
        chunk_index: int,
    ):
        self.chunk_id = chunk_id
        self.document_name = document_name
        self.clause_id = clause_id
        self.regulator = regulator
        self.title = title
        self.text = text
        self.chunk_index = chunk_index

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_name": self.document_name,
            "clause_id": self.clause_id,
            "regulator": self.regulator,
            "title": self.title,
            "text": self.text,
            "chunk_index": self.chunk_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentChunk":
        return cls(
            chunk_id=data["chunk_id"],
            document_name=data["document_name"],
            clause_id=data["clause_id"],
            regulator=data["regulator"],
            title=data["title"],
            text=data["text"],
            chunk_index=data["chunk_index"],
        )


CLAUSE_PATTERN = re.compile(r"^CLAUSE\s+([A-Z0-9_\-]+):\s*(.+)$", re.MULTILINE)
REGULATOR_HEADER_PATTERN = re.compile(r"^\[REGULATOR:\s*([^\]]+)\]", re.MULTILINE)


def parse_and_chunk_document(doc_path: str, max_chunk_chars: int = 600) -> List[DocumentChunk]:
    """
    Parses a regulatory text file preserving clause boundaries.
    Ensures related provisions are not sliced apart mid-sentence.
    """
    filename = os.path.basename(doc_path)
    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Determine default regulator from header
    reg_match = REGULATOR_HEADER_PATTERN.search(content)
    default_regulator = reg_match.group(1).strip() if reg_match else "SEBI"

    # Split document by CLAUSE headers
    matches = list(CLAUSE_PATTERN.finditer(content))
    chunks: List[DocumentChunk] = []

    for i, match in enumerate(matches):
        clause_id = match.group(1).strip()
        title = match.group(2).strip()
        start_idx = match.start()
        end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        clause_body = content[start_idx:end_idx].strip()

        # If clause body is compact, keep as single chunk
        if len(clause_body) <= max_chunk_chars:
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{clause_id}_c0",
                    document_name=filename,
                    clause_id=clause_id,
                    regulator=default_regulator,
                    title=title,
                    text=clause_body,
                    chunk_index=0,
                )
            )
        else:
            # Paragraph-level sub-chunking with clause header preservation
            paragraphs = [p.strip() for p in clause_body.split("\n\n") if p.strip()]
            sub_idx = 0
            curr_text = f"CLAUSE {clause_id}: {title}\n"
            for p in paragraphs:
                if len(curr_text) + len(p) > max_chunk_chars and len(curr_text) > 50:
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{clause_id}_c{sub_idx}",
                            document_name=filename,
                            clause_id=clause_id,
                            regulator=default_regulator,
                            title=title,
                            text=curr_text.strip(),
                            chunk_index=sub_idx,
                        )
                    )
                    sub_idx += 1
                    curr_text = f"CLAUSE {clause_id} (cont.):\n{p}\n"
                else:
                    curr_text += f"{p}\n\n"

            if curr_text.strip():
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{clause_id}_c{sub_idx}",
                        document_name=filename,
                        clause_id=clause_id,
                        regulator=default_regulator,
                        title=title,
                        text=curr_text.strip(),
                        chunk_index=sub_idx,
                    )
                )

    return chunks
