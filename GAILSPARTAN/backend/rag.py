"""A deterministic, local retrieval-augmented document service.

The service deliberately has no network or model dependency. PDF text is
extracted with pdfminer, normalized into overlapping chunks, and ranked with
an in-process TF-IDF cosine-style scorer. Answers are assembled by selecting
sentences from the ranked chunks, so every returned answer can be traced to an
indexed source.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from io import BytesIO, StringIO
import hashlib
import math
import re
import time
import unicodedata
from typing import Any, BinaryIO, Iterable, Sequence

from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage

try:
    from .extensions import db
    from .models import Document, DocumentChunk
except ImportError:  # pragma: no cover - direct script execution support.
    from extensions import db
    from models import Document, DocumentChunk


DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_TOP_K = 5
MIN_RELEVANCE_SCORE = 0.08
UNSUPPORTED_ANSWER = (
    "I couldn't find enough support in your indexed documents to answer "
    "that question."
)
CONFLICTING_ANSWER = (
    "The indexed documents contain conflicting information. Please confirm "
    "which source is current before relying on this answer."
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)?")
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
_NUMERIC_TIME_PATTERN = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>years?|yrs?|months?|mos?|weeks?|wks?|days?|hrs?|hours?|"
    r"minutes?|mins?|seconds?|secs?)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}
_WORD_TIME_PATTERN = re.compile(
    r"\b(?P<value>(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
    r"(?:[ -](?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)){0,2})\s+"
    r"(?P<unit>years?|yrs?|months?|mos?|weeks?|wks?|days?|hrs?|hours?|"
    r"minutes?|mins?|seconds?|secs?)\b",
    re.IGNORECASE,
)
_TIME_UNIT_SECONDS = {
    "year": 365 * 24 * 60 * 60,
    "yr": 365 * 24 * 60 * 60,
    "month": 30 * 24 * 60 * 60,
    "mo": 30 * 24 * 60 * 60,
    "week": 7 * 24 * 60 * 60,
    "wk": 7 * 24 * 60 * 60,
    "day": 24 * 60 * 60,
    "hour": 60 * 60,
    "hr": 60 * 60,
    "minute": 60,
    "min": 60,
    "second": 1,
    "sec": 1,
}

# Removing conversational stop words makes short questions such as "What does
# the policy say about retention?" focus on document terms instead of grammar.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "about",
        "be",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "of",
        "on",
        "or",
        "say",
        "should",
        "tell",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "you",
        "your",
    }
)


@dataclass(frozen=True)
class ExtractedPage:
    """Normalized text for one source PDF page."""

    page_number: int
    text: str


@dataclass(frozen=True)
class RAGAnswer:
    """An extractive answer and the chunks that support it."""

    response: str
    sources: list[dict[str, Any]]
    grounding_status: str = "insufficient_evidence"
    needs_escalation: bool = True
    latency_ms: int = 0
    citations: list[dict[str, Any]] = field(default_factory=list)


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace while retaining readable punctuation."""

    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _pdf_stream(pdf_file: Any) -> BinaryIO:
    """Return a seekable binary stream for Flask uploads and byte payloads."""

    if isinstance(pdf_file, (bytes, bytearray, memoryview)):
        return BytesIO(bytes(pdf_file))

    stream = getattr(pdf_file, "stream", pdf_file)
    if not hasattr(stream, "read"):
        raise ValueError("The uploaded PDF is not a readable file.")
    try:
        stream.seek(0)
    except (AttributeError, OSError):
        pass
    return stream


def _read_binary_payload(file_value: Any, max_size: int | None = None) -> bytes:
    """Read an upload once, optionally enforcing a byte limit."""

    if isinstance(file_value, (bytes, bytearray, memoryview)):
        payload = bytes(file_value)
    else:
        stream = getattr(file_value, "stream", file_value)
        if not hasattr(stream, "read"):
            raise ValueError("The uploaded file is not readable.")
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            pass
        read_size = max_size + 1 if max_size is not None and max_size >= 0 else -1
        payload = stream.read(read_size)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        try:
            payload = bytes(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("The uploaded file is not readable.") from exc

    if max_size is not None and len(payload) > max_size:
        raise ValueError(f"The uploaded file exceeds the {max_size}-byte limit.")
    if not payload:
        raise ValueError("The uploaded file is empty.")
    return payload


def extract_pdf_pages(pdf_file: Any) -> list[ExtractedPage]:
    """Extract normalized text from a PDF, retaining one-based page numbers."""

    stream = _pdf_stream(pdf_file)
    pages: list[ExtractedPage] = []

    for page_number, page in enumerate(PDFPage.get_pages(stream), start=1):
        resource_manager = PDFResourceManager()
        output = StringIO()
        converter = TextConverter(resource_manager, output, laparams=LAParams())
        interpreter = PDFPageInterpreter(resource_manager, converter)
        try:
            interpreter.process_page(page)
            page_text = normalize_text(output.getvalue())
        finally:
            converter.close()
            output.close()

        if page_text:
            pages.append(ExtractedPage(page_number=page_number, text=page_text))

    return pages


def extract_txt_pages(txt_file: Any) -> list[ExtractedPage]:
    """Extract one normalized page from a UTF-8 text file.

    UTF-8 decoding is deliberately strict and NUL bytes are rejected so a
    binary payload renamed to ``.txt`` cannot silently enter the index.
    """

    payload = _read_binary_payload(txt_file)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The uploaded TXT file is not valid UTF-8 text.") from exc
    if "\x00" in text:
        raise ValueError("The uploaded TXT file contains binary data.")
    normalized = normalize_text(text)
    return [ExtractedPage(page_number=1, text=normalized)] if normalized else []


def extract_text_from_pdf(pdf_file: Any) -> str:
    """Compatibility helper returning all extracted PDF text as one string."""

    return "\n\n".join(page.text for page in extract_pdf_pages(pdf_file))


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split normalized text into word-boundary chunks with character overlap."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    normalized = normalize_text(text)
    if not normalized:
        return []

    words = normalized.split(" ")
    chunks: list[str] = []
    start = 0

    while start < len(words):
        end = start
        length = 0
        while end < len(words):
            word_length = len(words[end])
            added_length = word_length if end == start else word_length + 1
            if end > start and length + added_length > chunk_size:
                break
            length += added_length
            end += 1

        # A single word longer than the requested size still belongs in one
        # chunk; dropping it would make the source impossible to retrieve.
        if end == start:
            end += 1

        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break

        if overlap == 0:
            next_start = end
        else:
            overlap_start = end
            while overlap_start > start:
                candidate = " ".join(words[overlap_start - 1 : end])
                if len(candidate) > overlap:
                    break
                overlap_start -= 1

            # Ensure progress even when the final word itself exceeds the
            # overlap budget.
            next_start = overlap_start if overlap_start < end else end - 1
            if next_start <= start:
                next_start = end

        start = next_start

    return chunks


def tokenize(text: str) -> list[str]:
    """Tokenize text deterministically for local ranking."""

    tokens = []
    for match in _TOKEN_PATTERN.finditer((text or "").lower()):
        token = match.group(0)
        if token not in _STOP_WORDS and len(token) > 1:
            tokens.append(token)
    return tokens


def _tfidf_vector(
    tokens: Sequence[str],
    document_frequency: Counter[str],
    total_documents: int,
) -> dict[str, float]:
    counts = Counter(tokens)
    token_count = len(tokens) or 1
    vector: dict[str, float] = {}
    for token, count in counts.items():
        document_frequency_value = document_frequency[token]
        inverse_document_frequency = math.log(
            (1 + total_documents) / (1 + document_frequency_value)
        ) + 1.0
        term_frequency = (1.0 + math.log(count)) / token_count
        vector[token] = term_frequency * inverse_document_frequency
    return vector


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot_product = sum(value * right.get(token, 0.0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot_product / (left_norm * right_norm)


def _chunk_text_value(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        return str(chunk.get("text", ""))
    return str(getattr(chunk, "text", ""))


def rank_chunks(
    query: str,
    chunks: Sequence[Any],
    top_k: int = DEFAULT_TOP_K,
) -> list[tuple[Any, float]]:
    """Rank chunks with TF-IDF cosine similarity and deterministic keyword bonuses."""

    if top_k <= 0:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    chunk_tokens = [tokenize(_chunk_text_value(chunk)) for chunk in chunks]
    document_frequency: Counter[str] = Counter()
    for tokens in chunk_tokens:
        document_frequency.update(set(tokens))

    query_vector = _tfidf_vector(
        query_tokens,
        document_frequency,
        max(len(chunk_tokens), 1),
    )
    query_terms = set(query_tokens)
    normalized_query = " ".join(query_tokens)
    scored: list[tuple[Any, float, int]] = []

    for index, (chunk, tokens) in enumerate(zip(chunks, chunk_tokens)):
        document_vector = _tfidf_vector(
            tokens,
            document_frequency,
            max(len(chunk_tokens), 1),
        )
        score = _cosine_similarity(query_vector, document_vector)
        matching_terms = query_terms.intersection(tokens)
        if matching_terms:
            # This small keyword component helps short, exact questions rank
            # well without introducing any non-deterministic model behavior.
            score += 0.05 * len(matching_terms) / len(query_terms)
        normalized_chunk = " ".join(tokens)
        if normalized_query and normalized_query in normalized_chunk:
            score += 0.05
        if score > 0.0:
            scored.append((chunk, score, index))

    scored.sort(key=lambda item: (-item[1], item[2]))
    return [(chunk, score) for chunk, score, _ in scored[:top_k]]


def _split_sentences(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    return [
        sentence.strip()
        for sentence in _SENTENCE_PATTERN.split(normalized)
        if sentence.strip()
    ]


def summarize_text(text: str, max_sentences: int = 3, max_chars: int = 700) -> str:
    """Create a bounded, deterministic extractive document summary."""

    normalized = normalize_text(text)
    if not normalized:
        return ""
    sentences = _split_sentences(normalized)
    summary = " ".join(sentences[: max(max_sentences, 1)]) if sentences else normalized
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return summary


def extract_keywords(text: str, max_keywords: int = 10) -> list[str]:
    """Return stable keywords ordered by frequency and first appearance."""

    tokens = tokenize(text)
    if not tokens or max_keywords <= 0:
        return []
    counts = Counter(tokens)
    first_seen: dict[str, int] = {}
    for index, token in enumerate(tokens):
        first_seen.setdefault(token, index)
    ranked = sorted(
        counts,
        key=lambda token: (-counts[token], first_seen[token], token),
    )
    return ranked[:max_keywords]


def _number_word_value(value_text: str) -> float | None:
    """Parse the small number-word vocabulary commonly found in policies."""

    words = [word for word in re.split(r"[ -]+", value_text.lower()) if word]
    if not words or any(word not in _NUMBER_WORDS for word in words):
        return None
    if len(words) == 1:
        return float(_NUMBER_WORDS[words[0]])
    if "hundred" in words:
        prefix = words[: words.index("hundred")]
        prefix_value = sum(_NUMBER_WORDS[word] for word in prefix) or 1
        suffix = words[words.index("hundred") + 1 :]
        return float(prefix_value * 100 + sum(_NUMBER_WORDS[word] for word in suffix))
    return float(sum(_NUMBER_WORDS[word] for word in words))


def _canonical_time_unit(unit: str) -> str:
    normalized = unit.lower().rstrip("s")
    if normalized == "yr":
        return "year"
    if normalized == "mo":
        return "month"
    if normalized == "wk":
        return "week"
    if normalized == "hr":
        return "hour"
    if normalized == "min":
        return "minute"
    if normalized == "sec":
        return "second"
    return normalized


def _numeric_time_claims(text: str) -> list[tuple[float, str, set[str]]]:
    """Extract comparable duration claims and the terms around each claim."""

    claims: list[tuple[float, str, set[str]]] = []
    for sentence in _split_sentences(text):
        sentence_tokens = set(tokenize(sentence))
        consumed: list[tuple[int, int]] = []
        for match in _NUMERIC_TIME_PATTERN.finditer(sentence):
            value = float(match.group("value"))
            unit = _canonical_time_unit(match.group("unit"))
            seconds = value * _TIME_UNIT_SECONDS.get(unit, 1)
            claims.append((seconds, unit, sentence_tokens))
            consumed.append(match.span())

        for match in _WORD_TIME_PATTERN.finditer(sentence):
            if any(
                start <= match.start() < end or start < match.end() <= end
                for start, end in consumed
            ):
                continue
            value = _number_word_value(match.group("value"))
            if value is None:
                continue
            unit = _canonical_time_unit(match.group("unit"))
            seconds = value * _TIME_UNIT_SECONDS.get(unit, 1)
            claims.append((seconds, unit, sentence_tokens))
    return claims


def _has_conflicting_evidence(
    query: str,
    matches: Sequence[tuple[Any, float]],
) -> bool:
    """Detect simple opposing numeric/time claims among highly ranked chunks."""

    if len(matches) < 2:
        return False
    query_terms = set(tokenize(query))
    if not query_terms:
        return False
    highest_score = matches[0][1]
    claims_by_chunk: list[list[tuple[float, str, set[str]]]] = []
    for chunk, score in matches[:5]:
        if score < max(MIN_RELEVANCE_SCORE, highest_score * 0.65):
            continue
        claims = _numeric_time_claims(_chunk_text_value(chunk))
        if claims:
            claims_by_chunk.append(claims)

    for index, left_claims in enumerate(claims_by_chunk):
        for right_claims in claims_by_chunk[index + 1 :]:
            for left_value, _, left_terms in left_claims:
                for right_value, _, right_terms in right_claims:
                    shared_terms = query_terms.intersection(left_terms).intersection(right_terms)
                    if not shared_terms:
                        continue
                    if not math.isclose(left_value, right_value, rel_tol=1e-9, abs_tol=1e-9):
                        return True
    return False


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _source_metadata(chunk: Any, score: float) -> dict[str, Any]:
    document = _value(chunk, "document")
    document_id = _value(document, "id")
    filename = _value(document, "filename") or _value(chunk, "filename") or "unknown"
    title = _value(document, "title")
    page_number = _value(chunk, "page_number")
    chunk_index = _value(chunk, "chunk_index")
    chunk_id = _value(chunk, "id")

    return {
        "chunk_id": chunk_id,
        "citation_id": f"{document_id}:{chunk_id}" if document_id is not None and chunk_id is not None else None,
        "document_id": document_id,
        "filename": filename,
        "title": title,
        "page": page_number,
        "page_number": page_number,
        "chunk": chunk_index,
        "chunk_index": chunk_index,
        "score": round(score, 6),
    }


def answer_from_matches(
    query: str,
    matches: Sequence[tuple[Any, float]],
    max_sentences: int = 3,
) -> RAGAnswer:
    """Build an extractive answer from ranked chunks and their metadata."""

    if not matches or max_sentences <= 0:
        return RAGAnswer(
            response=UNSUPPORTED_ANSWER,
            sources=[],
            grounding_status="insufficient_evidence",
            needs_escalation=True,
            citations=[],
        )

    query_terms = set(tokenize(query))
    candidates: list[tuple[float, int, int, str, Any, float]] = []

    for rank, (chunk, chunk_score) in enumerate(matches):
        if chunk_score < MIN_RELEVANCE_SCORE:
            continue
        text = _chunk_text_value(chunk)
        for sentence_index, sentence in enumerate(_split_sentences(text)):
            sentence_terms = set(tokenize(sentence))
            matching_terms = query_terms.intersection(sentence_terms)
            if not matching_terms:
                continue
            sentence_score = (
                len(matching_terms) / max(len(query_terms), 1)
                + 0.1 * len(matching_terms) / max(len(sentence_terms), 1)
                + chunk_score * 0.01
            )
            candidates.append(
                (sentence_score, rank, sentence_index, sentence, chunk, chunk_score)
            )

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected_sentences: list[str] = []
    selected_source_keys: set[tuple[Any, Any, Any]] = set()
    source_order: list[tuple[Any, Any, Any]] = []
    source_by_key: dict[tuple[Any, Any, Any], dict[str, Any]] = {}

    for _, _, _, sentence, chunk, chunk_score in candidates:
        sentence_key = normalize_text(sentence).casefold()
        if sentence_key in {item.casefold() for item in selected_sentences}:
            continue
        selected_sentences.append(sentence)
        metadata = _source_metadata(chunk, chunk_score)
        source_key = (
            metadata.get("document_id"),
            metadata.get("page_number"),
            metadata.get("chunk_index"),
        )
        if source_key not in selected_source_keys:
            selected_source_keys.add(source_key)
            source_order.append(source_key)
            source_by_key[source_key] = metadata
        if len(selected_sentences) >= max_sentences:
            break

    if not selected_sentences:
        return RAGAnswer(
            response=UNSUPPORTED_ANSWER,
            sources=[],
            grounding_status="insufficient_evidence",
            needs_escalation=True,
            citations=[],
        )

    sources = [source_by_key[key] for key in source_order]
    if _has_conflicting_evidence(query, matches):
        # Include the highly ranked, real source metadata even though the safe
        # response does not choose one policy version over another.
        conflict_sources: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any, Any]] = set()
        for chunk, chunk_score in matches[:5]:
            metadata = _source_metadata(chunk, chunk_score)
            key = (
                metadata.get("document_id"),
                metadata.get("page_number"),
                metadata.get("chunk_index"),
            )
            if key in seen:
                continue
            seen.add(key)
            conflict_sources.append(metadata)
        return RAGAnswer(
            response=CONFLICTING_ANSWER,
            sources=conflict_sources,
            grounding_status="conflicting_sources",
            needs_escalation=True,
            citations=conflict_sources,
        )

    return RAGAnswer(
        response=" ".join(selected_sentences),
        sources=sources,
        grounding_status="grounded",
        needs_escalation=False,
        citations=sources,
    )


class LocalRAGService:
    """Index and retrieve user-owned PDF chunks through the local database."""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("Invalid chunking configuration")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def _extract_pages(
        self,
        file_value: Any,
        filename: str,
        *,
        max_size: int | None = None,
    ) -> tuple[list[ExtractedPage], bytes]:
        """Read and parse one supported local upload."""

        payload = _read_binary_payload(file_value, max_size=max_size)
        normalized_filename = filename.casefold()
        if normalized_filename.endswith(".pdf"):
            try:
                pages = extract_pdf_pages(BytesIO(payload))
            except Exception as exc:  # pdfminer exposes several parser errors.
                raise ValueError("The uploaded file could not be read as a PDF.") from exc
        elif normalized_filename.endswith(".txt"):
            pages = extract_txt_pages(payload)
        else:
            raise ValueError("Only PDF and UTF-8 TXT files are supported.")
        if not pages:
            raise ValueError("The document does not contain extractable text.")
        return pages, payload

    def index_file(
        self,
        user_id: int,
        file_value: Any,
        filename: str,
        *,
        title: str | None = None,
        category: str = "general",
        version: str = "1.0",
        access_scope: str = "private",
        verification_status: str = "unverified",
        max_size: int | None = None,
    ) -> Document:
        """Index a PDF/TXT upload and stage its metadata and chunks.

        The surrounding request owns the transaction.  A same-user upload with
        the same checksum is treated as idempotent and returns the existing
        document rather than creating duplicate chunks.
        """

        safe_filename = normalize_text(filename) or "uploaded.txt"
        pages, payload = self._extract_pages(file_value, safe_filename, max_size=max_size)
        checksum = hashlib.sha256(payload).hexdigest()
        existing = Document.query.filter_by(user_id=user_id, checksum=checksum).first()
        if existing is not None:
            return existing

        chunk_rows: list[tuple[int, str]] = []
        full_text_parts: list[str] = []
        for page in pages:
            full_text_parts.append(page.text)
            for chunk in chunk_text(
                page.text,
                chunk_size=self.chunk_size,
                overlap=self.overlap,
            ):
                chunk_rows.append((page.page_number, chunk))

        if not chunk_rows:
            raise ValueError("The document does not contain extractable text.")

        full_text = "\n\n".join(full_text_parts)
        document = Document(
            user_id=user_id,
            filename=safe_filename,
            title=normalize_text(title or safe_filename)[:255],
            category=normalize_text(category)[:80] or "general",
            version=normalize_text(version)[:64] or "1.0",
            access_scope=normalize_text(access_scope)[:32] or "private",
            verification_status=normalize_text(verification_status)[:32] or "unverified",
            ingestion_status="ready",
            checksum=checksum,
            summary=summarize_text(full_text),
            keywords=",".join(extract_keywords(full_text)),
        )
        db.session.add(document)
        db.session.flush()

        for chunk_index, (page_number, text) in enumerate(chunk_rows):
            db.session.add(
                DocumentChunk(
                    document_id=document.id,
                    page_number=page_number,
                    chunk_index=chunk_index,
                    text=text,
                )
            )

        db.session.flush()
        return document

    def index_pdf(self, user_id: int, pdf_file: Any, filename: str) -> Document:
        """Extract and stage a PDF's chunks for a user.

        The caller owns the surrounding transaction. The new document and
        chunks are flushed so their IDs are available before the chat record is
        written, but they are committed together with that record by the app.
        """

        return self.index_file(user_id, pdf_file, filename)

    def retrieve(
        self,
        user_id: int,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        document_id: int | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """Retrieve only the best chunks belonging to ``user_id``."""

        query_builder = DocumentChunk.query.join(Document).filter(Document.user_id == user_id)
        if document_id is not None:
            query_builder = query_builder.filter(Document.id == document_id)
        chunks = query_builder.order_by(DocumentChunk.id.asc()).all()
        return rank_chunks(query, chunks, top_k=top_k)

    def answer(
        self,
        user_id: int,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        document_id: int | None = None,
    ) -> RAGAnswer:
        """Return a grounded extractive answer for one user's indexed corpus."""

        started = time.perf_counter()
        result = answer_from_matches(
            query,
            self.retrieve(user_id, query, top_k=top_k, document_id=document_id),
        )
        return replace(result, latency_ms=max(0, round((time.perf_counter() - started) * 1000)))
